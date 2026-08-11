# asr_client.py
import os
import asyncio
import httpx
from typing import Dict, Any

ASR_API_URL = os.getenv("ASR_API_URL", "https://morlayecis0003-whisper-pulaar-api.hf.space")

# Les Hugging Face Spaces gratuits s'endorment après inactivité : le premier
# appel peut prendre 30-60s le temps du "cold start". On retente une fois
# avec un délai avant d'abandonner, plutôt que de faire échouer le tour immédiatement.
ASR_RETRIES = 1
ASR_RETRY_DELAY_SECONDS = 5.0

async def transcribe_audio(audio_bytes: bytes) -> Dict[str, Any]:
    """
    Envoie des bytes audio à l'API ASR et retourne la transcription.
    Retente une fois en cas d'erreur transitoire (timeout, 502/503/504 — typique
    d'un cold start de Hugging Face Space).
    """
    last_error = None
    for attempt in range(ASR_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
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