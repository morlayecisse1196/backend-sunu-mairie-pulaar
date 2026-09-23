"""
Recherche des démarches (RAG) pour le mode information.

Sémantique (pgvector, search2.py) puis repli mot-clé (Supabase REST,
search.py), exécutée dans un thread : l'encodage sentence-transformers et la
connexion Postgres sont synchrones et bloquaient auparavant l'event loop du
WebSocket pendant chaque tour. Ne lève jamais d'exception : un incident RAG ne
doit pas faire tomber le tour de conversation.

Les modules search2/search sont importés à la première utilisation : search2
charge le modèle d'embeddings à l'import (plusieurs secondes), inutile pour les
routes qui n'en ont pas besoin ni pour les tests.
"""
from __future__ import annotations

import asyncio

from services.journal import obtenir_logger

log = obtenir_logger("rag")


def _rechercher_sync(question: str, commune: str | None, limite: int) -> list:
    try:
        from search2 import search_demarches as recherche_semantique

        return recherche_semantique(question, commune=commune, limit=limite)
    except Exception as exc:  # noqa: BLE001
        log.warning("RAG sémantique indisponible (%s) — repli mot-clé", type(exc).__name__)
    try:
        from search import search_demarches as recherche_mot_cle

        return recherche_mot_cle(question, commune=commune, limit=limite)
    except Exception as exc:  # noqa: BLE001
        log.warning("RAG mot-clé indisponible (%s) — aucune démarche", type(exc).__name__)
        return []


async def rechercher_demarches(question: str, commune: str | None, limite: int = 3) -> list:
    return await asyncio.to_thread(_rechercher_sync, question, commune, limite)


def resume_rag(resultats: list) -> str:
    """Résumé ultra-court (1-2 phrases) injecté dans le prompt du mode information."""
    if not resultats:
        return "Aucune information spécifique disponible."
    demarche = resultats[0]
    documents = ", ".join((demarche.get("documents_requis") or [])[:3])
    return f"Démarche : {demarche.get('nom_demarche', '')}. Documents : {documents}."
