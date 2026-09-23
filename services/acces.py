"""
Contrôles d'accès aux dossiers, partagés par les routeurs v3.

Même règle que main.py (`_verifier_dossier_commune_consultant`) : un consultant
ne voit QUE les dossiers de la commune de son profil — jamais une commune
passée en paramètre.
"""
from __future__ import annotations

from fastapi import HTTPException

from dossiers_repo import get_dossier, resoudre_commune_id
from services import db


async def charger_dossier(dossier_id: str) -> dict:
    dossier = await db.executer(get_dossier, dossier_id)
    if not dossier:
        raise HTTPException(status_code=404, detail="Dossier introuvable")
    return dossier


async def dossier_pour_consultant(dossier_id: str, consultant: dict) -> dict:
    dossier = await charger_dossier(dossier_id)
    commune_id = await db.executer(resoudre_commune_id, consultant["commune"])
    if not commune_id or dossier.get("commune_id") != commune_id:
        raise HTTPException(status_code=403, detail="Ce dossier n'appartient pas à votre commune")
    return dossier
