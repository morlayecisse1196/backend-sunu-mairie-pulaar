"""
Gabarits à trous : une phrase validée, des valeurs insérées (étape 3.2).

LE PROBLÈME

Le récapitulatif est le moment décisif du dialogue : le citoyen y confirme des
informations qui finiront sur un acte d'état civil. Il ne peut pas être une
phrase figée, puisqu'il contient les réponses du citoyen. Il partait donc en
entier au traducteur — valeurs comprises — et revenait différent à chaque
conversation, avec les dates lues comme des suites de chiffres.

LA RÉPONSE

Séparer la PHRASE des VALEURS. La phrase est un gabarit, relu une fois pour
toutes :

    Ko nii mi winndi : {nom_enfant}, jibinaaɗo {date_naissance_enfant} e
    {commune_naissance}. Ko ɗum woni goonga?

Les valeurs sont insérées par le code : un texte tel quel, une date énoncée en
entier, un âge avec son unité, un oui ou un non (`services/pulaar_nombres.py`).
Aucun modèle n'intervient.

CE QUI SE PASSE SI UNE VALEUR MANQUE

Le gabarit n'est pas rendu et l'appelant reçoit `None`. Un récapitulatif où
figurerait « non renseigné » ferait confirmer au citoyen une information qu'il
n'a jamais donnée — c'est exactement ce qu'un récapitulatif doit empêcher.
"""
from __future__ import annotations

import re

from services import pulaar_nombres
from services.journal import obtenir_logger

log = obtenir_logger("gabarits")

#: `{nom_champ}` — volontairement la même écriture qu'en Python, familière, et
#: sans risque de collision : aucune phrase du dialogue ne contient d'accolade.
_TROU = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

FRANCAIS = "francais"
PULAAR = "pulaar"


def trous(gabarit: str) -> list[str]:
    """Les champs cités par un gabarit, dans l'ordre d'apparition."""
    vus: list[str] = []
    for nom in _TROU.findall(gabarit or ""):
        if nom not in vus:
            vus.append(nom)
    return vus


def _valeur_francais(champ: dict, valeur) -> str | None:
    type_valeur = champ.get("type_valeur", "texte")
    if valeur is None:
        return None
    if type_valeur == "booleen":
        return "oui" if valeur else "non"
    if type_valeur == "age":
        if not isinstance(valeur, dict) or valeur.get("valeur") is None or not valeur.get("unite"):
            return None
        return f"{valeur['valeur']} {valeur['unite']}"
    if type_valeur == "nombre":
        return f"{valeur:g}" if isinstance(valeur, float) else str(valeur)
    return str(valeur)


def _valeur_pulaar(champ: dict, valeur) -> str | None:
    type_valeur = champ.get("type_valeur", "texte")
    if valeur is None:
        return None
    if type_valeur == "date":
        return pulaar_nombres.date_pulaar(valeur)
    if type_valeur == "age":
        return pulaar_nombres.age_pulaar(valeur)
    if type_valeur == "booleen":
        return pulaar_nombres.booleen_pulaar(valeur)
    if type_valeur == "nombre":
        try:
            return pulaar_nombres.nombre(int(float(valeur)))
        except (TypeError, ValueError):
            return None
    if type_valeur == "enum":
        # « masculin », « polygamie »… sont des mots français : les dire tels
        # quels en pulaar serait faux. Sans traduction relue, pas de pulaar.
        return None
    # Un nom propre ou un nom de commune se dit tel quel : le traduire serait
    # une faute, pas une amélioration.
    return str(valeur)


def rendre(gabarit: str | None, slots: dict, champs: list[dict], langue: str = FRANCAIS) -> str | None:
    """
    Remplit un gabarit, ou retourne `None` si une valeur manque ou n'est pas
    énonçable.

    `champs` sont les lignes `demarche_champs` : c'est leur `type_valeur` qui
    décide comment une valeur se dit, jamais le nom du champ. Une démarche
    ajoutée demain fonctionne sans toucher à ce module.
    """
    if not gabarit or not gabarit.strip():
        return None

    par_nom = {c["nom_champ"]: c for c in champs}
    rendu = gabarit
    for nom in trous(gabarit):
        champ = par_nom.get(nom)
        if champ is None:
            log.error("Gabarit : le champ %r n'existe pas dans cette démarche.", nom)
            return None
        valeur = (
            _valeur_pulaar(champ, slots.get(nom))
            if langue == PULAAR
            else _valeur_francais(champ, slots.get(nom))
        )
        if valeur is None:
            log.info("Gabarit non rendu : %r n'a pas de valeur énonçable.", nom)
            return None
        rendu = rendu.replace("{" + nom + "}", valeur)
    return rendu
