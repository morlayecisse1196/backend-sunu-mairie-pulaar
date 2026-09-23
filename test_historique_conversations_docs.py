"""
Test manuel — validation réelle des 3 fonctionnalités mobile demandées le
2026-09-10 (backend uniquement — la page profil ne nécessite AUCUN backend,
cf. décision utilisateur : Supabase Auth user_metadata suffit) :

1. Historique des conversations persistant (migration 010, conversations_repo.py)
   + endpoint de replay audio à la demande.
2. Liste des documents uploadés par le citoyen pendant le dialogue
   (GET /mes-dossiers/{id}/documents, gap réel trouvé — n'existait pas).

Même principe que test_websocket_j5.py (dont ce test réutilise le pattern) :
exerce le VRAI endpoint /ws/{session_id}, ASR/TTS-stream doublés (pas de
micro/Space HF disponible ici), LLM + Supabase réels. La synthèse TTS du
replay (tts_service.synthesize_text, PAS doublée ici) est en revanche réelle —
c'est justement ce qu'on veut valider pour la fonctionnalité "réécouter".
"""
import asyncio
import json
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient

import main  # noqa: E402
from dossiers_repo import upload_document
from test_bascule_administratif import TEST_CITOYEN_ID, TEST_COMMUNE

SESSION_ID = "test_historique_conv_session"

_MESSAGES_CITOYEN = iter([
    "comment avoir un extrait de naissance pour mon fils",  # tour 1 : information
    "oui je veux bien commencer",                            # tour 2 : bascule administratif
])


async def _fake_verify_token(token: str) -> dict:
    return {"sub": TEST_CITOYEN_ID}


async def _fake_get_user_profile(user_id: str) -> dict:
    return {"commune": TEST_COMMUNE}


async def _fake_transcribe_audio(audio_bytes: bytes) -> dict:
    return {"success": True, "transcription": next(_MESSAGES_CITOYEN)}


async def _fake_synthesize_stream(texte_pulaar: str, websocket) -> None:
    return None  # TTS streamé en direct hors périmètre — le replay (synthesize_text) reste réel


def lire_jusqua(ws, type_attendu: str, max_messages: int = 30) -> list:
    recus = []
    for _ in range(max_messages):
        msg = ws.receive()
        if "text" in msg:
            data = json.loads(msg["text"])
            recus.append(data)
            if data.get("type") == type_attendu:
                break
        elif "bytes" in msg:
            recus.append({"type": "audio_bytes", "len": len(msg["bytes"])})
    return recus


def main_test():
    main.verify_token = _fake_verify_token
    main.get_user_profile = _fake_get_user_profile
    main.transcribe_audio = _fake_transcribe_audio
    main.tts_service.synthesize_stream = _fake_synthesize_stream

    client = TestClient(main.app)

    with client.websocket_connect(f"/ws/{SESSION_ID}?token=fake-token-test-historique") as ws:
        print("=== Tour 1 (information) ===")
        ws.send_bytes(b"\x00\x01audio-bidon-tour-1")
        messages1 = lire_jusqua(ws, "end")
        stream_fr_1 = next(m["content"] for m in messages1 if m.get("type") == "stream_fr")
        print("Agent (fr) :", stream_fr_1)

        print("\n=== Tour 2 (bascule administratif) ===")
        ws.send_bytes(b"\x00\x01audio-bidon-tour-2")
        messages2 = lire_jusqua(ws, "end")
        stream_fr_2 = next(m["content"] for m in messages2 if m.get("type") == "stream_fr")
        print("Agent (fr) :", stream_fr_2)

        etat = main.dossier_sessions[SESSION_ID]
        assert etat["mode"] == "administratif"
        dossier_id = etat["dossier_id"]
        assert dossier_id
        print(f"Dossier créé : {dossier_id}")

    # --- 1. Persistance réelle en base (conversations_repo directement) ---
    print("\n=== Vérification en base (conversations_repo) ===")
    import conversations_repo
    conversation = None
    for c in conversations_repo.list_conversations_citoyen(TEST_CITOYEN_ID):
        if c["session_id"] == SESSION_ID:
            conversation = c
            break
    assert conversation, "aucune conversation persistée pour cette session"
    print(f"Conversation : id={conversation['id']} mode={conversation['mode']} dossier_id={conversation['dossier_id']} titre={conversation['titre']!r}")
    assert conversation["mode"] == "administratif", "la conversation n'a pas suivi la bascule information -> administratif"
    assert conversation["dossier_id"] == dossier_id, "dossier_id pas mis à jour sur la conversation après bascule"
    assert conversation["titre"] and "extrait de naissance" in conversation["titre"].lower(), (
        f"titre pas dérivé du premier message : {conversation['titre']!r}"
    )
    print("OK - conversation créée en mode 'information', bien mise à jour en 'administratif' + dossier_id après bascule.")

    messages_bd = conversations_repo.list_messages(conversation["id"])
    print(f"\n{len(messages_bd)} message(s) persisté(s) :")
    for m in messages_bd:
        print(f"  [{m['role']:9s}] fr={m['contenu_fr']!r:60s} pulaar={'(présent)' if m['contenu_pulaar'] else None}")
    assert len(messages_bd) == 4, f"attendu 4 messages (2 tours x user+assistant), obtenu {len(messages_bd)}"
    assert messages_bd[0]["role"] == "user" and messages_bd[0]["contenu_fr"] == "comment avoir un extrait de naissance pour mon fils"
    assert messages_bd[1]["role"] == "assistant" and messages_bd[1]["contenu_fr"] == stream_fr_1
    assert messages_bd[1]["contenu_pulaar"], "contenu_pulaar absent sur le message assistant (attendu : traduction réelle)"
    assert messages_bd[2]["role"] == "user" and messages_bd[2]["contenu_fr"] == "oui je veux bien commencer"
    assert messages_bd[3]["role"] == "assistant" and messages_bd[3]["contenu_fr"] == stream_fr_2
    print("OK - les 4 messages sont dans le bon ordre, avec le bon contenu FR + pulaar présent côté assistant.")

    # --- 2. Endpoints REST réels (GET /mes-conversations, détail, audio) ---
    print("\n=== Endpoints REST /mes-conversations ===")
    main.app.dependency_overrides[main.get_current_user] = lambda: {"id": TEST_CITOYEN_ID, "commune": TEST_COMMUNE}

    r_liste = client.get("/mes-conversations")
    assert r_liste.status_code == 200, r_liste.text
    ids_liste = [c["id"] for c in r_liste.json()["conversations"]]
    assert conversation["id"] in ids_liste
    print(f"OK - GET /mes-conversations : {len(ids_liste)} conversation(s), la nôtre y figure bien.")

    r_detail = client.get(f"/mes-conversations/{conversation['id']}")
    assert r_detail.status_code == 200, r_detail.text
    detail = r_detail.json()
    assert len(detail["messages"]) == 4
    print("OK - GET /mes-conversations/{id} : le détail complet (4 messages) est bien renvoyé.")

    message_assistant_id = messages_bd[1]["id"]
    print(f"\n=== Replay audio réel du message assistant {message_assistant_id} ===")
    r_audio = client.get(f"/mes-conversations/{conversation['id']}/messages/{message_assistant_id}/audio")
    assert r_audio.status_code == 200, r_audio.text
    assert len(r_audio.content) > 1000, f"audio suspicieusement petit ({len(r_audio.content)} octets)"
    print(f"OK - audio réel resynthétisé à la demande : {len(r_audio.content)} octets ({r_audio.headers.get('content-type')}).")

    message_user_id = messages_bd[0]["id"]
    r_audio_user = client.get(f"/mes-conversations/{conversation['id']}/messages/{message_user_id}/audio")
    assert r_audio_user.status_code == 400, r_audio_user.text
    print(f"OK - replay refusé pour un message 'user' (400 explicite) : {r_audio_user.json()['detail']}")

    # --- 3. Isolation : un autre citoyen ne peut pas lire cette conversation ---
    main.app.dependency_overrides[main.get_current_user] = lambda: {"id": "un-autre-citoyen-uuid", "commune": TEST_COMMUNE}
    r_interdit = client.get(f"/mes-conversations/{conversation['id']}")
    assert r_interdit.status_code == 403, r_interdit.text
    print(f"OK - un autre citoyen reçoit bien 403 sur cette conversation : {r_interdit.json()['detail']}")

    # --- 4. GET /mes-dossiers/{id}/documents (Feature 1b) ---
    main.app.dependency_overrides[main.get_current_user] = lambda: {"id": TEST_CITOYEN_ID, "commune": TEST_COMMUNE}
    print(f"\n=== GET /mes-dossiers/{dossier_id}/documents ===")
    assert upload_document(dossier_id, "certificat_naissance", b"\x89PNG\r\n\x1a\n" + b"X" * 50, "image/png", "png")
    r_docs = client.get(f"/mes-dossiers/{dossier_id}/documents")
    assert r_docs.status_code == 200, r_docs.text
    documents = r_docs.json()["documents"]
    assert len(documents) == 1 and documents[0]["type"] == "certificat_naissance"
    assert documents[0].get("url_signee"), "URL signée absente"
    print(f"OK - {len(documents)} document(s) visibles côté citoyen, avec URL signée réelle.")

    main.app.dependency_overrides.clear()
    print("\n✅ Historique des conversations + replay audio + documents citoyen : validés réellement.")


if __name__ == "__main__":
    main_test()
