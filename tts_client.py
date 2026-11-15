# tts_client.py
# Client HTTP vers le Space HF dédié à la synthèse vocale pulaar (GPU) —
# voir ANCIEN_CODE_HF_SPACE/ pour le code du Space lui-même. Même logique de
# retry que asr_client.py : le Space peut avoir un cold start après inactivité.
import os
import asyncio
import httpx

from services.pulaar import texte_pour_synthese

TTS_API_URL = os.getenv("TTS_API_URL", "https://morlayecis0003-tts-pulaar-docker.hf.space")
TTS_API_KEY = os.getenv("TTS_API_KEY")  # optionnel — doit matcher le secret TTS_API_KEY du Space

TTS_RETRIES = 1
TTS_RETRY_DELAY_SECONDS = 5.0
# Timeout par défaut : suffisant pour UNE phrase courte (conversation vocale,
# synthesize_stream). Un texte long (narration complète d'une démarche) a
# besoin de plus de marge — voir NARRATION_TIMEOUT_SECONDS, utilisé par
# tts_service.synthesize_text() — d'autant plus tant que le Space tourne sur
# CPU (avant activation du tier GPU).
TTS_TIMEOUT_SECONDS = 60.0
NARRATION_TIMEOUT_SECONDS = 150.0


class TTSError(Exception):
    """Erreur de synthèse distante (Space injoignable, erreur HTTP, texte vide, etc.)."""


async def synthesize_remote(text: str, timeout: float = TTS_TIMEOUT_SECONDS) -> bytes:
    """
    Appelle POST {TTS_API_URL}/tts et retourne les bytes WAV de la synthèse.
    Retente une fois en cas d'erreur transitoire (timeout, 502/503/504 —
    cold start du Space), comme transcribe_audio() dans asr_client.py.

    Point de passage UNIQUE vers le modèle vocal : c'est donc ici qu'est
    appliquée la préparation du texte (`services.pulaar.texte_pour_synthese`).
    `mms-tts-pul` est monolingue pulaar : il écorche les mots français laissés
    tels quels, et il ne sait pas dire un chiffre — les dix caractères sont
    dans son vocabulaire, mais pratiquement jamais vus à l'entraînement, si
    bien que « 2026 » produit 0,21 s de bruit là où « ujunaaje ɗiɗi e noogas e
    jeegom » en produit 3,09 s de parole. Les deux défauts se corrigent ici, et
    seulement sur le texte *envoyé au modèle* : jamais sur celui affiché au
    citoyen ni sur celui enregistré en base.
    """
    if not TTS_API_URL:
        raise TTSError("TTS_API_URL non défini dans .env")

    text = texte_pour_synthese(text)

    headers = {"Content-Type": "application/json"}
    if TTS_API_KEY:
        headers["X-API-Key"] = TTS_API_KEY

    last_error = None
    for attempt in range(TTS_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{TTS_API_URL}/tts",
                    headers=headers,
                    json={"text": text}
                )
                response.raise_for_status()
                return response.content
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            last_error = e
        except httpx.HTTPStatusError as e:
            last_error = e
            if e.response.status_code not in (502, 503, 504):
                break  # erreur non transitoire (401 clé invalide, 400 texte vide...) : inutile de retenter

        if attempt < TTS_RETRIES:
            await asyncio.sleep(TTS_RETRY_DELAY_SECONDS)

    raise TTSError(f"Service TTS indisponible : {last_error}")
