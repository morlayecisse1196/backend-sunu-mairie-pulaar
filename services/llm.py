"""
Client OpenRouter mutualisé (backend v3).

Remplace les appels copiés-collés de main.py/slot_controller.py (un
`httpx.AsyncClient` recréé à chaque appel, payload et retry dupliqués ~8 fois) :
- un client HTTP partagé (connexions réutilisées) ;
- réponses structurées JSON avec rejeu si le contenu est tronqué/invalide
  (observé ~1 appel sur 5-10 sur gemini-2.5-flash, cf. commentaire historique) ;
- rejeu court sur erreurs transitoires (timeout, connexion, 429, 5xx) ;
- flux texte (SSE) pour la traduction pulaar en direct.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Optional

import httpx

from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL
from services.journal import obtenir_logger

MODELE_DIALOGUE = "google/gemini-2.5-flash"
MODELE_TRADUCTION = "google/gemini-2.5-flash"

_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)
_client: Optional[httpx.AsyncClient] = None
log = obtenir_logger("llm")


class ErreurLLM(Exception):
    """Échec définitif d'un appel au modèle (après rejeux)."""


def definir_client(client: Optional[httpx.AsyncClient]) -> None:
    """Injection d'un client (tests : httpx.MockTransport)."""
    global _client
    _client = client


def _obtenir_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=_TIMEOUT)
    return _client


async def fermer() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _entetes() -> dict:
    return {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}


def _transitoire(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


async def _poster(payload: dict, rejeux: int) -> dict:
    derniere: Optional[BaseException] = None
    for tentative in range(rejeux + 1):
        try:
            reponse = await _obtenir_client().post(f"{OPENROUTER_BASE_URL}/chat/completions", headers=_entetes(), json=payload)
            reponse.raise_for_status()
            return reponse.json()
        except Exception as exc:  # noqa: BLE001 — classé ci-dessous
            derniere = exc
            if not _transitoire(exc) or tentative == rejeux:
                break
            await asyncio.sleep(1.0 * (tentative + 1))
    raise ErreurLLM(f"Appel au modèle échoué : {type(derniere).__name__}") from derniere


async def completer_texte(
    messages: list[dict], *, modele: str = MODELE_DIALOGUE, temperature: float = 0.3, rejeux: int = 1
) -> str:
    donnees = await _poster({"model": modele, "messages": messages, "stream": False, "temperature": temperature}, rejeux)
    try:
        return (donnees["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise ErreurLLM("Réponse du modèle mal formée") from exc


async def completer_structure(
    messages: list[dict],
    schema: dict,
    *,
    nom_schema: str = "reponse",
    modele: str = MODELE_DIALOGUE,
    temperature: float = 0.3,
    rejeux_json: int = 2,
) -> dict:
    """Sortie JSON conforme à `schema` ; rejoue l'appel complet si le JSON reçu est invalide."""
    payload: dict[str, Any] = {
        "model": modele,
        "messages": messages,
        "response_format": {"type": "json_schema", "json_schema": {"name": nom_schema, "strict": True, "schema": schema}},
        "stream": False,
        "temperature": temperature,
    }
    for tentative in range(rejeux_json + 1):
        donnees = await _poster(payload, rejeux=1)
        try:
            contenu = donnees["choices"][0]["message"]["content"]
            return json.loads(contenu)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            log.warning("JSON structuré invalide (schéma %s, tentative %d/%d)", nom_schema, tentative + 1, rejeux_json + 1)
    raise ErreurLLM(f"JSON structuré invalide après {rejeux_json + 1} tentatives ({nom_schema})")


async def flux_texte(
    messages: list[dict], *, modele: str = MODELE_TRADUCTION, temperature: float = 0.3
) -> AsyncIterator[str]:
    """Deltas de texte au fil de la génération (annulable : fermer l'itérateur coupe la requête)."""
    payload = {"model": modele, "messages": messages, "stream": True, "temperature": temperature}
    try:
        async with _obtenir_client().stream(
            "POST", f"{OPENROUTER_BASE_URL}/chat/completions", headers=_entetes(), json=payload
        ) as reponse:
            reponse.raise_for_status()
            async for ligne in reponse.aiter_lines():
                if not ligne.startswith("data: "):
                    continue
                donnee = ligne[6:]
                if donnee == "[DONE]":
                    break
                try:
                    delta = json.loads(donnee)["choices"][0]["delta"].get("content") or ""
                except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                    continue
                if delta:
                    yield delta
    except httpx.HTTPError as exc:
        raise ErreurLLM(f"Flux du modèle interrompu : {type(exc).__name__}") from exc
