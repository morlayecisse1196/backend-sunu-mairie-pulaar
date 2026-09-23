"""
Parole et informations initiées par le serveur, hors tour de dialogue.

* `relancer_apres_document` — après un upload réel (REST), confirme et
  enchaîne l'étape suivante sur la connexion ouverte. Si le citoyen n'est pas
  connecté, l'état avance quand même (et est enregistré) ; la phrase sera dite
  à sa prochaine connexion.
* `pousser_message` — consigne vocale ponctuelle (ex. photo floue à reprendre).
* `diffuser_transition` — abonné de services/evenements : prévient en direct
  le citoyen connecté (tous ses appareils) qu'un de ses dossiers a changé.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from services.evenements import Transition
from services.journal import obtenir_logger
from temps_reel import moteur
from temps_reel.moteur import ResultatTour
from temps_reel.registre import registre
from temps_reel.sessions import magasin

log = obtenir_logger("relances")

# Références fortes vers les tâches de fond : une tâche créée par
# asyncio.create_task sans référence conservée peut être détruite par le
# ramasse-miettes avant d'avoir fini (documenté par Python).
_taches_de_fond: set[asyncio.Task] = set()


def planifier(coroutine) -> asyncio.Task:
    """Lance une relance en arrière-plan sans bloquer la réponse HTTP qui l'a déclenchée."""
    tache = asyncio.create_task(coroutine)
    _taches_de_fond.add(tache)
    tache.add_done_callback(_taches_de_fond.discard)
    return tache


async def relancer_apres_document(dossier_id: str, type_document: Optional[str] = None) -> bool:
    etat = await magasin.pour_dossier(dossier_id)
    if etat is None:
        return False
    connexion = registre.pour_session(etat["id"])
    if connexion is not None and connexion.etat is not None and connexion.etat["id"] == etat["id"]:
        etat = connexion.etat

    async with magasin.verrou(etat["id"]):
        try:
            resultat = await moteur.apres_document_recu(etat)
        except Exception as exc:  # noqa: BLE001
            log.error("Relance après document en échec (dossier=%s, erreur=%s)", dossier_id, type(exc).__name__)
            return False
        if resultat is None:
            return False
        if connexion is None or connexion.fermee:
            etat["reponse_en_attente"] = resultat.reponse_fr
        await magasin.enregistrer(etat)

    if connexion is not None and not connexion.fermee:
        await connexion.envoyer_json({"type": "document_recu", "dossier_id": dossier_id, "document_type": type_document})
        connexion.pousser(resultat)
    return True


async def pousser_message(dossier_id: str, texte_fr: str) -> bool:
    """Dit une consigne au citoyen connecté sur la session liée au dossier (sans changer l'état du dialogue)."""
    etat = await magasin.pour_dossier(dossier_id)
    if etat is None:
        return False
    connexion = registre.pour_session(etat["id"])
    if connexion is None or connexion.fermee:
        return False
    return connexion.pousser(ResultatTour(texte_fr, document_attendu=etat.get("document_en_attente")))


async def diffuser_transition(transition: Transition) -> None:
    citoyen_id = (transition.dossier or {}).get("citoyen_id")
    if not citoyen_id:
        return
    message = {
        "type": "dossier_mis_a_jour",
        "dossier_id": transition.dossier_id,
        "statut": transition.statut_apres,
        "numero_suivi": (transition.dossier or {}).get("numero_suivi"),
        "libelle": transition.libelle,
    }
    for connexion in registre.pour_citoyen(citoyen_id):
        await connexion.envoyer_json(message)
