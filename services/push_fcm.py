"""
Notifications push Firebase Cloud Messaging (API HTTP v1).

Configuration (l'une ou l'autre, jamais commitée) :
  FCM_SERVICE_ACCOUNT_FILE=/chemin/vers/compte-de-service.json
  FCM_SERVICE_ACCOUNT_JSON={"type": "service_account", ...}

Sans configuration, `envoyer` ne fait rien (les notifications restent
consultables dans l'app et sur le web) — jamais d'erreur bloquante.
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

import httpx
from jose import jwt

from services.journal import obtenir_logger

log = obtenir_logger("push_fcm")

PORTEE = "https://www.googleapis.com/auth/firebase.messaging"
URL_JETON_DEFAUT = "https://oauth2.googleapis.com/token"

_config: Optional[dict] = None
_jeton_acces: tuple[Optional[str], float] = (None, 0.0)


def _charger_config() -> dict:
    brut = os.getenv("FCM_SERVICE_ACCOUNT_JSON")
    chemin = os.getenv("FCM_SERVICE_ACCOUNT_FILE")
    try:
        if brut:
            return json.loads(brut)
        if chemin and os.path.exists(chemin):
            with open(chemin, encoding="utf-8") as fichier:
                return json.load(fichier)
    except (OSError, json.JSONDecodeError) as exc:
        log.error("Compte de service FCM illisible (%s) — push désactivé", type(exc).__name__)
    return {}


def est_configure() -> bool:
    global _config
    if _config is None:
        _config = _charger_config()
    return bool(_config.get("private_key") and _config.get("client_email") and _config.get("project_id"))


def reinitialiser() -> None:
    """Tests uniquement."""
    global _config, _jeton_acces
    _config = None
    _jeton_acces = (None, 0.0)


def construire_message(jeton: str, titre: str, corps: str, donnees: dict) -> dict:
    return {
        "message": {
            "token": jeton,
            "notification": {"title": titre, "body": corps},
            # FCM n'accepte que des chaînes dans `data`.
            "data": {cle: str(valeur) for cle, valeur in donnees.items() if valeur is not None},
            "android": {"priority": "high", "notification": {"channel_id": "dossiers"}},
            "apns": {"payload": {"aps": {"sound": "default"}}},
        }
    }


async def _obtenir_jeton_acces(client: httpx.AsyncClient) -> str:
    global _jeton_acces
    jeton, expiration = _jeton_acces
    if jeton and expiration - 60 > time.time():
        return jeton
    maintenant = int(time.time())
    url_jeton = _config.get("token_uri") or URL_JETON_DEFAUT
    assertion = jwt.encode(
        {"iss": _config["client_email"], "scope": PORTEE, "aud": url_jeton, "iat": maintenant, "exp": maintenant + 3600},
        _config["private_key"],
        algorithm="RS256",
    )
    reponse = await client.post(
        url_jeton, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}
    )
    reponse.raise_for_status()
    corps = reponse.json()
    _jeton_acces = (corps["access_token"], maintenant + int(corps.get("expires_in", 3600)))
    return _jeton_acces[0]


async def envoyer(jetons: list[str], titre: str, corps: str, donnees: dict) -> list[str]:
    """Envoie à chaque appareil ; retourne les jetons devenus invalides (à supprimer)."""
    if not jetons or not est_configure():
        return []
    invalides: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            acces = await _obtenir_jeton_acces(client)
            url = f"https://fcm.googleapis.com/v1/projects/{_config['project_id']}/messages:send"
            for jeton in jetons:
                reponse = await client.post(url, headers={"Authorization": f"Bearer {acces}"}, json=construire_message(jeton, titre, corps, donnees))
                if reponse.status_code in (400, 404) and ("UNREGISTERED" in reponse.text or "not a valid FCM registration token" in reponse.text):
                    invalides.append(jeton)
                elif reponse.status_code >= 300:
                    log.warning("Push FCM refusé (statut %s)", reponse.status_code)
    except httpx.HTTPError as exc:
        log.error("Push FCM indisponible (%s)", type(exc).__name__)
    return invalides
