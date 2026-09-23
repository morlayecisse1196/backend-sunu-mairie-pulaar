"""
Test manuel — correctif du 2026-08-24 (salutation répétée + questions générales).

Deux bugs réels remontés :
  1. L'agent disait "Salam" à CHAQUE tour de la conversation, pas seulement au
     début (SYSTEM_PROMPT_FORMATTER — ses deux exemples commençaient tous les
     deux par "Salam.", sans distinction premier tour/tour suivant).
  2. Une question générale ("bonjour, comment tu peux m'aider ?", "c'est quoi
     une démarche ?", "pourquoi mon enfant a besoin de documents, quels sont
     les risques ?") recevait toujours "Je n'ai pas trouvé de démarche
     correspondante" au lieu d'une réponse courte utile suivie d'une question
     invitante.

Exerce le VRAI /ws/{session_id} (ASR doublé, LLM + formateur réels) pour
vérifier les DEUX correctifs ensemble, dans une vraie conversation.
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

SESSION_ID = "test_salutation_questions_session"

_MESSAGES_CITOYEN = iter([
    "Bonjour, comment tu peux m'aider ?",                              # 1: général (+ premier tour -> Salam attendu)
    "C'est quoi une démarche ?",                                       # 2: général (pas premier tour -> PAS de Salam)
    "Pourquoi mon enfant a besoin de documents, quels sont les risques ?",  # 3: général (idem)
])


async def _fake_verify_token(token: str) -> dict:
    return {"sub": TEST_CITOYEN_ID}


async def _fake_get_user_profile(user_id: str) -> dict:
    return {"commune": TEST_COMMUNE}


async def _fake_transcribe_audio(audio_bytes: bytes) -> dict:
    return {"success": True, "transcription": next(_MESSAGES_CITOYEN)}


async def _fake_synthesize_stream(texte_pulaar: str, websocket) -> None:
    return None


def lire_tour(ws, max_messages: int = 40) -> dict:
    """Lit un tour complet, retourne {stream_fr, stream_pulaar (concaténé)}."""
    stream_fr = None
    pulaar_parts = []
    for _ in range(max_messages):
        msg = ws.receive()
        if "text" not in msg:
            continue
        data = json.loads(msg["text"])
        if data.get("type") == "stream_fr":
            stream_fr = data["content"]
        elif data.get("type") == "stream_pulaar":
            pulaar_parts.append(data["content"])
        elif data.get("type") == "end":
            break
    return {"stream_fr": stream_fr, "stream_pulaar": "".join(pulaar_parts)}


def main_test():
    main.verify_token = _fake_verify_token
    main.get_user_profile = _fake_get_user_profile
    main.transcribe_audio = _fake_transcribe_audio
    main.tts_service.synthesize_stream = _fake_synthesize_stream

    client = TestClient(main.app)

    with client.websocket_connect(f"/ws/{SESSION_ID}?token=fake-token-salutation") as ws:
        # --- Tour 1 : salutation + question générale, PREMIER tour -> Salam attendu ---
        ws.send_bytes(b"\x00\x01audio-bidon-1")
        tour1 = lire_tour(ws)
        print("=== Tour 1 (\"Bonjour, comment tu peux m'aider ?\") ===")
        print("FR    :", tour1["stream_fr"])
        print("Pulaar:", tour1["stream_pulaar"])

        assert tour1["stream_fr"], "aucune réponse reçue au tour 1"
        texte_bas = tour1["stream_fr"].lower()
        assert "trouvé de démarche correspondante" not in texte_bas, (
            f"régression : réponse générale rejetée avec le refus générique : {tour1['stream_fr']!r}"
        )
        assert "?" in tour1["stream_fr"], "la réponse générale devrait se terminer par une question invitante"
        assert "salam" in tour1["stream_pulaar"].lower(), (
            f"le premier tour devrait commencer par 'Salam' : {tour1['stream_pulaar']!r}"
        )
        print("OK - tour 1 : réponse utile (pas de refus générique), question invitante, Salam présent.\n")

        # --- Tour 2 : autre question générale, PAS le premier tour -> PAS de Salam ---
        ws.send_bytes(b"\x00\x01audio-bidon-2")
        tour2 = lire_tour(ws)
        print("=== Tour 2 (\"C'est quoi une démarche ?\") ===")
        print("FR    :", tour2["stream_fr"])
        print("Pulaar:", tour2["stream_pulaar"])

        assert tour2["stream_fr"], "aucune réponse reçue au tour 2"
        assert "trouvé de démarche correspondante" not in tour2["stream_fr"].lower(), (
            f"régression : réponse générale rejetée avec le refus générique : {tour2['stream_fr']!r}"
        )
        assert "salam" not in tour2["stream_pulaar"].lower(), (
            f"BUG : salutation répétée à un tour qui n'est PAS le premier : {tour2['stream_pulaar']!r}"
        )
        print("OK - tour 2 : réponse utile, PAS de 'Salam' répété (ce n'est plus le premier tour).\n")

        # --- Tour 3 : question de sensibilisation, toujours pas de Salam ---
        ws.send_bytes(b"\x00\x01audio-bidon-3")
        tour3 = lire_tour(ws)
        print("=== Tour 3 (\"Pourquoi mon enfant a besoin de documents, quels sont les risques ?\") ===")
        print("FR    :", tour3["stream_fr"])
        print("Pulaar:", tour3["stream_pulaar"])

        assert tour3["stream_fr"], "aucune réponse reçue au tour 3"
        assert "trouvé de démarche correspondante" not in tour3["stream_fr"].lower(), (
            f"régression : réponse générale rejetée avec le refus générique : {tour3['stream_fr']!r}"
        )
        assert "salam" not in tour3["stream_pulaar"].lower(), (
            f"BUG : salutation répétée à un tour qui n'est PAS le premier : {tour3['stream_pulaar']!r}"
        )
        print("OK - tour 3 : réponse utile sur les risques, toujours pas de 'Salam' répété.\n")

    print("Correctifs validés : questions générales traitées utilement (pas de refus générique),")
    print("et 'Salam' réservé au tout premier tour de la conversation.")


if __name__ == "__main__":
    main_test()
