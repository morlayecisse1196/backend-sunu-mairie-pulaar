"""
Compléments consultant (web v3) : ce que le citoyen a signalé, les notes entre
agents et l'historique complet du dossier.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from auth import get_current_consultant
from services import acces, notes

router = APIRouter(prefix="/consultant/dossiers/{dossier_id}", tags=["consultant"])


class NoteIn(BaseModel):
    texte: str = Field(min_length=1, max_length=notes.LONGUEUR_MAX_NOTE)


@router.get("/remarques")
async def remarques_du_dossier(dossier_id: str, consultant: dict = Depends(get_current_consultant)):
    """Signalements du citoyen — le consultant voit enfin CE QU'il a signalé (table `remarques`)."""
    await acces.dossier_pour_consultant(dossier_id, consultant)
    return {"remarques": await notes.lister_remarques(dossier_id)}


@router.get("/notes")
async def notes_du_dossier(dossier_id: str, consultant: dict = Depends(get_current_consultant)):
    await acces.dossier_pour_consultant(dossier_id, consultant)
    return {"notes": await notes.lister_notes(dossier_id)}


@router.post("/notes", status_code=201)
async def ajouter_note(dossier_id: str, body: NoteIn, consultant: dict = Depends(get_current_consultant)):
    await acces.dossier_pour_consultant(dossier_id, consultant)
    return await notes.ajouter_note(dossier_id, consultant["id"], body.texte)


@router.get("/historique")
async def historique_du_dossier(dossier_id: str, consultant: dict = Depends(get_current_consultant)):
    await acces.dossier_pour_consultant(dossier_id, consultant)
    return {"evenements": await notes.lister_evenements(dossier_id)}
