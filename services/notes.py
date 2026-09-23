"""
Remarques du citoyen, notes internes entre agents et historique d'un dossier.

Ces trois listes répondent au même besoin côté web : savoir CE QUI s'est passé
sur un dossier et POURQUOI. Les notes internes ne sont jamais exposées au
citoyen (aucune route `/mes-*` ne les lit).
"""
from __future__ import annotations

from typing import Optional

from services import db
from services.journal import obtenir_logger

log = obtenir_logger("notes")

MIGRATION_NOTES = "012"
LONGUEUR_MAX_NOTE = 2000


def _noms_auteurs_sync(identifiants: list[str]) -> dict:
    if not identifiants:
        return {}
    try:
        profils = db.client().table("profiles").select("id, nom_complet").in_("id", identifiants).execute().data or []
        return {p["id"]: p.get("nom_complet") for p in profils}
    except Exception:  # noqa: BLE001 — colonne nom_complet absente avant la migration 012
        return {}


async def lister_remarques(dossier_id: str) -> list:
    """Signalements du citoyen sur le document généré (table `remarques`, existante)."""
    def _lire():
        return (
            db.client().table("remarques").select("*").eq("dossier_id", dossier_id)
            .order("horodatage", desc=True).execute().data or []
        )

    return await db.executer(_lire)


async def lister_notes(dossier_id: str) -> list:
    def _lire():
        notes = (
            db.client().table("notes_internes").select("*").eq("dossier_id", dossier_id)
            .order("cree_le", desc=True).execute().data or []
        )
        noms = _noms_auteurs_sync(sorted({n["auteur_id"] for n in notes}))
        for note in notes:
            note["auteur_nom"] = noms.get(note["auteur_id"])
        return notes

    try:
        return await db.executer(_lire)
    except Exception as exc:  # noqa: BLE001
        if db.est_erreur_schema(exc):
            raise db.migration_manquante(MIGRATION_NOTES, "Les notes internes")
        log.error("Lecture des notes échouée (%s)", type(exc).__name__)
        raise


async def ajouter_note(dossier_id: str, auteur_id: str, texte: str) -> dict:
    texte = (texte or "").strip()[:LONGUEUR_MAX_NOTE]
    if not texte:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="La note ne peut pas être vide.")

    def _ecrire():
        reponse = db.client().table("notes_internes").insert(
            {"dossier_id": dossier_id, "auteur_id": auteur_id, "texte": texte}
        ).execute()
        note = reponse.data[0] if reponse.data else {"dossier_id": dossier_id, "auteur_id": auteur_id, "texte": texte}
        note["auteur_nom"] = _noms_auteurs_sync([auteur_id]).get(auteur_id)
        return note

    try:
        return await db.executer(_ecrire)
    except Exception as exc:  # noqa: BLE001
        if db.est_erreur_schema(exc):
            raise db.migration_manquante(MIGRATION_NOTES, "Les notes internes")
        log.error("Écriture d'une note échouée (%s)", type(exc).__name__)
        raise


async def lister_evenements(dossier_id: str) -> list:
    """Historique du cycle de vie, du plus ancien au plus récent (ordre de lecture d'une frise)."""
    def _lire():
        evenements = (
            db.client().table("dossier_evenements").select("*").eq("dossier_id", dossier_id)
            .order("cree_le").execute().data or []
        )
        noms = _noms_auteurs_sync(sorted({e["acteur_id"] for e in evenements if e.get("acteur_id")}))
        for evenement in evenements:
            evenement["acteur_nom"] = noms.get(evenement.get("acteur_id"))
        return evenements

    try:
        return await db.executer(_lire)
    except Exception as exc:  # noqa: BLE001
        if db.est_erreur_schema(exc):
            raise db.migration_manquante(MIGRATION_NOTES, "L'historique du dossier")
        log.error("Lecture de l'historique échouée (%s)", type(exc).__name__)
        raise
