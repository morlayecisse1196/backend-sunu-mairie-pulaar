"""
Diagnostic — blocage signalé après upload de document (test terrain du 2026-08-24).

Question : le backend redémarre-t-il correctement la conversation SI le
citoyen reparle après avoir uploadé une photo, ou le blocage vient-il d'une
vraie régression serveur (pas seulement d'un manque de relance côté mobile) ?

Exerce le VRAI /ws/{session_id} (comme test_websocket_j5.py), avec un
véritable upload_document() entre deux tours WS, pour isoler la cause.
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

SESSION_ID = "test_diag_blocage_session"

_MESSAGES_CITOYEN = iter([
    "comment avoir un extrait de naissance pour mon fils",  # 1: information
    "oui je veux bien commencer",                            # 2: bascule
    "il a 7 jours",                                          # 3: age_enfant
    "à Tambacounda",                                          # 4: commune_naissance -> déclenche attente_upload
    "d'accord je viens d'envoyer la photo",                   # 5: APRÈS upload réel -> doit avancer à nom_enfant
])


async def _fake_verify_token(token: str) -> dict:
    return {"sub": TEST_CITOYEN_ID}


async def _fake_get_user_profile(user_id: str) -> dict:
    return {"commune": TEST_COMMUNE}


async def _fake_transcribe_audio(audio_bytes: bytes) -> dict:
    return {"success": True, "transcription": next(_MESSAGES_CITOYEN)}


async def _fake_synthesize_stream(texte_pulaar: str, websocket) -> None:
    return None


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

    with client.websocket_connect(f"/ws/{SESSION_ID}?token=fake-token-diag") as ws:
        for i, libelle in enumerate(["information", "bascule", "age_enfant", "commune_naissance"], start=1):
            ws.send_bytes(b"\x00\x01audio-bidon")
            messages = lire_jusqua(ws, "end")
            stream_fr = next((m["content"] for m in messages if m.get("type") == "stream_fr"), None)
            print(f"=== Tour {i} ({libelle}) ===\nAgent (fr) : {stream_fr}\n")

        etat = main.dossier_sessions[SESSION_ID]
        dossier_id = etat["dossier_id"]
        assert dossier_id, "le dossier n'a pas été créé"
        print(f"dossier_id={dossier_id}  document_attendu en attente ? documents_demandes={etat['documents_demandes']}")

        # Simule EXACTEMENT ce que fait le mobile : upload RÉEL via l'endpoint REST
        # (ici on appelle directement upload_document(), équivalent à ce que fait
        # POST /dossiers/{id}/documents — même fonction repo utilisée).
        doc = upload_document(dossier_id, "certificat_naissance", b"\x89PNG\r\n\x1a\n" + b"0" * 50, "image/png", "png")
        assert doc, "upload réel échoué"
        print(f"\n📤 Document réellement uploadé (comme le ferait le mobile) : {doc['id']}\n")

        # Le citoyen reparle ENSUITE (tour 5) — EST-CE QUE ÇA DÉBLOQUE VRAIMENT ?
        print("=== Tour 5 (le citoyen reparle APRÈS l'upload) ===")
        ws.send_bytes(b"\x00\x01audio-bidon-apres-upload")
        messages5 = lire_jusqua(ws, "end")
        stream_fr_5 = next((m["content"] for m in messages5 if m.get("type") == "stream_fr"), None)
        print(f"Agent (fr) : {stream_fr_5}")

        etat_apres = main.dossier_sessions[SESSION_ID]
        print(f"\nslots après tour 5 : {etat_apres['slots']}")

        if stream_fr_5 and ("nom" in stream_fr_5.lower() or "enfant" in stream_fr_5.lower()):
            print("\n✅ Le backend a bien redémarré la conversation (nouvelle question posée). "
                  "Le blocage n'est PAS une régression backend — le citoyen doit reparler après "
                  "l'upload, ce que le mobile ne semble pas inviter clairement à faire (ou l'app "
                  "reste bloquée avant même que le citoyen puisse reparler).")
        else:
            print("\n❌ Le backend N'A PAS redémarré la conversation correctement — vraie régression serveur.")


if __name__ == "__main__":
    main_test()
