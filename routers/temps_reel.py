"""
Points d'entrée WebSocket du dialogue vocal.

`/ws/v2` est déclaré AVANT `/ws/{session_id}` : sinon « v2 » serait pris pour
une clé de session du protocole historique.
"""
from __future__ import annotations

from fastapi import APIRouter, WebSocket

from services import evenements
from temps_reel import connexion as module_connexion
from temps_reel import relances

router = APIRouter(tags=["temps-reel"])

# Tout changement de statut d'un dossier est poussé en direct au citoyen connecté.
evenements.abonner(relances.diffuser_transition)


@router.websocket("/ws/v2")
async def websocket_v2(websocket: WebSocket) -> None:
    await module_connexion.Connexion(websocket, protocole=module_connexion.PROTOCOLE_V2).demarrer_v2()


@router.websocket("/ws/{session_id}")
async def websocket_v1(websocket: WebSocket, session_id: str) -> None:
    await module_connexion.Connexion(websocket, protocole=module_connexion.PROTOCOLE_V1).demarrer_v1(
        session_id, websocket.query_params.get("token")
    )
