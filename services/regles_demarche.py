"""
Règles transverses d'une démarche (étape 2.1 du plan maître, formes 2 et 3).

Une condition portée par un champ ou un document répond à la question « faut-il
poser cette question / demander cette pièce ? ». Deux formes de règles réelles
ne rentrent pas dans ce moule, parce qu'elles ne concernent aucune étape en
particulier mais la démarche entière :

- **Délai qui interrompt la démarche** (`bloquer`). La constatation de mariage
  n'est plus recevable passé six mois ; le citoyen doit être orienté vers une
  autre procédure, pas laissé remplir un dossier qui sera rejeté.
- **Combinaison interdite entre deux champs** (`interdire`). L'option
  polygamique est incompatible avec le régime de la communauté de biens : la
  dernière réponse doit être refusée et redemandée, pas enregistrée.

Une règle est donc : une condition, un effet, un message, et une source
juridique. La source n'est pas décorative — règle 3 du plan maître : aucune
règle de droit n'est codée sans source, et une règle non confirmée par un
officier d'état civil est signalée comme hypothèse.

`demarche_regles` n'existe qu'à partir de la migration 017. Tant qu'elle n'est
pas appliquée, `charger_regles` retourne une liste vide et le moteur se
comporte exactement comme avant.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from services import conditions, demarche
from services.journal import obtenir_logger

log = obtenir_logger("regles_demarche")

#: La démarche ne peut pas se poursuivre : on explique et on oriente.
BLOQUER = "bloquer"
#: La dernière valeur saisie est refusée : on explique et on redemande.
INTERDIRE = "interdire"

EFFETS = (BLOQUER, INTERDIRE)


@dataclass(frozen=True)
class Violation:
    """Une règle dont la condition est vraie pour l'état courant du dossier."""

    code: str
    effet: str
    message: str
    #: Le champ à vider et redemander (effet `interdire`), s'il est précisé.
    champ: str | None = None
    source: str | None = None


def charger_regles(type_demarche: str, version: int | None = None) -> list[dict]:
    """
    Règles d'une démarche, triées par `ordre`.

    `version` fige les règles sur celles en vigueur au début du dialogue
    (étape 2.4) : une interdiction ajoutée en pleine journée ne doit pas
    invalider une réponse déjà donnée par un citoyen en ligne.
    """
    return demarche.regles(type_demarche, version)


def evaluer_regles(
    regles: list[dict],
    slots: dict,
    *,
    effets: tuple[str, ...] = EFFETS,
    aujourdhui: date | None = None,
) -> list[Violation]:
    """
    Les règles dont la condition est **certainement** vraie, dans l'ordre.

    Une condition indéterminée (champ pas encore rempli) ne déclenche rien :
    on ne bloque jamais une démarche sur une information qu'on n'a pas encore
    demandée.
    """
    violations: list[Violation] = []
    for regle in regles:
        effet = regle.get("effet")
        if effet not in effets:
            continue
        if conditions.evaluer(regle.get("condition"), slots, aujourdhui) != conditions.VRAI:
            continue
        violations.append(
            Violation(
                code=regle.get("code") or "?",
                effet=effet,
                message=regle.get("message") or "Cette demande ne peut pas être poursuivie ainsi.",
                champ=regle.get("champ_concerne"),
                source=regle.get("source"),
            )
        )
    return violations
