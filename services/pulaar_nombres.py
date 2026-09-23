"""
Nombres, dates, âges et montants énoncés en pulaar, sans modèle (étape 3.2).

POURQUOI

Le récapitulatif est le moment le plus important du dialogue : le citoyen y
confirme des informations qui finiront sur un acte d'état civil. Il contient
forcément des valeurs — une date, un nom, un âge — qu'aucune phrase figée ne
peut contenir d'avance.

Jusqu'ici, tout partait au traducteur, y compris les chiffres. Le modèle
lisait « 2026-09-07 » comme il pouvait, différemment à chaque fois, et la
synthèse vocale prononçait ce qu'elle voulait de « 07 ». Un citoyen qui ne lit
pas doit ENTENDRE « ñalnde jeeɗiɗi, lewru Sattumbar, hitaande ujunaaje ɗiɗi e
noogas e jeegom » — pas une suite de chiffres.

Ces fonctions sont déterministes : même entrée, même sortie, toujours. Aucun
appel réseau, aucun modèle.

⚠️ STATUT
Les noms de nombres suivent le pulaar du Fuuta Tooro et sont corroborés par le
corpus de traduction (`teemedde ɗiɗi` pour 200, `lebbi tati` pour trois mois).
Les NOMS DE MOIS, eux, sont les emprunts français usuels au Sénégal : ils
doivent être relus comme le reste (`scripts/atelier_pulaar.py`).
"""
from __future__ import annotations

from datetime import date, datetime

# ---------------------------------------------------------------------------
# Nombres
# ---------------------------------------------------------------------------

UNITES = {
    0: "meere",
    1: "go'o",
    2: "ɗiɗi",
    3: "tati",
    4: "nayi",
    5: "joyi",
    6: "jeegom",
    7: "jeeɗiɗi",
    8: "jeetati",
    9: "jeenayi",
}

DIX = "sappo"
VINGT = "noogas"
#: 30 à 90 : « cappanɗe » (dizaines) suivi du chiffre.
DIZAINES = "cappanɗe"
CENT = "teemedere"
CENTS = "teemedde"
MILLE = "ujunere"
MILLES = "ujunaaje"

ET = "e"


def _sous_cent(nombre: int) -> str:
    if nombre < 10:
        return UNITES[nombre]
    if nombre < 20:
        reste = nombre - 10
        return DIX if reste == 0 else f"{DIX} {ET} {UNITES[reste]}"
    dizaine, reste = divmod(nombre, 10)
    tete = VINGT if dizaine == 2 else f"{DIZAINES} {UNITES[dizaine]}"
    return tete if reste == 0 else f"{tete} {ET} {UNITES[reste]}"


def _sous_mille(nombre: int) -> str:
    centaines, reste = divmod(nombre, 100)
    if centaines == 0:
        return _sous_cent(reste)
    tete = CENT if centaines == 1 else f"{CENTS} {UNITES[centaines]}"
    return tete if reste == 0 else f"{tete} {ET} {_sous_cent(reste)}"


def nombre(valeur: int) -> str:
    """
    Un entier énoncé en pulaar, de 0 à 999 999.

    Au-delà, les chiffres sont rendus tels quels plutôt qu'approximés : un
    numéro d'acte à dix-neuf chiffres ne se dit pas, il s'épelle (voir
    `chiffre_par_chiffre`).
    """
    entier = int(valeur)
    if entier < 0:
        return f"{'les'} {nombre(-entier)}"  # cas théorique : aucun champ n'accepte de négatif
    if entier < 1000:
        return _sous_mille(entier)
    if entier >= 1_000_000:
        return str(entier)
    milliers, reste = divmod(entier, 1000)
    tete = MILLE if milliers == 1 else f"{MILLES} {_sous_mille(milliers)}"
    return tete if reste == 0 else f"{tete} {ET} {_sous_mille(reste)}"


def chiffre_par_chiffre(valeur: str | int) -> str:
    """
    Chaque chiffre dit séparément — pour un numéro de suivi ou un numéro
    d'acte, que personne n'énonce comme une quantité.
    """
    return " ".join(UNITES[int(c)] for c in str(valeur) if c.isdigit())


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

#: Emprunts français usuels au Sénégal, écrits comme le pulaar les prononce.
#: À relire comme le reste des phrases.
MOIS = {
    1: "Sanwiye", 2: "Feebariye", 3: "Marse", 4: "Awril",
    5: "Me", 6: "Suwe", 7: "Sulet", 8: "Ut",
    9: "Sattumbar", 10: "Oktoobar", 11: "Nowammbar", 12: "Desammbar",
}

JOUR = "ñalnde"
LEWRU = "lewru"
HITAANDE = "hitaande"


def comme_date(valeur) -> date | None:
    """Les dates sont stockées en ISO par `slot_controller.valider_valeur`."""
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    if isinstance(valeur, str):
        try:
            return date.fromisoformat(valeur.strip()[:10])
        except ValueError:
            return None
    return None


def date_pulaar(valeur) -> str | None:
    """
    Une date énoncée en entier : jour, mois, année.

    `None` si la valeur n'est pas une date lisible — à l'appelant de décider,
    plutôt que de faire dire n'importe quoi au citoyen.
    """
    jour = comme_date(valeur)
    if jour is None:
        return None
    return (
        f"{JOUR} {nombre(jour.day)}, {LEWRU} {MOIS[jour.month]}, "
        f"{HITAANDE} {nombre(jour.year)}"
    )


# ---------------------------------------------------------------------------
# Âges et montants
# ---------------------------------------------------------------------------

#: Pluriels du corpus : « lebbi tati » (trois mois), « balɗe » (jours).
UNITES_AGE = {
    "jour": "ñalawma", "jours": "balɗe",
    "semaine": "yontere", "semaines": "jonte",
    "mois": "lebbi",
    "an": "hitaande", "ans": "duuɓi", "annee": "hitaande", "annees": "duuɓi",
    "année": "hitaande", "années": "duuɓi",
}


def age_pulaar(valeur) -> str | None:
    """Un âge `{"valeur": 3, "unite": "mois"}` énoncé en pulaar."""
    if not isinstance(valeur, dict):
        return None
    quantite, unite = valeur.get("valeur"), (valeur.get("unite") or "").strip().lower()
    if quantite is None or unite not in UNITES_AGE:
        return None
    try:
        entier = int(float(quantite))
    except (TypeError, ValueError):
        return None
    # Le singulier est employé quand la quantité vaut un : « ñalawma go'o »
    # plutôt que « balɗe go'o ».
    if entier == 1:
        singulier = {"balɗe": "ñalawma", "jonte": "yontere", "lebbi": "lewru", "duuɓi": "hitaande"}
        mot = singulier.get(UNITES_AGE[unite], UNITES_AGE[unite])
        return f"{mot} {nombre(1)}"
    return f"{UNITES_AGE[unite]} {nombre(entier)}"


MONNAIE = "faraŋ seefaa"


def montant_pulaar(valeur) -> str | None:
    """Un montant en francs CFA."""
    try:
        entier = int(float(str(valeur).replace(",", ".")))
    except (TypeError, ValueError):
        return None
    return f"{nombre(entier)} {MONNAIE}"


OUI = "eey"
NON = "alaa"


def booleen_pulaar(valeur) -> str:
    return OUI if valeur else NON
