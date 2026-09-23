"""
Administration (web v3) : vue transversale des dossiers, reprise d'un dossier
bloqué, historique et notes, réinitialisation d'un mot de passe consultant,
journal d'activité.

L'administration CONSULTE les dossiers sans effet de bord : contrairement à
l'ouverture par un consultant, elle ne fait jamais passer un dossier de
« reçu » à « en traitement ».
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from admin_repo import list_dossiers_admin, reinitialiser_mot_de_passe_consultant
from auth import get_current_admin
from dossiers_repo import (
    get_document_genere_signed_url,
    get_document_signed_url,
    list_cas_particuliers,
    list_document_formulaires,
    list_documents,
    list_documents_generes,
)
from services import acces, audit, db, evenements, notes
from services.journal import obtenir_logger

router = APIRouter(prefix="/admin", tags=["admin"])
log = obtenir_logger("routers.admin")

STATUTS_REPRISE = ("en_traitement", "recu")
LONGUEUR_MIN_MOTIF = 10


class DebloquerIn(BaseModel):
    statut_cible: Literal["en_traitement", "recu"] = "en_traitement"
    motif: str = Field(min_length=LONGUEUR_MIN_MOTIF, max_length=1000)
    reinitialiser_compteur: bool = True


class NoteIn(BaseModel):
    texte: str = Field(min_length=1, max_length=notes.LONGUEUR_MAX_NOTE)


@router.get("/dossiers")
async def tous_les_dossiers(
    inclure_en_cours: bool = Query(False), admin: dict = Depends(get_current_admin)
):
    """Tous les dossiers, toutes communes. Les dialogues encore en cours sont exclus par défaut."""
    return {"dossiers": await db.executer(list_dossiers_admin, inclure_en_cours)}


@router.get("/dossiers/{dossier_id}")
async def detail_dossier(dossier_id: str, admin: dict = Depends(get_current_admin)):
    dossier = await acces.charger_dossier(dossier_id)

    def _contenu():
        documents = list_documents(dossier_id)
        for document in documents:
            if document.get("fichier_url"):
                document["url_signee"] = get_document_signed_url(document["fichier_url"])
        generes = list_documents_generes(dossier_id)
        for genere in generes:
            if genere.get("contenu_url"):
                genere["url_signee"] = get_document_genere_signed_url(genere["contenu_url"])
        return {
            "documents": documents,
            "document_formulaires": list_document_formulaires(dossier_id),
            "cas_particuliers": list_cas_particuliers(dossier_id),
            "documents_generes": generes,
        }

    contenu = await db.executer(_contenu)
    await audit.journaliser(
        "dossier_consulte_admin", acteur=admin, cible_type="dossier", cible_id=dossier_id,
        cible_libelle=dossier.get("numero_suivi"),
    )
    return {"dossier": dossier, **contenu}


@router.post("/dossiers/{dossier_id}/debloquer")
async def debloquer_dossier(dossier_id: str, body: DebloquerIn, admin: dict = Depends(get_current_admin)):
    """
    Remet un dossier bloqué dans la file de travail de sa commune. Le motif est
    obligatoire : il apparaît dans l'historique du dossier et dans le journal.
    """
    dossier = await acces.charger_dossier(dossier_id)
    if dossier.get("statut") != "bloque":
        raise HTTPException(
            status_code=409,
            detail={"code": "dossier_non_bloque", "message": f"Ce dossier n'est pas bloqué (statut : « {dossier.get('statut')} »)."},
        )

    champs: dict = {"motif_blocage": None}
    if body.reinitialiser_compteur:
        champs["nb_iterations_correction"] = 0

    apres = await evenements.transition_statut(
        dossier_id,
        body.statut_cible,
        acteur_type="admin",
        acteur_id=admin["id"],
        libelle=f"Repris par l'administration : {body.motif.strip()}",
        details={"motif": body.motif.strip(), "compteur_reinitialise": body.reinitialiser_compteur},
        champs=champs,
        dossier_actuel=dossier,
    )
    if apres is None:
        raise HTTPException(status_code=502, detail="Échec de la mise à jour du dossier")

    await audit.journaliser(
        "dossier_debloque", acteur=admin, cible_type="dossier", cible_id=dossier_id,
        cible_libelle=dossier.get("numero_suivi"), details={"statut_cible": body.statut_cible, "motif": body.motif.strip()},
    )
    return {"id": dossier_id, "statut": apres["statut"], "nb_iterations_correction": apres.get("nb_iterations_correction")}


@router.get("/dossiers/{dossier_id}/historique")
async def historique_dossier(dossier_id: str, admin: dict = Depends(get_current_admin)):
    await acces.charger_dossier(dossier_id)
    return {"evenements": await notes.lister_evenements(dossier_id)}


@router.get("/dossiers/{dossier_id}/notes")
async def notes_dossier(dossier_id: str, admin: dict = Depends(get_current_admin)):
    await acces.charger_dossier(dossier_id)
    return {"notes": await notes.lister_notes(dossier_id)}


@router.post("/dossiers/{dossier_id}/notes", status_code=201)
async def ajouter_note_dossier(dossier_id: str, body: NoteIn, admin: dict = Depends(get_current_admin)):
    await acces.charger_dossier(dossier_id)
    return await notes.ajouter_note(dossier_id, admin["id"], body.texte)


@router.post("/consultants/{consultant_id}/reinitialiser-mot-de-passe")
async def reinitialiser_mot_de_passe(consultant_id: str, admin: dict = Depends(get_current_admin)):
    """
    Nouveau mot de passe temporaire, affiché UNE SEULE FOIS. Les sessions en
    cours du consultant sont révoquées et il devra le changer à la connexion.
    """
    resultat = await db.executer(reinitialiser_mot_de_passe_consultant, consultant_id)
    if resultat is None:
        raise HTTPException(status_code=404, detail="Consultant introuvable")

    await audit.journaliser(
        "consultant_mdp_reinitialise", acteur=admin, cible_type="consultant", cible_id=consultant_id,
        cible_libelle=resultat.get("email"),
    )
    return resultat


@router.get("/journal")
async def journal_activite(
    limite: int = Query(100, ge=1, le=500),
    action: Optional[str] = None,
    acteur_id: Optional[str] = None,
    cible_type: Optional[str] = None,
    admin: dict = Depends(get_current_admin),
):
    return await audit.lister(limite=limite, action=action, acteur_id=acteur_id, cible_type=cible_type)
