"""
Notifications de l'utilisateur connecté (web consultant/admin ET mobile
citoyen) et enregistrement des appareils pour le push.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from auth import get_current_profile
from services import db, evenements, notifications
from services.journal import obtenir_logger

router = APIRouter(tags=["notifications"])
log = obtenir_logger("routers.notifications")

# Chaque transition de statut crée les notifications correspondantes.
evenements.abonner(notifications.sur_transition)

MIGRATION = "014"


def _erreur_base(exc: Exception, fonctionnalite: str) -> HTTPException:
    if db.est_erreur_schema(exc):
        return db.migration_manquante(MIGRATION, fonctionnalite)
    log.error("%s : erreur base (%s)", fonctionnalite, type(exc).__name__)
    return HTTPException(status_code=502, detail=f"{fonctionnalite} momentanément indisponibles.")


@router.get("/notifications")
async def lister_notifications(limite: int = Query(15, ge=1, le=100), user: dict = Depends(get_current_profile)):
    def _lire():
        table = db.client().table(notifications.TABLE)
        liste = (
            table.select("id, type, titre, message, lien, dossier_id, lu, cree_le")
            .eq("destinataire_id", user["id"]).order("cree_le", desc=True).limit(limite).execute().data
            or []
        )
        non_lues = (
            db.client().table(notifications.TABLE).select("id", count="exact")
            .eq("destinataire_id", user["id"]).eq("lu", False).limit(1).execute().count
            or 0
        )
        return liste, non_lues

    try:
        liste, non_lues = await db.executer(_lire)
    except Exception as exc:  # noqa: BLE001
        raise _erreur_base(exc, "Les notifications")
    return {"notifications": liste, "non_lues": non_lues}


@router.post("/notifications/tout-lu", status_code=204)
async def tout_marquer_lu(user: dict = Depends(get_current_profile)):
    try:
        await db.executer(
            lambda: db.client().table(notifications.TABLE).update({"lu": True}).eq("destinataire_id", user["id"]).eq("lu", False).execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise _erreur_base(exc, "Les notifications")
    return Response(status_code=204)


@router.post("/notifications/{notification_id}/lu", status_code=204)
async def marquer_lu(notification_id: str, user: dict = Depends(get_current_profile)):
    try:
        reponse = await db.executer(
            lambda: db.client().table(notifications.TABLE).update({"lu": True})
            .eq("id", notification_id).eq("destinataire_id", user["id"]).execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise _erreur_base(exc, "Les notifications")
    if not reponse.data:
        raise HTTPException(status_code=404, detail="Notification introuvable")
    return Response(status_code=204)


class AppareilIn(BaseModel):
    jeton_fcm: str = Field(min_length=20, max_length=4096)
    plateforme: Literal["android", "ios", "web"]
    langue: Optional[Literal["pulaar", "francais"]] = None


@router.post("/me/appareils")
async def enregistrer_appareil(body: AppareilIn, user: dict = Depends(get_current_profile)):
    ligne = {
        "utilisateur_id": user["id"],
        "jeton_fcm": body.jeton_fcm,
        "plateforme": body.plateforme,
        "langue": body.langue,
        "derniere_utilisation": datetime.now(timezone.utc).isoformat(),
    }
    try:
        # Un jeton est réattribué au compte connecté (téléphone partagé, changement de compte).
        await db.executer(lambda: db.client().table("appareils").upsert(ligne, on_conflict="jeton_fcm").execute())
    except Exception as exc:  # noqa: BLE001
        raise _erreur_base(exc, "L'enregistrement des appareils")
    return {"enregistre": True, "push_actif": notifications.push_fcm.est_configure()}


@router.delete("/me/appareils/{jeton_fcm}", status_code=204)
async def supprimer_appareil(jeton_fcm: str, user: dict = Depends(get_current_profile)):
    try:
        await db.executer(
            lambda: db.client().table("appareils").delete().eq("jeton_fcm", jeton_fcm).eq("utilisateur_id", user["id"]).execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise _erreur_base(exc, "L'enregistrement des appareils")
    return Response(status_code=204)
