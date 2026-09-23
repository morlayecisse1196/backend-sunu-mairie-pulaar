"""
Règles d'écriture selon le statut d'un dossier — une seule source de vérité
pour les endpoints consultant (et le front web, qui applique les mêmes règles
en lecture seule).

Pourquoi (revue du 2026-09-14) : aucun endpoint consultant ne vérifiait le
statut avant d'écrire. Un consultant pouvait régénérer un dossier FINALISÉ
(repassé silencieusement à « genere »), modifier les champs d'un document déjà
envoyé au citoyen, ou d'un dossier bloqué en attente de reprise admin.
"""
from __future__ import annotations

from typing import Literal

ActionConsultant = Literal[
    "modifier_formulaire", "ocr", "analyser", "creer_cas", "resoudre_cas", "generer", "valider",
]

STATUTS_LECTURE_SEULE = frozenset({"finalise", "bloque"})
STATUT_CHEZ_CITOYEN = "en_attente_validation_citoyen"
STATUTS_GENERATION_AUTORISEE = frozenset({"recu", "en_traitement", "genere", "corrections_demandees"})


class RefusStatut(Exception):
    """Action refusée pour le statut courant — à traduire en HTTP 409."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.message = message
        self.code = code

    def detail(self) -> dict:
        return {"message": self.message, "code": self.code}


def verifier_action_consultant(statut: str, action: ActionConsultant) -> None:
    """Lève `RefusStatut` si `action` est interdite pour un dossier au `statut` donné."""
    if statut == "en_cours":
        raise RefusStatut(
            "Ce dossier n'a pas encore été confirmé par le citoyen : il n'est pas traitable.", "dossier_non_confirme"
        )

    if action == "analyser":
        return  # lecture seule, sans effet sur le dossier

    if statut == "finalise":
        raise RefusStatut("Dossier finalisé : le citoyen a validé son document, plus aucune modification possible.", "dossier_finalise")
    if statut == "bloque":
        raise RefusStatut("Dossier bloqué : il doit d'abord être repris par un administrateur.", "dossier_bloque")

    if action == "valider":
        if statut != "genere":
            raise RefusStatut(
                f"Le dossier doit être au statut « genere » pour être envoyé au citoyen (statut actuel : « {statut} »).",
                "validation_impossible",
            )
        return

    if statut == STATUT_CHEZ_CITOYEN:
        raise RefusStatut(
            "Le document est chez le citoyen : attendez sa validation ou sa demande de correction.", "document_chez_citoyen"
        )

    if action == "generer" and statut not in STATUTS_GENERATION_AUTORISEE:
        raise RefusStatut(f"Génération impossible au statut « {statut} ».", "generation_impossible")
