"""
Profil de l'utilisateur connecté.

Tâche 1.4 : `POST /me/profil-citoyen` remplace l'écriture DIRECTE de la table
`profiles` par l'application mobile (upsert avec le jeton du citoyen) — cette
écriture directe est désormais bloquée par la migration 011 pour tout ce qui
touche au rôle, et c'est le backend qui garantit le rôle « citoyen ».
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from auth import get_current_citoyen, get_current_profile
from services import audit, db, profil
from services.journal import obtenir_logger

router = APIRouter(tags=["profil"])
log = obtenir_logger("routers.moi")

FORMAT_TELEPHONE = re.compile(r"^\+?[\d\s.\-]{8,20}$")


class ProfilCitoyenIn(BaseModel):
    commune: str = Field(min_length=1, max_length=80)
    nom_complet: Optional[str] = Field(default=None, max_length=120)
    langue: Optional[Literal["pulaar", "francais"]] = None


@router.post("/me/profil-citoyen")
async def enregistrer_profil_citoyen(body: ProfilCitoyenIn, user: dict = Depends(get_current_citoyen)):
    """Crée ou met à jour le profil d'un citoyen (commune, et si disponibles nom et langue)."""
    if user["role"] in ("consultant", "admin"):
        raise HTTPException(status_code=403, detail="La commune d'un agent est gérée par l'administration.")

    commune = body.commune.strip()
    if not commune:
        raise HTTPException(status_code=400, detail="La commune est obligatoire.")

    try:
        await db.executer(
            lambda: db.client().table("profiles").upsert({"id": user["id"], "commune": commune}, on_conflict="id").execute()
        )
    except Exception as e:
        log.error("Écriture du profil citoyen échouée (user=%s, erreur=%s)", user["id"], type(e).__name__)
        raise HTTPException(status_code=502, detail="Échec de l'enregistrement du profil.")

    extras = {}
    if body.nom_complet and body.nom_complet.strip():
        extras["nom_complet"] = body.nom_complet.strip()
    if body.langue:
        extras["langue_preferee"] = body.langue

    champs_ignores: list[str] = []
    if extras:
        try:
            await db.executer(lambda: db.client().table("profiles").update(extras).eq("id", user["id"]).execute())
        except Exception as e:
            if db.est_erreur_schema(e):
                champs_ignores = sorted(extras)
                log.warning("Colonnes de profil absentes (migration 012 non appliquée) : %s", champs_ignores)
            else:
                log.error("Mise à jour des informations de profil échouée (user=%s, erreur=%s)", user["id"], type(e).__name__)
                raise HTTPException(status_code=502, detail="Échec de l'enregistrement du profil.")

    return {"id": user["id"], "role": "citoyen", "commune": commune, "champs_ignores": champs_ignores}


# --- Profil de l'agent connecté (web consultant/admin) ---------------------


class ProfilPatch(BaseModel):
    """`role`, `commune` et `email` sont volontairement absents : ils relèvent de l'administration."""

    nom_complet: Optional[str] = Field(default=None, max_length=120)
    telephone: Optional[str] = Field(default=None, max_length=20)
    fonction: Optional[str] = Field(default=None, max_length=80)

    @field_validator("telephone")
    @classmethod
    def _valider_telephone(cls, valeur: Optional[str]) -> Optional[str]:
        if valeur is None or not valeur.strip():
            return None
        valeur = valeur.strip()
        if not FORMAT_TELEPHONE.match(valeur):
            raise ValueError("Numéro de téléphone invalide (8 à 20 chiffres, espaces, points ou tirets).")
        return valeur


class PreferencesPatch(BaseModel):
    theme: Optional[Literal["light", "dark", "system"]] = None
    notifications_email: Optional[bool] = None


@router.patch("/me")
async def modifier_mon_profil(body: ProfilPatch, moi: dict = Depends(get_current_profile)):
    champs = body.model_dump(exclude_unset=True)
    if not champs:
        raise HTTPException(status_code=400, detail="Aucun champ à modifier.")
    champs = {cle: (valeur.strip() if isinstance(valeur, str) else valeur) for cle, valeur in champs.items()}
    await profil.mettre_a_jour_identite(moi["id"], champs)
    return await profil.lire(moi["id"], moi["role"], moi["commune"], moi.get("email"))


@router.patch("/me/preferences")
async def modifier_mes_preferences(body: PreferencesPatch, moi: dict = Depends(get_current_profile)):
    preferences = body.model_dump(exclude_unset=True)
    if not preferences:
        raise HTTPException(status_code=400, detail="Aucune préférence à modifier.")
    return {"preferences": await profil.fusionner_preferences(moi["id"], preferences)}


@router.post("/me/mot-de-passe-modifie")
async def confirmer_mot_de_passe_modifie(moi: dict = Depends(get_current_profile)):
    """
    Appelé par le web APRÈS un changement de mot de passe réussi : lève le
    drapeau « mot de passe temporaire » qui bloque l'accès à l'espace.
    """
    await profil.marquer_mot_de_passe_modifie(moi["id"])
    await audit.journaliser(
        "mot_de_passe_modifie", acteur=moi, cible_type="compte", cible_id=moi["id"], cible_libelle=moi.get("email")
    )
    return {"ok": True}


@router.get("/me/activite")
async def mon_activite(limite: int = Query(10, ge=1, le=100), moi: dict = Depends(get_current_profile)):
    return {"evenements": await audit.activite_du_compte(moi["id"], limite)}
