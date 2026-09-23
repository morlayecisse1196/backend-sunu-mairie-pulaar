"""
État d'une session de dialogue — représentation unique, sérialisable.

Le moteur manipule un `dict` (même contrat que l'ancien
`dossier_sessions[session_id]` de main.py), ce qui garde `slot_controller`
inchangé : il lit/écrit `slots`, `dossier_id`, `type_demarche`,
`compteurs_echecs`, `dernieres_raisons`, `documents_ignores` (set),
`documents_demandes` (set), `dernieres_reponses`, `compteurs_variation`.

Ce module garantit que cet état fait l'aller-retour vers la base
(`dialogue_sessions`, migration 013) sans perte : ensembles ↔ listes triées,
clés inconnues tolérées, clés manquantes complétées par défaut (une session
enregistrée par une version antérieure reste relisible).
"""
from __future__ import annotations

import copy
from typing import Any

from services import demarche

# Les slots initiaux se déduisent désormais des champs déclarés de la démarche
# (`services/demarche.slots_vides`, étape 2.3) : ajouter une question ne demande
# plus de penser à compléter une constante ici.
#
# `SLOTS_VIDES_EXTRAIT_NAISSANCE` reste exporté pour les scripts de
# vérification manuelle de la racine, qui l'importent — mais il est calculé à
# la PREMIÈRE LECTURE, pas à l'import : lire la base au chargement d'un module
# ferait dépendre le démarrage du serveur de la disponibilité de Supabase.
def __getattr__(nom: str):
    if nom == "SLOTS_VIDES_EXTRAIT_NAISSANCE":
        return demarche.slots_vides()
    raise AttributeError(nom)

MODES = ("information", "administratif")
PHASES = ("collecte", "relecture_en_cours", "termine", "bloque")
HISTORIQUE_MAX_ENTREES = 12

_CHAMPS_ENSEMBLES = ("documents_demandes", "documents_ignores")
_CHAMPS_DICTS = ("compteurs_echecs", "dernieres_raisons", "dernieres_reponses", "compteurs_variation")

# Colonnes dédiées de `dialogue_sessions` (le reste va dans la colonne JSON `etat`).
_COLONNES = ("id", "cle_client", "citoyen_id", "conversation_id", "dossier_id", "type_demarche", "mode", "phase", "statut")


def nouvel_etat(*, session_id: str, cle_client: str, citoyen_id: str, commune_profil: str) -> dict:
    return {
        "id": session_id,
        "cle_client": cle_client,
        "citoyen_id": citoyen_id,
        "commune_profil": commune_profil or "National",
        "conversation_id": None,
        "dossier_id": None,
        "type_demarche": demarche.TYPE_DEMARCHE_PAR_DEFAUT,
        # Figée au passage en mode administratif, pas ici : tant que le citoyen
        # s'informe, rien ne l'engage (étape 2.4).
        "demarche_version": None,
        "mode": "information",
        "phase": "collecte",
        "statut": "active",
        "numero_suivi": None,
        "cas_legal": None,
        "slots": demarche.slots_vides(demarche.TYPE_DEMARCHE_PAR_DEFAUT),
        "commune_id_resolue": False,
        "dernier_tour_propose_demarche": False,
        # La démarche que le tour précédent proposait de commencer : au tour
        # suivant, le citoyen dit « oui » et plus rien ne dit laquelle.
        "demarche_proposee": None,
        "nb_iterations_correction": 0,
        "document_en_attente": None,
        "correction_attendue": False,
        "historique": [],
        **{nom: set() for nom in _CHAMPS_ENSEMBLES},
        **{nom: {} for nom in _CHAMPS_DICTS},
    }


def serialiser(etat: dict) -> dict:
    """Ligne `dialogue_sessions` prête à l'écriture (JSON pur, aucun set)."""
    contenu: dict[str, Any] = {}
    for cle, valeur in etat.items():
        if cle in _COLONNES:
            continue
        if isinstance(valeur, set):
            contenu[cle] = sorted(valeur)
        else:
            contenu[cle] = copy.deepcopy(valeur)
    ligne = {cle: etat.get(cle) for cle in _COLONNES}
    ligne["etat"] = contenu
    return ligne


def deserialiser(ligne: dict, *, commune_profil: str | None = None) -> dict:
    """Reconstruit l'état complet depuis une ligne `dialogue_sessions`."""
    etat = nouvel_etat(
        session_id=ligne["id"],
        cle_client=ligne.get("cle_client") or ligne["id"],
        citoyen_id=ligne["citoyen_id"],
        commune_profil=commune_profil or (ligne.get("etat") or {}).get("commune_profil") or "National",
    )
    slots_enregistres: dict | None = None
    for cle, valeur in (ligne.get("etat") or {}).items():
        if cle in _CHAMPS_ENSEMBLES:
            etat[cle] = set(valeur or [])
        elif cle == "slots":
            slots_enregistres = valeur or {}
        else:
            etat[cle] = valeur
    for cle in _COLONNES:
        if ligne.get(cle) is not None:
            etat[cle] = ligne[cle]

    # Les slots sont complétés APRÈS la boucle, pour que `type_demarche` et
    # `demarche_version` soient connus : une session commencée sous une
    # version antérieure doit retrouver les champs de SA version, pas ceux
    # d'une question ajoutée depuis (étape 2.4). Une session enregistrée
    # avant le versionnement n'a pas de version — elle repart du vivant,
    # comme avant.
    etat["slots"] = {
        **demarche.slots_vides(
            etat.get("type_demarche") or demarche.TYPE_DEMARCHE_PAR_DEFAUT,
            etat.get("demarche_version"),
        ),
        **(slots_enregistres or {}),
    }
    if commune_profil:
        etat["commune_profil"] = commune_profil
    if etat["mode"] not in MODES:
        etat["mode"] = "information"
    if etat["phase"] not in PHASES:
        etat["phase"] = "collecte"
    return etat


def ajouter_historique(etat: dict, role: str, contenu: str) -> None:
    """Conserve les derniers échanges pour le contexte du modèle (jamais plus de HISTORIQUE_MAX_ENTREES)."""
    if not contenu:
        return
    etat.setdefault("historique", []).append({"role": role, "content": contenu})
    if len(etat["historique"]) > HISTORIQUE_MAX_ENTREES:
        etat["historique"] = etat["historique"][-HISTORIQUE_MAX_ENTREES:]


def instantane_client(etat: dict) -> dict:
    """Ce que le client a le droit de savoir de sa session (message `session` du protocole)."""
    return {
        "session_id": etat["id"],
        "conversation_id": etat.get("conversation_id"),
        "mode": etat["mode"],
        "phase": etat["phase"],
        "statut": etat["statut"],
        "dossier_id": etat.get("dossier_id"),
        "numero_suivi": etat.get("numero_suivi"),
        "document_attendu": etat.get("document_en_attente"),
        "type_demarche": etat.get("type_demarche"),
    }
