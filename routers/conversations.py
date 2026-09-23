"""
Conversations (démarches vocales) du citoyen — hors WebSocket.

`POST /conversations` démarre une nouvelle démarche : la session active est
close et une nouvelle est ouverte. Si l'app est connectée en temps réel sur
l'ancienne session, sa connexion bascule automatiquement sur la nouvelle.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_citoyen
from temps_reel import sessions
from temps_reel.etat import instantane_client
from temps_reel.registre import registre

router = APIRouter(tags=["conversations"])


class NouvelleConversationIn(BaseModel):
    cle_client: Optional[str] = Field(default=None, max_length=128)


@router.post("/conversations")
async def nouvelle_conversation(body: Optional[NouvelleConversationIn] = None, user: dict = Depends(get_current_citoyen)):
    try:
        etat, _ = await sessions.magasin.ouvrir(
            citoyen_id=user["id"], commune_profil=user["commune"], cle_client=body.cle_client if body else None, nouvelle=True
        )
    except sessions.SessionEtrangere:
        raise HTTPException(status_code=403, detail="Cette clé de session appartient à un autre utilisateur.")
    except sessions.ErreurPersistance:
        raise HTTPException(status_code=503, detail="Service momentanément indisponible, réessayez.")

    for connexion in registre.pour_citoyen(user["id"]):
        if connexion.etat is not None and connexion.etat.get("statut") == "close":
            await connexion.adopter_session_externe(etat)
    return {"session": instantane_client(etat)}


@router.get("/conversations/active")
async def conversation_active(user: dict = Depends(get_current_citoyen)):
    etat = await sessions.magasin.active_du_citoyen(user["id"])
    return {"session": instantane_client(etat) if etat else None}
