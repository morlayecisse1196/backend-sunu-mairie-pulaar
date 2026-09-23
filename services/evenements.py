"""
Transitions de statut et historique des dossiers — point de passage UNIQUE.

Pourquoi : les changements de statut étaient dispersés dans main.py (WS,
endpoints citoyen, consultant) sans trace de qui/quand, sans notification, et
sans que le citoyen connecté soit prévenu en direct. Toute transition passe
désormais par `transition_statut()` :

  1. mise à jour du dossier (avec repli si une colonne de migration manque) ;
  2. événement d'historique (`dossier_evenements`, migration 012) ;
  3. diffusion aux abonnés (notifications, push temps réel, FCM) — en tâche de
     fond : un abonné lent ou en échec ne retarde ni ne fait échouer l'appelant.

Les abonnés s'enregistrent au démarrage (`abonner`) : ce module ne dépend ni
des notifications ni du WebSocket.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from dossiers_repo import get_dossier, update_dossier
from services import db
from services.journal import obtenir_logger

log = obtenir_logger("evenements")

LIBELLES_TRANSITION = {
    "en_cours": "Démarche commencée avec l'agent vocal",
    "recu": "Demande confirmée par le citoyen",
    "en_traitement": "Dossier ouvert par un consultant",
    "genere": "Document officiel généré",
    "en_attente_validation_citoyen": "Document envoyé au citoyen pour validation",
    "finalise": "Document validé par le citoyen",
    "corrections_demandees": "Correction demandée par le citoyen",
    "bloque": "Dossier bloqué — reprise humaine nécessaire",
}

# Colonnes ajoutées par une migration récente : si la base n'est pas à jour,
# la transition est rejouée SANS elles plutôt que d'échouer (un statut qui ne
# change pas serait bien plus grave qu'un motif non enregistré).
_CHAMPS_DE_MIGRATION = {"motif_blocage"}


@dataclass(frozen=True)
class Transition:
    dossier_id: str
    statut_avant: Optional[str]
    statut_apres: str
    acteur_type: str
    acteur_id: Optional[str]
    libelle: str
    dossier: dict = field(default_factory=dict)
    details: Optional[dict] = None


Abonne = Callable[[Transition], Awaitable[None]]
_abonnes: list[Abonne] = []
_taches_en_vol: set[asyncio.Task] = set()
_table_evenements_absente_signalee = False


def abonner(abonne: Abonne) -> None:
    if abonne not in _abonnes:
        _abonnes.append(abonne)


def reinitialiser_abonnes() -> None:
    """Tests uniquement."""
    _abonnes.clear()


async def ajouter_evenement(
    dossier_id: str,
    type_evenement: str,
    libelle: str,
    *,
    acteur_type: str,
    acteur_id: Optional[str] = None,
    statut_avant: Optional[str] = None,
    statut_apres: Optional[str] = None,
    details: Optional[dict] = None,
) -> Optional[dict]:
    """Ajoute une ligne d'historique. Best-effort : ne lève jamais."""
    global _table_evenements_absente_signalee
    ligne = {
        "dossier_id": dossier_id,
        "type": type_evenement,
        "libelle": libelle,
        "acteur_type": acteur_type,
        "acteur_id": acteur_id,
        "statut_avant": statut_avant,
        "statut_apres": statut_apres,
        "details": details,
    }
    try:
        reponse = await db.executer(lambda: db.client().table("dossier_evenements").insert(ligne).execute())
        return reponse.data[0] if reponse.data else None
    except Exception as exc:  # noqa: BLE001
        if db.est_erreur_schema(exc):
            if not _table_evenements_absente_signalee:
                log.warning("Table dossier_evenements absente (migration 012) — historique non enregistré")
                _table_evenements_absente_signalee = True
        else:
            log.error("Écriture d'événement échouée (dossier=%s, type=%s, erreur=%s)", dossier_id, type_evenement, type(exc).__name__)
        return None


async def _diffuser(transition: Transition) -> None:
    for abonne in list(_abonnes):
        try:
            await abonne(transition)
        except Exception as exc:  # noqa: BLE001
            log.error("Abonné %s en échec (dossier=%s, erreur=%s)", getattr(abonne, "__name__", abonne), transition.dossier_id, type(exc).__name__)


async def transition_statut(
    dossier_id: str,
    nouveau_statut: str,
    *,
    acteur_type: str,
    acteur_id: Optional[str] = None,
    libelle: Optional[str] = None,
    details: Optional[dict] = None,
    champs: Optional[dict] = None,
    dossier_actuel: Optional[dict] = None,
) -> Optional[dict]:
    """
    Change le statut d'un dossier et déclenche historique + diffusion.
    Retourne le dossier après transition, ou None si l'écriture a échoué.
    """
    champs = dict(champs or {})
    avant = dossier_actuel if dossier_actuel is not None else await db.executer(get_dossier, dossier_id)
    statut_avant = (avant or {}).get("statut")

    ok = await db.executer(lambda: update_dossier(dossier_id, statut=nouveau_statut, **champs))
    if not ok and _CHAMPS_DE_MIGRATION & champs.keys():
        champs_sans_migration = {k: v for k, v in champs.items() if k not in _CHAMPS_DE_MIGRATION}
        log.warning("Transition rejouée sans %s (migration 012 absente ?)", sorted(_CHAMPS_DE_MIGRATION & champs.keys()))
        ok = await db.executer(lambda: update_dossier(dossier_id, statut=nouveau_statut, **champs_sans_migration))
        champs = champs_sans_migration
    if not ok:
        log.error("Transition de statut échouée (dossier=%s, %s -> %s)", dossier_id, statut_avant, nouveau_statut)
        return None

    apres = {**(avant or {"id": dossier_id}), **champs, "statut": nouveau_statut}
    texte = libelle or LIBELLES_TRANSITION.get(nouveau_statut, f"Statut : {nouveau_statut}")

    await ajouter_evenement(
        dossier_id,
        "statut_modifie",
        texte,
        acteur_type=acteur_type,
        acteur_id=acteur_id,
        statut_avant=statut_avant,
        statut_apres=nouveau_statut,
        details=details,
    )

    transition = Transition(
        dossier_id=dossier_id,
        statut_avant=statut_avant,
        statut_apres=nouveau_statut,
        acteur_type=acteur_type,
        acteur_id=acteur_id,
        libelle=texte,
        dossier=apres,
        details=details,
    )
    if _abonnes:
        tache = asyncio.create_task(_diffuser(transition))
        _taches_en_vol.add(tache)
        tache.add_done_callback(_taches_en_vol.discard)
    return apres
