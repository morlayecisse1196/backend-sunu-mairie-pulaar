"""
Écriture des dates en toutes lettres, pour les actes d'état civil (étape 5.5).

Un acte porte ses dates écrites en toutes lettres : « onze septembre deux
mille vingt ». Jusqu'ici, le consultant les recopiait à la main — une dizaine
de mentions entre les trois documents, à chaque dossier, avec le risque de
taper une date différente de celle du dialogue.

La conversion est faite ici, à partir de la date ISO que le dialogue a déjà
collectée. Elle est entièrement déterministe : aucun modèle de langue, aucune
approximation. C'est ce qui permet de la vérifier exhaustivement, et c'est la
condition pour qu'elle ait sa place sur un acte légal.

**Le consultant garde le dernier mot** : dans les templates, sa saisie manuelle
est essayée AVANT la conversion automatique. S'il a le registre papier sous les
yeux et que celui-ci écrit « deux mil quatre », c'est sa version qui sort.

Orthographe : graphie traditionnelle, celle des actes (« mille neuf cent
quatre-vingt-quatre », pas « mille-neuf-cent-quatre-vingt-quatre »). Le premier
jour du mois s'écrit « premier », jamais « un ».
"""
from __future__ import annotations

from datetime import date

_UNITES = [
    "zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit",
    "neuf", "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize",
]

_DIZAINES = {20: "vingt", 30: "trente", 40: "quarante", 50: "cinquante", 60: "soixante"}

MOIS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]

#: Au-delà, ce n'est plus une date d'état civil mais une erreur de saisie —
#: mieux vaut ne rien écrire que d'écrire n'importe quoi sur un acte.
MAXIMUM = 9999


def _moins_de_cent(n: int) -> str:
    if n < 17:
        return _UNITES[n]
    if n < 20:
        return f"dix-{_UNITES[n - 10]}"
    if n < 70:
        base = _DIZAINES[(n // 10) * 10]
        unite = n % 10
        if unite == 0:
            return base
        # « vingt et un », mais « vingt-deux » : le « et » ne vaut que pour 1.
        return f"{base} et un" if unite == 1 else f"{base}-{_UNITES[unite]}"
    if n < 80:
        # 70 à 79 se comptent à partir de soixante : soixante-dix, soixante et
        # onze, soixante-douze...
        reste = n - 60
        return "soixante et onze" if reste == 11 else f"soixante-{_moins_de_cent(reste)}"
    reste = n - 80
    if reste == 0:
        # « quatre-vingts » prend un s quand rien ne le suit (1980), pas
        # quand un nombre le suit (1984).
        return "quatre-vingts"
    return f"quatre-vingt-{_moins_de_cent(reste)}"


def _centaines(n: int) -> str:
    centaines, reste = divmod(n, 100)
    tete = "cent" if centaines == 1 else f"{_UNITES[centaines]} cent"
    if reste == 0:
        return f"{tete}s" if centaines > 1 else tete
    return f"{tete} {_moins_de_cent(reste)}"


def nombre_en_lettres(n: int) -> str:
    """Un entier de 0 à 9999, écrit comme sur un acte."""
    if not isinstance(n, int) or isinstance(n, bool) or n < 0 or n > MAXIMUM:
        raise ValueError(f"nombre hors de portée pour un acte : {n!r}")
    if n < 100:
        return _moins_de_cent(n)
    if n < 1000:
        return _centaines(n)
    milliers, reste = divmod(n, 1000)
    # « mille » est invariable et ne se dit jamais « un mille ».
    tete = "mille" if milliers == 1 else f"{_moins_de_cent(milliers)} mille"
    if reste == 0:
        return tete
    return f"{tete} {_moins_de_cent(reste) if reste < 100 else _centaines(reste)}"


def date_en_lettres(valeur) -> str | None:
    """
    « 2020-09-11 » -> « onze septembre deux mille vingt ».

    Renvoie None si la valeur n'est pas une date ISO lisible : sur un acte,
    une mention absente se voit et se corrige, une mention fausse se signe.
    """
    if isinstance(valeur, date):
        jour, mois, annee = valeur.day, valeur.month, valeur.year
    else:
        if not isinstance(valeur, str):
            return None
        try:
            # Tolère un horodatage complet (« 2020-09-11T00:00:00+00:00 ») :
            # certaines valeurs remontent de la base dans cette forme.
            analysee = date.fromisoformat(valeur.strip()[:10])
        except ValueError:
            return None
        jour, mois, annee = analysee.day, analysee.month, analysee.year

    # Pas de garde sur l'année : une `date` Python ne peut pas dépasser 9999,
    # et `fromisoformat` refuse déjà tout le reste. Une campagne de mutation a
    # montré que le contrôle que j'avais mis là était invérifiable.
    jour_lettres = "premier" if jour == 1 else nombre_en_lettres(jour)
    return f"{jour_lettres} {MOIS[mois - 1]} {nombre_en_lettres(annee)}"
