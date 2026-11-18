# asr_client.py
import os
import asyncio
import httpx
from typing import Dict, Any

from temps_reel.audio import DUREE_MAX_SECONDES

ASR_API_URL = os.getenv("ASR_API_URL", "https://morlayecis0003-whisper-pulaar-api.hf.space")

# Les Hugging Face Spaces gratuits s'endorment après inactivité : le premier
# appel peut prendre 30-60s le temps du "cold start". On retente une fois
# avec un délai avant d'abandonner, plutôt que de faire échouer le tour immédiatement.
ASR_RETRIES = 1
ASR_RETRY_DELAY_SECONDS = 5.0

# Le délai n'est plus un chiffre choisi à part : il DÉCOULE de la durée d'audio
# que le backend accepte.
#
# Avant, les deux vivaient chacun de leur côté — 60 s acceptées dans
# `temps_reel/audio.py`, 60 s de patience ici — et le compte n'y était pas : le
# Space transcrit à ~1,8 fois le temps réel (31,4 s d'audio → 56,0 s de calcul,
# mesuré sur la production le 2026-11-17). Un audio que le backend déclarait
# valable dépassait donc le délai, et le citoyen payait le réessai : 42,7 s
# d'audio lui coûtaient 1 min 51 d'attente, et le Space transcrivait deux fois
# le même fichier, faute de savoir que le client avait renoncé.
#
# La marge couvre le téléversement, la mise en file et la variation de charge
# du Space ; le réessai, lui, reste pour le cold start, qui n'a rien à voir
# avec la durée de l'audio.
FACTEUR_TEMPS_REEL_MESURE = 1.8
MARGE_SECONDES = 20.0
DELAI_SECONDES = DUREE_MAX_SECONDES * FACTEUR_TEMPS_REEL_MESURE + MARGE_SECONDES

async def transcribe_audio(audio_bytes: bytes) -> Dict[str, Any]:
    """
    Envoie des bytes audio à l'API ASR et retourne la transcription.
    Retente une fois en cas d'erreur transitoire (timeout, 502/503/504 — typique
    d'un cold start de Hugging Face Space).
    """
    last_error = None
    for attempt in range(ASR_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=DELAI_SECONDES) as client:
                files = {"audio": ("audio.wav", audio_bytes, "audio/wav")}
                response = await client.post(
                    f"{ASR_API_URL}/transcribe",
                    files=files
                )
                response.raise_for_status()
                return response.json()
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            last_error = e
        except httpx.HTTPStatusError as e:
            last_error = e
            if e.response.status_code not in (502, 503, 504):
                break  # erreur non transitoire (ex: 400), inutile de retenter

        if attempt < ASR_RETRIES:
            await asyncio.sleep(ASR_RETRY_DELAY_SECONDS)

    return {"success": False, "error": f"Service ASR indisponible : {last_error}"}