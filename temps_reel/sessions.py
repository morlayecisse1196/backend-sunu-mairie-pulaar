"""
Magasin des sessions de dialogue : cache mémoire + persistance
(`dialogue_sessions`, migration 013) + verrou par session.

Garanties :
  * PROPRIÉTÉ — une clé de session déjà utilisée par un autre citoyen est
    refusée (`SessionEtrangere`). En cas d'incident base pendant cette
    vérification, on refuse (`ErreurPersistance`) plutôt que d'autoriser.
  * UNE session active par clé ; `nouvelle=True` clôt l'active et en ouvre une.
  * REPRISE après coupure réseau ou redémarrage serveur (état relu en base).
  * DÉGRADATION — si la migration 013 n'est pas appliquée, fonctionnement en
    mémoire seule (propriété toujours vérifiée dans le processus), signalé
    une fois dans les logs.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from services import db
from services.journal import obtenir_logger
from temps_reel.etat import deserialiser, nouvel_etat, serialiser

log = obtenir_logger("sessions")

TABLE = "dialogue_sessions"


class SessionEtrangere(Exception):
    """La clé de session appartient à un autre citoyen."""


class ErreurPersistance(Exception):
    """La base est injoignable pour une vérification qui ne peut pas être contournée."""


class PersistanceSupabase:
    """Accès synchrones (exécutés en thread par le magasin)."""

    def lignes_par_cle(self, cle_client: str) -> list:
        return (
            db.client().table(TABLE).select("*").eq("cle_client", cle_client).order("updated_at", desc=True).limit(50).execute().data
            or []
        )

    def active_du_citoyen(self, citoyen_id: str) -> Optional[dict]:
        data = (
            db.client().table(TABLE).select("*").eq("citoyen_id", citoyen_id).eq("statut", "active")
            .order("updated_at", desc=True).limit(1).execute().data
        )
        return data[0] if data else None

    def active_par_dossier(self, dossier_id: str) -> Optional[dict]:
        data = (
            db.client().table(TABLE).select("*").eq("dossier_id", dossier_id).eq("statut", "active")
            .order("updated_at", desc=True).limit(1).execute().data
        )
        return data[0] if data else None

    def inserer(self, ligne: dict) -> None:
        db.client().table(TABLE).insert(ligne).execute()

    def mettre_a_jour(self, session_id: str, ligne: dict) -> None:
        champs = {k: v for k, v in ligne.items() if k != "id"}
        champs["updated_at"] = datetime.now(timezone.utc).isoformat()
        db.client().table(TABLE).update(champs).eq("id", session_id).execute()


class MagasinSessions:
    def __init__(self, persistance=None):
        self._persistance = persistance or PersistanceSupabase()
        self._etats: dict[str, dict] = {}
        self._verrous: dict[str, asyncio.Lock] = {}
        self._activite: dict[str, float] = {}
        self._persistance_disponible = True

    # -- utilitaires ---------------------------------------------------------

    @property
    def persistance_disponible(self) -> bool:
        return self._persistance_disponible

    def verrou(self, session_id: str) -> asyncio.Lock:
        return self._verrous.setdefault(session_id, asyncio.Lock())

    def obtenir(self, session_id: str) -> Optional[dict]:
        return self._etats.get(session_id)

    def _toucher(self, session_id: str) -> None:
        self._activite[session_id] = time.monotonic()

    async def _appeler(self, fonction, *args, critique: bool = False):
        if not self._persistance_disponible:
            return None
        try:
            return await db.executer(fonction, *args)
        except Exception as exc:  # noqa: BLE001
            if db.est_erreur_schema(exc):
                self._persistance_disponible = False
                log.warning("Table %s absente (migration 013) — sessions conservées en mémoire uniquement", TABLE)
                return None
            log.error("Accès %s échoué (%s)", TABLE, type(exc).__name__)
            if critique:
                raise ErreurPersistance("Sessions momentanément indisponibles") from exc
            return None

    def _active_en_memoire(self, *, cle_client: Optional[str], citoyen_id: str) -> Optional[dict]:
        candidates = [
            etat for etat in self._etats.values()
            if etat["statut"] == "active" and etat["citoyen_id"] == citoyen_id and (cle_client is None or etat["cle_client"] == cle_client)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda e: self._activite.get(e["id"], 0.0))

    # -- API -----------------------------------------------------------------

    async def ouvrir(
        self, *, citoyen_id: str, commune_profil: str, cle_client: Optional[str] = None, nouvelle: bool = False
    ) -> tuple[dict, bool]:
        """Retourne `(etat, reprise)` : la session active reprise, ou une nouvelle."""
        active: Optional[dict] = None

        if cle_client:
            if any(e["cle_client"] == cle_client and e["citoyen_id"] != citoyen_id for e in self._etats.values()):
                raise SessionEtrangere(cle_client)
            lignes = await self._appeler(self._persistance.lignes_par_cle, cle_client, critique=True) or []
            if any(ligne["citoyen_id"] != citoyen_id for ligne in lignes):
                raise SessionEtrangere(cle_client)
            active = self._active_en_memoire(cle_client=cle_client, citoyen_id=citoyen_id)
            if active is None:
                ligne_active = next((ligne for ligne in lignes if ligne.get("statut") == "active"), None)
                active = deserialiser(ligne_active, commune_profil=commune_profil) if ligne_active else None
        else:
            active = self._active_en_memoire(cle_client=None, citoyen_id=citoyen_id)
            if active is None:
                ligne = await self._appeler(self._persistance.active_du_citoyen, citoyen_id, critique=True)
                active = deserialiser(ligne, commune_profil=commune_profil) if ligne else None

        if active is not None and nouvelle:
            await self.clore(active, "nouvelle_conversation")
            active = None

        if active is not None:
            active["commune_profil"] = commune_profil or active.get("commune_profil") or "National"
            self._etats[active["id"]] = active
            self._toucher(active["id"])
            return active, True

        session_id = str(uuid.uuid4())
        etat = nouvel_etat(
            session_id=session_id, cle_client=cle_client or session_id, citoyen_id=citoyen_id, commune_profil=commune_profil
        )
        await self._appeler(self._persistance.inserer, serialiser(etat))
        self._etats[session_id] = etat
        self._toucher(session_id)
        return etat, False

    async def enregistrer(self, etat: dict) -> None:
        self._toucher(etat["id"])
        await self._appeler(self._persistance.mettre_a_jour, etat["id"], serialiser(etat))

    async def clore(self, etat: dict, raison: str) -> None:
        etat["statut"] = "close"
        etat["raison_cloture"] = raison
        ligne = serialiser(etat)
        ligne["close_le"] = datetime.now(timezone.utc).isoformat()
        await self._appeler(self._persistance.mettre_a_jour, etat["id"], ligne)
        self._etats.pop(etat["id"], None)
        self._activite.pop(etat["id"], None)

    async def active_du_citoyen(self, citoyen_id: str) -> Optional[dict]:
        """Session active la plus récente du citoyen, sans jamais en créer une."""
        etat = self._active_en_memoire(cle_client=None, citoyen_id=citoyen_id)
        if etat is not None:
            return etat
        ligne = await self._appeler(self._persistance.active_du_citoyen, citoyen_id)
        return deserialiser(ligne) if ligne else None

    async def pour_dossier(self, dossier_id: str) -> Optional[dict]:
        """Session active liée à un dossier (relance après upload, reprise admin)."""
        for etat in self._etats.values():
            if etat.get("dossier_id") == dossier_id and etat["statut"] == "active":
                return etat
        ligne = await self._appeler(self._persistance.active_par_dossier, dossier_id)
        if not ligne:
            return None
        etat = deserialiser(ligne)
        self._etats[etat["id"]] = etat
        self._toucher(etat["id"])
        return etat

    def purger_inactives(self, ttl_secondes: float, sessions_connectees: set[str] | None = None) -> int:
        """Retire du cache les sessions inactives (l'état reste en base)."""
        limite = time.monotonic() - ttl_secondes
        connectees = sessions_connectees or set()
        a_retirer = [
            sid for sid, derniere in self._activite.items()
            if derniere < limite and sid not in connectees and not self.verrou(sid).locked()
        ]
        for sid in a_retirer:
            self._etats.pop(sid, None)
            self._activite.pop(sid, None)
            self._verrous.pop(sid, None)
        return len(a_retirer)


magasin = MagasinSessions()
