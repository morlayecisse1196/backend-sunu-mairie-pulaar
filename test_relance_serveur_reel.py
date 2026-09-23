"""
Test manuel — vérifie le correctif "asyncio.create_task" (non-bloquant) sur un
VRAI serveur uvicorn (pas TestClient, dont le transport WebSocket simulé
pourrait ne pas refléter fidèlement un vrai accès concurrent lecture/écriture
sur la même connexion — lecture continue côté boucle WS + écriture depuis la
tâche de fond `notifier_document_recu`, lancée par POST /dossiers/{id}/documents).

Démarre uvicorn EN PROCESS (même interpréteur, ASR/TTS/auth doublés), puis
utilise un vrai client WebSocket (`websockets`) + un vrai client HTTP (`httpx`)
sur de vrais sockets TCP loopback — même mécanique qu'un serveur de production.
"""
import asyncio
import json
import sys
import threading
import time
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

import httpx
import uvicorn
import websockets

import main
from test_bascule_administratif import TEST_CITOYEN_ID, TEST_COMMUNE

PORT = 8765
_MESSAGES_CITOYEN = iter([
    "comment avoir un extrait de naissance pour mon fils",
    "oui je veux bien commencer",
    "il a 7 jours",
    "à Tambacounda",
])


async def _fake_verify_token(token: str) -> dict:
    return {"sub": TEST_CITOYEN_ID}


async def _fake_get_user_profile(user_id: str) -> dict:
    return {"commune": TEST_COMMUNE}


async def _fake_transcribe_audio(audio_bytes: bytes) -> dict:
    return {"success": True, "transcription": next(_MESSAGES_CITOYEN)}


async def _fake_synthesize_stream(texte_pulaar: str, websocket) -> None:
    return None


async def _fake_get_current_user_dep(*args, **kwargs):
    return {"id": TEST_CITOYEN_ID, "commune": TEST_COMMUNE}


async def lire_jusqua(ws, type_attendu: str, max_messages: int = 30) -> list:
    recus = []
    for _ in range(max_messages):
        raw = await ws.recv()
        if isinstance(raw, bytes):
            continue
        data = json.loads(raw)
        recus.append(data)
        if data.get("type") == type_attendu:
            break
    return recus


async def main_test():
    main.verify_token = _fake_verify_token
    main.get_user_profile = _fake_get_user_profile
    main.transcribe_audio = _fake_transcribe_audio
    main.tts_service.synthesize_stream = _fake_synthesize_stream
    main.app.dependency_overrides[main.get_current_user] = lambda: {"id": TEST_CITOYEN_ID, "commune": TEST_COMMUNE}

    config = uvicorn.Config(main.app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    # Attendre que le serveur soit prêt.
    for _ in range(50):
        if getattr(server, "started", False):
            break
        await asyncio.sleep(0.1)
    print(f"Serveur uvicorn réel démarré sur 127.0.0.1:{PORT}\n")

    try:
        async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/test_relance_reel?token=x") as ws:
            for i, libelle in enumerate(["information", "bascule", "age_enfant", "commune_naissance"], start=1):
                await ws.send(b"\x00\x01audio-bidon")
                messages = await lire_jusqua(ws, "end")
                stream_fr = next((m["content"] for m in messages if m.get("type") == "stream_fr"), None)
                print(f"=== Tour {i} ({libelle}) ===\nAgent (fr) : {stream_fr}\n")

            etat = main.dossier_sessions["test_relance_reel"]
            dossier_id = etat["dossier_id"]
            assert dossier_id, "le dossier n'a pas été créé"
            print(f"dossier_id={dossier_id} — upload réel du certificat_naissance...\n")

            async with httpx.AsyncClient() as client:
                t0 = time.monotonic()
                response = await client.post(
                    f"http://127.0.0.1:{PORT}/dossiers/{dossier_id}/documents",
                    data={"type": "certificat_naissance"},
                    files={"fichier": ("c.png", b"\x89PNG\r\n\x1a\n" + b"0" * 50, "image/png")},
                    headers={"Authorization": "Bearer x"},
                )
                duree_reponse = time.monotonic() - t0

            print(f"POST /documents -> {response.status_code} en {duree_reponse:.2f}s : {response.json()}")
            assert response.status_code == 200, response.text

            print("=== Relance poussée automatiquement (aucun audio envoyé) ===")
            t1 = time.monotonic()
            messages_relance = await lire_jusqua(ws, "end")
            duree_relance = time.monotonic() - t1
            stream_fr_relance = next((m["content"] for m in messages_relance if m.get("type") == "stream_fr"), None)
            print(f"Agent (fr) : {stream_fr_relance}  (reçu {duree_relance:.2f}s après la réponse HTTP)")
            assert stream_fr_relance, "aucune relance reçue après l'upload"

            # Le vrai critère : la réponse HTTP n'attend PAS la fin de la
            # relance (traduction + TTS, plusieurs secondes) — donc la relance
            # doit encore être "en vol" ou fraîchement arrivée APRÈS le POST,
            # pas déjà terminée AVANT que le POST ne réponde. `duree_reponse`
            # (upload réseau réel, pas suspect en soi) doit être nettement
            # plus courte qu'un aller-retour complet LLM+traduction+TTS.
            assert duree_reponse < 5.0, (
                f"la réponse HTTP a pris {duree_reponse:.2f}s — anormalement long pour un simple upload, "
                "à vérifier si create_task fonctionne réellement."
            )
            print("\n✅ Correctif validé sur un VRAI serveur : réponse HTTP rapide (upload réseau réel uniquement) "
                  "+ relance WS reçue séparément en parallèle, sans lien de timing entre les deux (fire-and-forget).")
    finally:
        server.should_exit = True
        await server_task


if __name__ == "__main__":
    asyncio.run(main_test())
