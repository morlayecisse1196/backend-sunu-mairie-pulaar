"""
Journalisation applicative du backend v3.

Règle : AUCUNE donnée personnelle dans les logs — ni transcription, ni nom,
ni réponse de l'agent (le code historique affichait les messages transcrits
des citoyens en clair, cf. revue du 2026-09-14). On journalise des
identifiants techniques, des longueurs, des durées et des codes d'erreur.
"""
from __future__ import annotations

import logging
import os
import sys

_configure = False


def _configurer() -> None:
    global _configure
    if _configure:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    racine = logging.getLogger("sunu")
    racine.addHandler(handler)
    racine.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    racine.propagate = False
    _configure = True


def obtenir_logger(nom: str) -> logging.Logger:
    _configurer()
    return logging.getLogger(f"sunu.{nom}")


def masquer(texte: str | None) -> str:
    """Remplace un contenu potentiellement personnel par sa seule longueur."""
    if not texte:
        return "<vide>"
    return f"<{len(texte)} car.>"
