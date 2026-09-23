"""
Journal d'audit des actions sensibles (comptes, communes, tampons, modèles,
reprises de dossier, documents).

Journal en AJOUT SEUL : aucune route ne modifie ni ne supprime une entrée.
Les clés d'action sont celles attendues par l'écran web « Journal d'activité ».
"""
from __future__ import annotations

from typing import Optional

from services import db
from services.journal import obtenir_logger

log = obtenir_logger("audit")

TABLE = "journal_audit"
MIGRATION = "016"

ACTIONS = {
    "connexion",
    "connexion_echec",
    "mot_de_passe_modifie",
    "consultant_cree",
    "consultant_desactive",
    "consultant_reactive",
    "consultant_commune_modifiee",
    "consultant_mdp_reinitialise",
    "commune_creee",
    "commune_modifiee",
    "tampon_enregistre",
    "template_cree",
    "template_modifie",
    "dossier_debloque",
    "document_genere",
    "document_envoye_citoyen",
    "dossier_consulte_admin",
}

LIBELLES = {
    "connexion": "Connexion",
    "connexion_echec": "Tentative de connexion échouée",
    "mot_de_passe_modifie": "Mot de passe modifié",
    "consultant_cree": "Compte consultant créé",
    "consultant_desactive": "Compte consultant désactivé",
    "consultant_reactive": "Compte consultant réactivé",
    "consultant_commune_modifiee": "Commune d'un consultant modifiée",
    "consultant_mdp_reinitialise": "Mot de passe réinitialisé par l'administration",
    "commune_creee": "Commune créée",
    "commune_modifiee": "Commune modifiée",
    "tampon_enregistre": "Tampon numérique enregistré",
    "template_cree": "Modèle de document créé",
    "template_modifie": "Modèle de document modifié",
    "dossier_debloque": "Dossier débloqué",
    "document_genere": "Document généré",
    "document_envoye_citoyen": "Document envoyé au citoyen",
    "dossier_consulte_admin": "Dossier consulté par l'administration",
}

# Ce que l'agent voit dans « Activité de mon compte » : ce qui touche à SON
# accès, pas son travail quotidien sur les dossiers.
ACTIONS_COMPTE = ("connexion", "connexion_echec", "mot_de_passe_modifie", "consultant_mdp_reinitialise")

_table_absente_signalee = False


def libelle(action: str) -> str:
    return LIBELLES.get(action, action.replace("_", " ").capitalize())


async def journaliser(
    action: str,
    *,
    acteur: Optional[dict] = None,
    cible_type: Optional[str] = None,
    cible_id: Optional[str] = None,
    cible_libelle: Optional[str] = None,
    details: Optional[dict] = None,
) -> None:
    """Best-effort : une écriture d'audit ne doit jamais faire échouer l'action métier."""
    global _table_absente_signalee
    if action not in ACTIONS:
        log.warning("Action d'audit hors catalogue : %s", action)
    ligne = {
        "acteur_id": (acteur or {}).get("id"),
        "acteur_email": (acteur or {}).get("email"),
        "acteur_role": (acteur or {}).get("role"),
        "action": action,
        "cible_type": cible_type,
        "cible_id": cible_id,
        "cible_libelle": cible_libelle,
        "details": details,
    }
    try:
        await db.executer(lambda: db.client().table(TABLE).insert(ligne).execute())
    except Exception as exc:  # noqa: BLE001
        if db.est_erreur_schema(exc):
            if not _table_absente_signalee:
                log.warning("Table journal_audit absente (migration %s) — audit non enregistré", MIGRATION)
                _table_absente_signalee = True
        else:
            log.error("Écriture d'audit échouée (action=%s, erreur=%s)", action, type(exc).__name__)


async def lister(
    *, limite: int = 100, action: Optional[str] = None, acteur_id: Optional[str] = None, cible_type: Optional[str] = None
) -> dict:
    def _lire():
        requete = db.client().table(TABLE).select("*", count="exact")
        if action:
            requete = requete.eq("action", action)
        if acteur_id:
            requete = requete.eq("acteur_id", acteur_id)
        if cible_type:
            requete = requete.eq("cible_type", cible_type)
        reponse = requete.order("cree_le", desc=True).limit(limite).execute()
        entrees = reponse.data or []
        for entree in entrees:
            entree["libelle"] = libelle(entree.get("action", ""))
        return {"entrees": entrees, "total": reponse.count or len(entrees)}

    try:
        return await db.executer(_lire)
    except Exception as exc:  # noqa: BLE001
        if db.est_erreur_schema(exc):
            raise db.migration_manquante(MIGRATION, "Le journal d'activité")
        log.error("Lecture du journal échouée (%s)", type(exc).__name__)
        raise


async def activite_du_compte(user_id: str, limite: int = 10) -> list:
    """Activité liée à l'accès d'un agent. Silencieuse si la migration 016 manque."""
    def _lire():
        entrees = (
            db.client().table(TABLE).select("*").eq("acteur_id", user_id)
            .in_("action", list(ACTIONS_COMPTE)).order("cree_le", desc=True).limit(limite).execute().data or []
        )
        for entree in entrees:
            entree["libelle"] = libelle(entree.get("action", ""))
        return entrees

    try:
        return await db.executer(_lire)
    except Exception as exc:  # noqa: BLE001
        if db.est_erreur_schema(exc):
            return []
        log.error("Lecture de l'activité du compte échouée (%s)", type(exc).__name__)
        return []
