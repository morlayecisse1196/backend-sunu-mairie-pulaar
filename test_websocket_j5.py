"""
Test manuel — Sprint J, Tâche J.5 (câblage de traiter_tour_administratif dans
la vraie boucle WebSocket de main.py).

Les deux tests de non-régression EXPLICITEMENT exigés par J.5
(test_bascule_administratif.py, test_relecture_confirmation.py) passent déjà
sans modification (vérifié séparément) — mais ils reproduisent la logique
EUX-MÊMES via les fonctions exportées de main.py, sans jamais appeler
`websocket_endpoint` réel. Ce test-ci exerce le VRAI endpoint `/ws/{session_id}`
(le "plumbing" réécrit par J.5), pour vérifier que le câblage lui-même
fonctionne, pas seulement les briques qu'il assemble.

Réseau réel pour le LLM (OpenRouter, générateur + formateur) et Supabase —
seuls l'ASR (audio -> texte) et le TTS (texte -> audio, service HF Space
externe, hors périmètre de ce test) sont remplacés par des doublures, pour un
test rapide et déterministe qui ne dépend pas d'un micro ni de la
disponibilité du Space HF.
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
from test_bascule_administratif import TEST_CITOYEN_ID, TEST_COMMUNE

SESSION_ID = "test_j5_ws_session"

# File des transcriptions "reçues" (une par tour) — l'ASR réel n'est pas
# exercé ici (pas d'audio réel disponible dans cet environnement), seul le
# câblage administratif/slot_controller nous intéresse.
_MESSAGES_CITOYEN = iter([
    "comment avoir un extrait de naissance pour mon fils",  # tour 1 : information
    "oui je veux bien commencer",                            # tour 2 : bascule administratif
    "il a 7 jours",                                          # tour 3 : 1er champ (age_enfant, DB-driven)
])


async def _fake_verify_token(token: str) -> dict:
    return {"sub": TEST_CITOYEN_ID}


async def _fake_get_user_profile(user_id: str) -> dict:
    return {"commune": TEST_COMMUNE}


async def _fake_transcribe_audio(audio_bytes: bytes) -> dict:
    return {"success": True, "transcription": next(_MESSAGES_CITOYEN)}


async def _fake_synthesize_stream(texte_pulaar: str, websocket) -> None:
    return None  # pas de TTS réel — hors périmètre de ce test (service HF externe)


def lire_jusqua(ws, type_attendu: str, max_messages: int = 30) -> list:
    """Lit les messages du WS jusqu'à en croiser un du type demandé (inclus)."""
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
    # --- Doublures (ASR/auth/TTS) — le LLM et Supabase restent réels. ---
    main.verify_token = _fake_verify_token
    main.get_user_profile = _fake_get_user_profile
    main.transcribe_audio = _fake_transcribe_audio
    main.tts_service.synthesize_stream = _fake_synthesize_stream

    client = TestClient(main.app)

    with client.websocket_connect(f"/ws/{SESSION_ID}?token=fake-token-test-j5") as ws:
        # Tour 1 : mode information (contenu de l'audio ignoré par la doublure ASR)
        ws.send_bytes(b"\x00\x01audio-bidon-tour-1")
        messages1 = lire_jusqua(ws, "end")
        stream_fr_1 = next(m["content"] for m in messages1 if m.get("type") == "stream_fr")
        print("=== Tour 1 (information) ===")
        print("Agent (fr) :", stream_fr_1)
        assert "extrait de naissance" in stream_fr_1.lower() or "naissance" in stream_fr_1.lower()

        # Tour 2 : "oui" -> bascule administratif RÉELLE (create_dossier en base)
        ws.send_bytes(b"\x00\x01audio-bidon-tour-2")
        messages2 = lire_jusqua(ws, "end")
        stream_fr_2 = next(m["content"] for m in messages2 if m.get("type") == "stream_fr")
        print("\n=== Tour 2 (bascule administratif) ===")
        print("Agent (fr) :", stream_fr_2)

        etat = main.dossier_sessions[SESSION_ID]
        assert etat["mode"] == "administratif", "la bascule ne s'est pas produite"
        assert etat["dossier_id"], "le dossier n'a pas été créé en base"
        print(f"Dossier créé : {etat['dossier_id']}")

        # Preuve que c'est bien le NOUVEAU flux (slot_controller/demarche_champs)
        # qui tourne : la 1ère question posée en administratif doit être celle
        # d'age_enfant (ordre=5 en base), PAS "pour qui demandez-vous..." comme
        # dans l'ancien flux (cf. test_bascule_administratif.py, tour 2).
        assert "âge" in stream_fr_2.lower() or "age" in stream_fr_2.lower(), (
            f"la question posée ne semble pas venir du contrôleur de champ générique : {stream_fr_2!r}"
        )
        print("OK - la question posée vient bien de demarche_champs (age_enfant en 1er), pas de l'ancien flux.")

        # Tour 3 : réponse au 1er champ -> vérifie l'écriture réelle dans slots
        ws.send_bytes(b"\x00\x01audio-bidon-tour-3")
        messages3 = lire_jusqua(ws, "end")
        stream_fr_3 = next(m["content"] for m in messages3 if m.get("type") == "stream_fr")
        print("\n=== Tour 3 (1er champ rempli) ===")
        print("Agent (fr) :", stream_fr_3)

        dossier_relu = main.get_dossier(etat["dossier_id"])
        assert dossier_relu["slots"]["age_enfant"]["valeur"] == 7, (
            f"age_enfant pas persisté correctement via le nouveau flux : {dossier_relu['slots']}"
        )
        print("OK - age_enfant réellement persisté en base via traiter_tour_administratif.")

    print("\nTâche J.5 validée : le VRAI endpoint /ws/{session_id} appelle bien traiter_tour_administratif,")
    print("le résultat est correctement transformé en messages WS et persisté en base.")


if __name__ == "__main__":
    main_test()
