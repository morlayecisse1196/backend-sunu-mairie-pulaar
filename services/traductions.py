"""
Mémoire des traductions françaises -> pulaar.

LE PROBLÈME MESURÉ

Le traducteur de production est `google/gemini-2.5-flash` (MODEL_FORMATTER),
et il ne rend pas deux fois la même chose. Mesuré sur la base réelle, une même
phrase française traduite trois fois de suite :

    « Dans quelle commune votre enfant est-il né ? »
      -> to komin hono?    to komin yiɗi?    to komin goɗɗum?

Trois versions sur trois. Et sur « numéro de suivi » : `limoore jokkondiral`,
`limoore maa`, `limoore reentagol` — trois mots différents pour la chose que le
citoyen doit retenir et présenter au guichet.

CE QUE L'INSTABILITÉ COÛTE EN PLUS

Le cache audio est indexé sur le texte pulaar RÉELLEMENT prononcé. Un pulaar
qui change à chaque fois ne retombe donc jamais sur un fichier déjà
synthétisé : chaque tour repaie une synthèse complète, mesurée à 7,6 s. Rendre
la traduction stable rend aussi le cache audio utile.

LA CLÉ

L'empreinte de TOUT ce qui est envoyé au modèle — consigne système comprise.
Deux conséquences voulues :

  * le contexte compte : « premier tour » ajoute « Salam. », et deux contextes
    différents ne doivent pas se partager une entrée ;
  * modifier le prompt du traducteur invalide le cache de lui-même, sans
    qu'on ait à y penser. C'est le même principe que l'audio pré-généré, dont
    l'empreinte porte sur le texte réellement dit.

Ce cache ne remplace PAS la relecture : une phrase relue en base ne passe
jamais ici. Il ne fait que rendre reproductible ce qui, faute de relecture,
doit encore être traduit à la volée.
"""
from __future__ import annotations

import hashlib
import os

from services.journal import obtenir_logger

log = obtenir_logger("traductions")

DOSSIER = os.path.join("cache_traductions")


def cle(invite_systeme: str, invite_utilisateur: str) -> str:
    empreinte = hashlib.sha256(
        (invite_systeme + "\x00" + invite_utilisateur).encode("utf-8")
    ).hexdigest()[:24]
    return f"tr_{empreinte}"


def _chemin(identifiant: str) -> str:
    return os.path.join(DOSSIER, f"{identifiant}.txt")


def lire(identifiant: str) -> str | None:
    """La traduction déjà obtenue pour cette demande exacte, ou `None`."""
    chemin = _chemin(identifiant)
    try:
        if not os.path.exists(chemin):
            return None
        with open(chemin, encoding="utf-8") as fichier:
            texte = fichier.read().strip()
        return texte or None
    except OSError as exc:
        log.warning("Lecture du cache de traduction échouée (%s)", type(exc).__name__)
        return None


def ranger(identifiant: str, texte: str) -> None:
    """
    Garde la traduction. Best-effort : un échec d'écriture ne doit jamais
    empêcher le citoyen d'entendre la réponse qu'on vient de lui produire.
    """
    texte = (texte or "").strip()
    if not texte:
        return
    try:
        os.makedirs(DOSSIER, exist_ok=True)
        # Écriture puis renommage : un disque plein ou un arrêt au mauvais
        # moment laisserait sinon un fichier à moitié écrit, qui serait relu
        # comme une traduction valable et dit au citoyen.
        provisoire = _chemin(identifiant) + ".tmp"
        with open(provisoire, "w", encoding="utf-8") as fichier:
            fichier.write(texte)
        os.replace(provisoire, _chemin(identifiant))
    except OSError as exc:
        log.warning("Écriture du cache de traduction échouée (%s)", type(exc).__name__)
