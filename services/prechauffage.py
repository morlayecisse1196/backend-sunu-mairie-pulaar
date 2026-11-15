"""
Réveil des services vocaux distants au démarrage du serveur.

Pourquoi : l'ASR et le TTS tournent sur des Spaces Hugging Face qui
s'endorment après inactivité. Mesuré le 2026-11-04 sur ce projet : un premier
appel au TTS endormi a mis **55 secondes**. Ce délai tombait entièrement sur le
premier citoyen de la journée — celui qui, précisément, ne sait pas lire le
message « ça prend un peu de temps » et conclut que le téléphone est cassé.

Le contrat temps réel prévoit déjà le message `lent` pour prévenir (cf.
README-TEMPS-REEL-MOBILE.md §7), mais prévenir n'est pas corriger : il valait
mieux payer le réveil au démarrage du serveur, quand personne n'attend.

Trois principes :

1. **Jamais bloquant.** Lancé comme tâche de fond dans le `lifespan` : le
   serveur accepte des requêtes immédiatement. Un Space injoignable ne doit
   jamais empêcher l'API de démarrer — le dialogue retomberait simplement sur
   l'ancien comportement (premier tour lent), pas sur une panne.
2. **Réveil du conteneur d'abord, du modèle ensuite.** Un simple GET sur la
   racine du Space suffit à sortir le conteneur de veille, sans consommer
   d'inférence. La synthèse d'un mot très court qui suit vérifie en plus que le
   modèle lui-même répond — c'est ce qui distingue « le Space répond » de
   « la voix fonctionne ».
3. **Aucune donnée inventée.** Le mot synthétisé est jeté : ce module ne met
   rien en cache et ne touche à aucune session.

Pour le catalogue audio de l'interface, qui est un tout autre problème (16
phrases à traduire ET synthétiser une fois pour toutes), voir
`scripts/generer_catalogue_audio.py` : il n'a rien à faire au démarrage.
"""
from __future__ import annotations

import asyncio
import time

import httpx

from asr_client import ASR_API_URL
from services.journal import obtenir_logger
from tts_client import TTS_API_URL, synthesize_remote

log = obtenir_logger("prechauffage")

# Un Space au réveil met typiquement 30 à 60 s à répondre : en dessous, on
# abandonnerait juste avant qu'il soit prêt, et le premier citoyen paierait
# quand même l'attente.
DELAI_REVEIL_SECONDES = 90.0

# Un seul mot pulaar, très court : assez pour charger le modèle en mémoire,
# assez peu pour ne pas consommer de quota pour rien. « jam » = la paix, le
# premier mot d'une salutation.
MOT_DE_REVEIL = "jam"


async def _reveiller_conteneur(nom: str, url: str | None) -> bool:
    """GET sur la racine du Space : sort le conteneur de veille sans inférence."""
    if not url:
        log.warning("prechauffage.%s.ignore url_absente", nom)
        return False
    debut = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=DELAI_REVEIL_SECONDES) as client:
            reponse = await client.get(url)
        log.info(
            "prechauffage.%s.conteneur statut=%s duree=%.1fs",
            nom, reponse.status_code, time.monotonic() - debut,
        )
        return reponse.status_code < 500
    except Exception as exc:  # noqa: BLE001 — un réveil raté n'est pas une panne
        log.warning(
            "prechauffage.%s.conteneur.echec %s duree=%.1fs",
            nom, type(exc).__name__, time.monotonic() - debut,
        )
        return False


async def _reveiller_modele_tts() -> bool:
    """Synthétise un mot très court : vérifie que le modèle vocal répond."""
    debut = time.monotonic()
    try:
        audio = await synthesize_remote(MOT_DE_REVEIL, timeout=DELAI_REVEIL_SECONDES)
    except Exception as exc:  # noqa: BLE001 — TTSError incluse
        log.warning(
            "prechauffage.tts.modele.echec %s duree=%.1fs",
            type(exc).__name__, time.monotonic() - debut,
        )
        return False
    log.info(
        "prechauffage.tts.modele octets=%d duree=%.1fs",
        len(audio or b""), time.monotonic() - debut,
    )
    return bool(audio)


async def prechauffer_services_vocaux() -> None:
    """
    Réveille ASR et TTS en parallèle. Ne lève jamais : toute erreur est
    journalisée et le serveur continue — c'est le même parti que
    `auth.prechauffer_jwks`.
    """
    debut = time.monotonic()
    try:
        asr, tts = await asyncio.gather(
            _reveiller_conteneur("asr", ASR_API_URL),
            _reveiller_conteneur("tts", TTS_API_URL),
        )
        modele = await _reveiller_modele_tts() if tts else False
        log.info(
            "prechauffage.termine asr=%s tts=%s modele_tts=%s duree=%.1fs",
            asr, tts, modele, time.monotonic() - debut,
        )
    except asyncio.CancelledError:
        # Arrêt du serveur pendant le réveil : rien à signaler.
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("prechauffage.echec %s: %s", type(exc).__name__, exc)
