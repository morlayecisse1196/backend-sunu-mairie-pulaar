"""
Contenu du mode information : ce que l'agent répond avant toute démarche
(plan maître, étape 5.6).

POURQUOI UN ÉCRAN

Ces fiches — documents à fournir, conditions, coût, délai, lieu — sont lues
par l'agent à chaque question de citoyen. Elles n'étaient modifiables que par
un accès direct à la base. Or ce sont précisément les informations qui
changent d'une mairie à l'autre et dans le temps : un tarif, un délai, un
bureau. Tant que personne ne peut les corriger depuis l'application, elles
vieillissent en silence et l'agent répond faux avec assurance.

CE QUI N'EST PAS MODIFIABLE ICI

Le nom et la catégorie. Ils servent à retrouver la fiche par la recherche
sémantique (`demarches_embeddings`) : les changer sans régénérer les vecteurs
rendrait la fiche introuvable, sans que rien ne le signale. Renommer une
démarche reste une opération de migration, suivie de `seed_embeddings.py`.
"""
from __future__ import annotations

from typing import Any

from services.journal import obtenir_logger
from supabase_client import get_supabase_client

log = obtenir_logger("informations")

TABLE = "demarches"

#: Les colonnes qu'un administrateur peut corriger depuis l'écran.
COLONNES_MODIFIABLES = (
    "documents_requis", "conditions", "cout", "delai", "lieu",
    "questions_agent", "alertes", "regles_speciales",
)

#: Listes de textes ; le reste est du texte simple.
COLONNES_LISTES = ("documents_requis", "conditions", "questions_agent", "alertes")

LONGUEUR_MAX = 2000


class ModificationRefusee(ValueError):
    """La modification ne peut pas être écrite telle quelle."""


def lister(commune: str | None = None) -> list[dict]:
    """Les fiches d'information, triées par catégorie puis par nom."""
    requete = get_supabase_client().table(TABLE).select("*")
    if commune and commune != "National":
        requete = requete.in_("commune", [commune, "National"])
    lignes = requete.execute().data or []
    return sorted(lignes, key=lambda l: ((l.get("categorie") or ""), (l.get("nom_demarche") or "")))


def _nettoyer(colonne: str, valeur: Any):
    if colonne in COLONNES_LISTES:
        if isinstance(valeur, str):
            valeur = [valeur]
        if not isinstance(valeur, list):
            raise ModificationRefusee(f"« {colonne} » attend une liste de phrases.")
        elements = [str(v).strip() for v in valeur if str(v).strip()]
        if any(len(e) > LONGUEUR_MAX for e in elements):
            raise ModificationRefusee(f"« {colonne} » : une entrée dépasse {LONGUEUR_MAX} caractères.")
        return elements
    if valeur is None:
        return None
    texte = str(valeur).strip()
    if len(texte) > LONGUEUR_MAX:
        raise ModificationRefusee(f"« {colonne} » dépasse {LONGUEUR_MAX} caractères.")
    # Un coût vidé vaut « non renseigné » : l'agent le dira au lieu d'inventer.
    return texte or None


def modifier(fiche_id: str, valeurs: dict, *, par: str | None = None) -> dict:
    """
    Corrige une fiche. Seules les colonnes de contenu sont acceptées.

    Un nom ou une catégorie glissés dans la demande sont REFUSÉS, pas
    ignorés : les accepter en silence laisserait croire au correcteur que son
    changement a été pris en compte.
    """
    inconnues = sorted(set(valeurs) - set(COLONNES_MODIFIABLES))
    if inconnues:
        raise ModificationRefusee(
            f"Champ(s) non modifiable(s) ici : {', '.join(inconnues)}. "
            f"Le nom et la catégorie servent à retrouver la fiche : les changer demande "
            f"une migration puis la régénération des vecteurs de recherche."
        )
    if not valeurs:
        raise ModificationRefusee("Aucune modification demandée.")

    a_ecrire = {colonne: _nettoyer(colonne, valeur) for colonne, valeur in valeurs.items()}
    client = get_supabase_client()
    reponse = client.table(TABLE).update(a_ecrire).eq("id", fiche_id).execute()
    if not reponse.data:
        raise ModificationRefusee(f"Fiche introuvable : {fiche_id}")
    log.info("Fiche d'information %s corrigée par %s : %s",
             fiche_id, par or "inconnu", ", ".join(sorted(a_ecrire)))
    return reponse.data[0]
