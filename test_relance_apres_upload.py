"""
Test manuel — correctif du 2026-08-24 (blocage après upload de document).

Bug réel remonté en test terrain : après avoir envoyé la photo demandée, le
dialogue restait SILENCIEUX — le citoyen (potentiellement analphabète) n'a
aucun moyen de deviner qu'il doit reparler pour que la conversation continue.
Diagnostic (test_diagnostic_blocage_upload.py) : le backend n'était PAS
deadlocké (si le citoyen reparle, ça fonctionne), mais rien ne relançait la
conversation tout seul.

Ce test vérifie le VRAI correctif : upload via le VRAI endpoint REST
(`POST /dossiers/{id}/documents`, pas un appel direct à upload_document()),
PENDANT qu'une connexion WebSocket est ouverte sur la même session — SANS
envoyer aucun nouvel audio — et vérifie qu'une relance (confirmation + question
suivante) arrive bien, poussée automatiquement sur cette même connexion.
"""
import json
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient

import main  # noqa: E402
from test_bascule_administratif import TEST_CITOYEN_ID, TEST_COMMUNE

SESSION_ID = "test_relance_upload_session"

_MESSAGES_CITOYEN = iter([
    "comment avoir un extrait de naissance pour mon fils",  # 1: information
    "oui je veux bien commencer",                            # 2: bascule
    "il a 7 jours",                                          # 3: age_enfant
    "à Tambacounda",                                          # 4: commune_naissance -> attente_upload
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


def generer_png_bidon() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"0" * 50


def main_test():
    main.verify_token = _fake_verify_token
    main.get_user_profile = _fake_get_user_profile
    main.transcribe_audio = _fake_transcribe_audio
    main.tts_service.synthesize_stream = _fake_synthesize_stream
    main.app.dependency_overrides[main.get_current_user] = lambda: {"id": TEST_CITOYEN_ID, "commune": TEST_COMMUNE}

    client = TestClient(main.app)

    with client.websocket_connect(f"/ws/{SESSION_ID}?token=fake-token-relance") as ws:
        for i, libelle in enumerate(["information", "bascule", "age_enfant", "commune_naissance"], start=1):
            ws.send_bytes(b"\x00\x01audio-bidon")
            messages = lire_jusqua(ws, "end")
            stream_fr = next((m["content"] for m in messages if m.get("type") == "stream_fr"), None)
            print(f"=== Tour {i} ({libelle}) ===\nAgent (fr) : {stream_fr}\n")

        etat = main.dossier_sessions[SESSION_ID]
        dossier_id = etat["dossier_id"]
        assert dossier_id, "le dossier n'a pas été créé"
        assert SESSION_ID in main.active_websockets, "la connexion WS devrait être enregistrée dans active_websockets"
        print(f"dossier_id={dossier_id} — attente du document 'certificat_naissance'\n")

        # --- LE VRAI TEST : upload via le VRAI endpoint REST, SANS renvoyer
        # aucun audio sur le WS ensuite. ---
        print("📤 Upload réel via POST /dossiers/{id}/documents (comme le ferait le mobile)...")
        response = client.post(
            f"/dossiers/{dossier_id}/documents",
            data={"type": "certificat_naissance"},
            files={"fichier": ("certificat.png", generer_png_bidon(), "image/png")},
        )
        assert response.status_code == 200, f"upload échoué : {response.status_code} {response.text}"
        print(f"Upload OK : {response.json()}\n")

        # Aucun send_bytes ici — on lit directement ce qui arrive sur le WS.
        print("=== Relance poussée automatiquement (aucun audio envoyé) ===")
        messages_relance = lire_jusqua(ws, "end")
        stream_fr_relance = next((m["content"] for m in messages_relance if m.get("type") == "stream_fr"), None)
        print(f"Agent (fr) : {stream_fr_relance}")

        assert stream_fr_relance, (
            "AUCUNE relance reçue après l'upload sans reparler — le bug n'est PAS corrigé, "
            "le citoyen serait toujours bloqué en silence."
        )
        assert "enfant" in stream_fr_relance.lower() or "nom" in stream_fr_relance.lower(), (
            f"la relance ne semble pas être la bonne question (nom_enfant attendu) : {stream_fr_relance!r}"
        )
        print("\n✅ Correctif validé : la conversation a repris TOUTE SEULE après l'upload, sans que le "
              "citoyen ait besoin de reparler.")

    main.app.dependency_overrides.clear()


if __name__ == "__main__":
    main_test()
