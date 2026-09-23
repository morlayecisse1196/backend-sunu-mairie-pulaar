"""
Profil complet de l'agent connecté (consultant ou admin) : identité, commune,
préférences, drapeau de mot de passe temporaire, dernière connexion.

Deux sources : la table `profiles` (migration 012) et Supabase Auth
(`last_sign_in_at`, `user_metadata`, `app_metadata`). Les métadonnées Auth ne
servent que de REPLI : le web les écrit déjà lui-même, et un profil dont la
migration n'est pas appliquée doit rester lisible.
"""
from __future__ import annotations

from typing import Optional

from dossiers_repo import resoudre_commune_id
from services import db
from services.journal import obtenir_logger

log = obtenir_logger("profil")

MIGRATION_PROFILS = "012"
CHAMPS_IDENTITE = ("nom_complet", "telephone", "fonction")
PREFERENCES_PAR_DEFAUT = {"theme": "system", "notifications_email": True}
THEMES = ("light", "dark", "system")


def _ligne_profil(user_id: str) -> dict:
    try:
        lignes = db.client().table("profiles").select("*").eq("id", user_id).limit(1).execute().data
        return lignes[0] if lignes else {}
    except Exception as exc:  # noqa: BLE001
        log.warning("Lecture du profil %s échouée (%s)", user_id, type(exc).__name__)
        return {}


def _utilisateur_auth(user_id: str):
    try:
        return db.client().auth.admin.get_user_by_id(user_id).user
    except Exception as exc:  # noqa: BLE001
        log.warning("Lecture Auth de %s échouée (%s)", user_id, type(exc).__name__)
        return None


def _horodatage(valeur) -> Optional[str]:
    if valeur is None:
        return None
    return valeur.isoformat() if hasattr(valeur, "isoformat") else str(valeur)


def _assembler(user_id: str, role: str, commune: str, email: Optional[str]) -> dict:
    ligne = _ligne_profil(user_id)
    utilisateur = _utilisateur_auth(user_id)
    meta = dict(getattr(utilisateur, "user_metadata", None) or {})
    app_meta = dict(getattr(utilisateur, "app_metadata", None) or {})
    derniere_connexion = _horodatage(getattr(utilisateur, "last_sign_in_at", None))

    preferences = {**PREFERENCES_PAR_DEFAUT, **(ligne.get("preferences") or {})}
    profil = {
        "id": user_id,
        "role": ligne.get("role") or role,
        "commune": ligne.get("commune") or commune,
        "commune_id": None,
        "email": email or getattr(utilisateur, "email", None),
        "nom_complet": ligne.get("nom_complet") or meta.get("full_name") or meta.get("nom_complet"),
        "telephone": ligne.get("telephone") or meta.get("telephone"),
        "fonction": ligne.get("fonction") or meta.get("fonction"),
        "doit_changer_mot_de_passe": bool(
            ligne.get("doit_changer_mot_de_passe")
            if ligne.get("doit_changer_mot_de_passe") is not None
            else app_meta.get("must_change_password", False)
        ),
        "derniere_connexion": derniere_connexion,
        "preferences": preferences,
    }
    try:
        profil["commune_id"] = resoudre_commune_id(profil["commune"])
    except Exception:  # noqa: BLE001 — commune_id reste null pour un admin national
        pass

    # Première requête depuis une nouvelle connexion : on le repère en comparant
    # `last_sign_in_at` à la dernière valeur vue, ce qui évite un hook Auth.
    profil["_connexion_nouvelle"] = bool(
        derniere_connexion and ligne and ligne.get("derniere_connexion_vue") != derniere_connexion
    )
    profil["_derniere_connexion_vue"] = derniere_connexion
    return profil


def _marquer_connexion_vue(user_id: str, horodatage: Optional[str]) -> None:
    try:
        db.client().table("profiles").update({"derniere_connexion_vue": horodatage}).eq("id", user_id).execute()
    except Exception as exc:  # noqa: BLE001 — migration 012 absente : rien à mémoriser
        if not db.est_erreur_schema(exc):
            log.warning("Mémorisation de la connexion échouée (%s)", type(exc).__name__)


async def lire(user_id: str, role: str, commune: str, email: Optional[str] = None) -> dict:
    """Profil complet, sans jamais échouer sur une base dont la migration 012 manque."""
    profil = await db.executer(_assembler, user_id, role, commune, email)
    nouvelle = profil.pop("_connexion_nouvelle", False)
    vue = profil.pop("_derniere_connexion_vue", None)
    if nouvelle:
        from services import audit  # import tardif : audit n'a pas besoin de profil

        await db.executer(_marquer_connexion_vue, user_id, vue)
        await audit.journaliser(
            "connexion",
            acteur={"id": user_id, "email": profil.get("email"), "role": profil.get("role")},
            cible_type="compte",
            cible_id=user_id,
        )
    return profil


async def mettre_a_jour_identite(user_id: str, champs: dict) -> None:
    """
    Écrit dans `profiles` ET dans `user_metadata` : le web lit le repli des
    métadonnées quand la migration 012 n'est pas appliquée.
    """
    def _ecrire():
        erreur_profil = None
        try:
            db.client().table("profiles").update(champs).eq("id", user_id).execute()
        except Exception as exc:  # noqa: BLE001
            if not db.est_erreur_schema(exc):
                raise
            erreur_profil = exc
        metadonnees = {("full_name" if cle == "nom_complet" else cle): valeur for cle, valeur in champs.items()}
        try:
            db.client().auth.admin.update_user_by_id(user_id, {"user_metadata": metadonnees})
        except Exception as exc:  # noqa: BLE001
            if erreur_profil is not None:
                raise db.migration_manquante(MIGRATION_PROFILS, "La modification du profil")
            log.warning("Métadonnées Auth non mises à jour (%s)", type(exc).__name__)

    await db.executer(_ecrire)


async def fusionner_preferences(user_id: str, preferences: dict) -> dict:
    def _ecrire():
        ligne = _ligne_profil(user_id)
        fusionnees = {**PREFERENCES_PAR_DEFAUT, **(ligne.get("preferences") or {}), **preferences}
        try:
            db.client().table("profiles").update({"preferences": fusionnees}).eq("id", user_id).execute()
        except Exception as exc:  # noqa: BLE001
            if db.est_erreur_schema(exc):
                raise db.migration_manquante(MIGRATION_PROFILS, "Les préférences")
            raise
        return fusionnees

    return await db.executer(_ecrire)


async def marquer_mot_de_passe_modifie(user_id: str) -> None:
    """Le mot de passe temporaire a été remplacé : on lève le drapeau des deux côtés."""
    def _ecrire():
        try:
            db.client().auth.admin.update_user_by_id(user_id, {"app_metadata": {"must_change_password": False}})
        except Exception as exc:  # noqa: BLE001
            log.warning("Drapeau Auth non levé pour %s (%s)", user_id, type(exc).__name__)
        try:
            db.client().table("profiles").update({"doit_changer_mot_de_passe": False}).eq("id", user_id).execute()
        except Exception as exc:  # noqa: BLE001
            if not db.est_erreur_schema(exc):
                log.warning("Drapeau profil non levé pour %s (%s)", user_id, type(exc).__name__)

    await db.executer(_ecrire)
