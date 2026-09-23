"""
Registre des connexions WebSocket actives (processus courant).

Deux index : par session de dialogue (une seule connexion active par session —
une nouvelle connexion remplace l'ancienne) et par citoyen (plusieurs appareils
possibles, utile pour pousser un changement de statut de dossier).
"""
from __future__ import annotations

from typing import Optional, Protocol


class ConnexionEnregistrable(Protocol):
    citoyen_id: Optional[str]
    etat: Optional[dict]


class Registre:
    def __init__(self):
        self._par_session: dict[str, ConnexionEnregistrable] = {}
        self._par_citoyen: dict[str, list[ConnexionEnregistrable]] = {}

    def enregistrer(self, connexion: ConnexionEnregistrable) -> Optional[ConnexionEnregistrable]:
        """Indexe la connexion ; retourne celle qu'elle remplace pour la même session (à fermer), sinon None."""
        session_id = connexion.etat["id"]
        ancienne = self._par_session.get(session_id)
        self._par_session[session_id] = connexion
        connexions = self._par_citoyen.setdefault(connexion.citoyen_id, [])
        if connexion not in connexions:
            connexions.append(connexion)
        return ancienne if ancienne is not connexion else None

    def retirer(self, connexion: ConnexionEnregistrable, session_id: Optional[str] = None) -> None:
        cle = session_id or (connexion.etat or {}).get("id")
        if cle and self._par_session.get(cle) is connexion:
            del self._par_session[cle]
        connexions = self._par_citoyen.get(connexion.citoyen_id)
        if connexions and connexion in connexions and not any(c is connexion for c in self._par_session.values()):
            connexions.remove(connexion)
            if not connexions:
                del self._par_citoyen[connexion.citoyen_id]

    def pour_session(self, session_id: str) -> Optional[ConnexionEnregistrable]:
        return self._par_session.get(session_id)

    def pour_citoyen(self, citoyen_id: str) -> list:
        return list(self._par_citoyen.get(citoyen_id, []))

    def sessions_connectees(self) -> set[str]:
        return set(self._par_session)


registre = Registre()
