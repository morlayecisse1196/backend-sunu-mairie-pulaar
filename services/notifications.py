"""
Notifications : qui prévenir, de quoi, à chaque transition de statut.

Abonné de services/evenements.py. La table de correspondance
(`annonces_pour_transition`) est une fonction pure : c'est elle qui fixe la
politique de notification, testée sans base.

Destinataires :
  * consultants de la commune du dossier — nouveau dossier, correction
    demandée, document validé, dossier bloqué, dossier repris par l'admin ;
  * administrateurs — dossier bloqué ;
  * citoyen — dossier pris en charge, document prêt à valider, dossier bloqué.
L'auteur d'une action n'est jamais notifié de sa propre action.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from services import db, push_fcm
from services.evenements import Transition
from services.journal import obtenir_logger

log = obtenir_logger("notifications")

TABLE = "notifications"
_table_absente_signalee = False


@dataclass(frozen=True)
class Annonce:
    role: str  # consultant | admin | citoyen
    type: str
    titre: str
    message: str


def lien(role: str, dossier_id: str) -> str:
    return {
        "consultant": f"/consultant/dossiers/{dossier_id}",
        "admin": f"/admin/dossiers/{dossier_id}",
        "citoyen": f"/mes-dossiers/{dossier_id}",
    }[role]


def annonces_pour_transition(transition: Transition) -> list[Annonce]:
    statut = transition.statut_apres
    numero = (transition.dossier or {}).get("numero_suivi")
    suffixe = f" — {numero}" if numero else ""
    annonces: list[Annonce] = []

    if statut == "recu":
        annonces.append(Annonce("consultant", "dossier_recu", f"Nouveau dossier à traiter{suffixe}", "Demande d'extrait de naissance confirmée par le citoyen."))
    elif statut == "en_traitement" and transition.acteur_type == "admin":
        annonces.append(Annonce("consultant", "dossier_recu", f"Dossier repris par l'administration{suffixe}", "Le dossier est de nouveau dans votre file de travail."))
    elif statut == "en_traitement":
        annonces.append(Annonce("citoyen", "dossier_en_traitement", "Votre dossier est en cours de traitement", "Un agent de la mairie vérifie votre demande."))
    elif statut == "en_attente_validation_citoyen":
        annonces.append(Annonce("citoyen", "document_pret", "Votre document est prêt", "Ouvrez l'application pour l'écouter et le valider."))
    elif statut == "corrections_demandees":
        annonces.append(Annonce("consultant", "corrections_demandees", f"Correction demandée{suffixe}", "Le citoyen a signalé une erreur sur son document."))
    elif statut == "finalise":
        annonces.append(Annonce("consultant", "dossier_valide_citoyen", f"Document validé{suffixe}", "Le citoyen a validé son extrait de naissance."))
    elif statut == "bloque":
        annonces.append(Annonce("admin", "dossier_bloque", f"Dossier bloqué{suffixe}", "Une reprise humaine est nécessaire."))
        annonces.append(Annonce("consultant", "dossier_bloque", f"Dossier bloqué{suffixe}", "Le dossier attend une reprise par l'administration."))
        annonces.append(Annonce("citoyen", "dossier_bloque", "Un agent va vous aider", "Votre demande nécessite l'aide d'un agent de la mairie."))
    return annonces


# -- accès base (synchrones, exécutés en thread) ----------------------------

def _consultants_de_la_commune_sync(commune_id: Optional[str]) -> list[str]:
    if not commune_id:
        return []
    communes = db.client().table("communes").select("nom").eq("id", commune_id).limit(1).execute().data
    if not communes:
        return []
    profils = db.client().table("profiles").select("id").eq("role", "consultant").ilike("commune", communes[0]["nom"]).execute().data
    return [p["id"] for p in profils or []]


def _administrateurs_sync() -> list[str]:
    return [p["id"] for p in db.client().table("profiles").select("id").eq("role", "admin").execute().data or []]


def _inserer_sync(lignes: list[dict]) -> None:
    db.client().table(TABLE).insert(lignes).execute()


def _jetons_sync(utilisateurs: list[str]) -> list[str]:
    return [a["jeton_fcm"] for a in db.client().table("appareils").select("jeton_fcm").in_("utilisateur_id", utilisateurs).execute().data or []]


def _supprimer_jetons_sync(jetons: list[str]) -> None:
    db.client().table("appareils").delete().in_("jeton_fcm", jetons).execute()


# -- API --------------------------------------------------------------------

async def notifier(destinataires: list[Optional[str]], annonce: Annonce, dossier_id: str) -> int:
    """Crée les notifications et envoie le push aux appareils connus. Retourne le nombre de destinataires."""
    global _table_absente_signalee
    uniques = sorted({d for d in destinataires if d})
    if not uniques:
        return 0
    lignes = [
        {"destinataire_id": d, "type": annonce.type, "titre": annonce.titre, "message": annonce.message,
         "lien": lien(annonce.role, dossier_id), "dossier_id": dossier_id}
        for d in uniques
    ]
    try:
        await db.executer(_inserer_sync, lignes)
    except Exception as exc:  # noqa: BLE001
        if db.est_erreur_schema(exc):
            if not _table_absente_signalee:
                log.warning("Table notifications absente (migration 014) — notifications non enregistrées")
                _table_absente_signalee = True
        else:
            log.error("Création des notifications échouée (%s)", type(exc).__name__)

    if push_fcm.est_configure():
        try:
            jetons = await db.executer(_jetons_sync, uniques)
            invalides = await push_fcm.envoyer(
                jetons, annonce.titre, annonce.message,
                {"type": annonce.type, "dossier_id": dossier_id, "lien": lien(annonce.role, dossier_id)},
            )
            if invalides:
                await db.executer(_supprimer_jetons_sync, invalides)
        except Exception as exc:  # noqa: BLE001
            log.error("Push des notifications échoué (%s)", type(exc).__name__)
    return len(uniques)


async def sur_transition(transition: Transition) -> None:
    dossier = transition.dossier or {}
    for annonce in annonces_pour_transition(transition):
        if annonce.role == "consultant":
            destinataires = await db.executer(_consultants_de_la_commune_sync, dossier.get("commune_id"))
        elif annonce.role == "admin":
            destinataires = await db.executer(_administrateurs_sync)
        else:
            destinataires = [dossier.get("citoyen_id")]
        destinataires = [d for d in destinataires if d and d != transition.acteur_id]
        await notifier(destinataires, annonce, transition.dossier_id)
