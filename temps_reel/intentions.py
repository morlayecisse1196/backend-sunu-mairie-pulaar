"""
Détection déterministe des réponses de confirmation (RG7, bascule).

Bug corrigé (revue du 2026-09-14) : l'ancienne `est_reponse_affirmative`
(main.py) cherchait un mot affirmatif n'importe où dans la phrase, sans tenir
compte de la négation — « Non, ce n'est pas correct », « Je ne suis pas
d'accord », « Oui mais le nom du père est faux » étaient tous lus comme une
CONFIRMATION, et le dossier partait à la mairie avec des données fausses
(violation directe de RG7 : ne jamais forcer l'envoi).

Règle désormais : une réponse n'est « oui » que si elle contient un marqueur
affirmatif ET aucun marqueur de négation ou de réserve. Dans le doute, ce
n'est jamais « oui » — c'est le seul sens d'erreur acceptable pour RG7.

Les marqueurs pulaar (« eey », « eyyi » pour oui, « alaa » pour non) sont
issus de transcriptions réelles mais NON validés par un locuteur natif : à
compléter dès qu'une relecture pulaar est possible.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Literal

Confirmation = Literal["oui", "non", "incertain"]

MOTS_REPONSE_AFFIRMATIVE = [
    "oui", "ouais", "d'accord", "daccord", "je veux bien", "je suis d'accord",
    "ok", "okay", "allons-y", "allons y", "commençons", "commencons",
    "je suis pret", "je suis prêt", "je suis prete", "je suis prête",
    "c'est bon", "c'est exact", "c'est correct", "c'est ça", "c'est ca", "c'est juste",
    "exact", "correct", "parfait", "tout est bon", "tout est juste", "valide", "je confirme",
    "eyyi", "eey", "eyy",  # pulaar — à valider par un locuteur natif
]

# Expressions affirmatives qui CONTIENNENT un mot de négation (« pas de
# problème ») : retirées du texte avant la recherche de négation, sinon un
# citoyen poli qui confirme serait lu comme refusant — et, en relecture RG7,
# chaque refus apparent compte comme une itération vers le blocage du dossier.
EXPRESSIONS_AFFIRMATIVES_AVEC_NEGATION = [
    "pas de probleme", "pas de soucis", "pas de souci", "sans probleme", "aucun probleme", "aucun souci",
]

MARQUEURS_NEGATION = [
    "non", "pas", "jamais", "aucun", "aucune", "rien", "ni",
    "faux", "fausse", "incorrect", "incorrecte", "inexact", "inexacte", "erreur", "erreurs",
    "mauvais", "mauvaise", "errone", "erronee",
    "alaa",  # pulaar — « non », à valider par un locuteur natif
]

# Marqueurs de réserve : « oui MAIS la date est fausse » n'est pas une confirmation.
MARQUEURS_RESERVE = [
    "mais", "sauf", "par contre", "cependant", "pourtant", "attendez", "attends", "attend",
    "corriger", "correction", "changer", "modifier", "rectifier",
]


def normaliser(texte: str | None) -> str:
    """Minuscules, sans accents, apostrophes typographiques unifiées, espaces compactés."""
    if not texte:
        return ""
    t = texte.replace("’", "'").replace("`", "'").lower()
    t = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip()


def _contient(texte: str, expressions: list[str]) -> bool:
    return any(re.search(rf"(?<![\w'])({re.escape(normaliser(e))})(?![\w])", texte) for e in expressions)


def classer_confirmation(message: str | None) -> Confirmation:
    """
    « oui » : marqueur affirmatif présent, aucune négation ni réserve.
    « non » : négation ou réserve présente (même avec un « oui » dans la phrase).
    « incertain » : ni l'un ni l'autre (bruit, hésitation, réponse hors sujet) —
    c'est à l'appelant de décider (en RG7 : ne pas envoyer, redemander).
    """
    texte = normaliser(message)
    if not texte:
        return "incertain"

    affirmatif = _contient(texte, MOTS_REPONSE_AFFIRMATIVE) or _contient(texte, EXPRESSIONS_AFFIRMATIVES_AVEC_NEGATION)

    sans_expressions = texte
    for expression in EXPRESSIONS_AFFIRMATIVES_AVEC_NEGATION:
        sans_expressions = re.sub(rf"(?<![\w']){re.escape(normaliser(expression))}(?![\w])", " ", sans_expressions)
    negatif = _contient(sans_expressions, MARQUEURS_NEGATION) or _contient(sans_expressions, MARQUEURS_RESERVE)

    if negatif:
        return "non"
    if affirmatif:
        return "oui"
    return "incertain"


def est_reponse_affirmative(message: str | None) -> bool:
    """Compatibilité avec l'ancienne API (main.py, scripts de test) : vrai uniquement pour un « oui » net."""
    return classer_confirmation(message) == "oui"
