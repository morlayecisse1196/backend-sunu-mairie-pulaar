# demarches_repo.py
# Accès en lecture à la table Supabase `demarches` pour les besoins du mobile
# (listing complet, détail par id, liste des communes couvertes) — distinct de
# search.py/search2.py qui servent le RAG conversationnel (recherche par similarité).
from supabase_client import get_supabase_client
from typing import List, Dict, Any, Optional


def list_communes() -> List[str]:
    """
    Liste triée des communes distinctes réellement présentes dans les données
    (utilisée pour peupler le sélecteur de commune à l'inscription mobile).
    Ne lève jamais d'exception : une liste vide en cas d'échec plutôt qu'un 500,
    l'inscription mobile a un repli statique dans ce cas.
    """
    try:
        supabase = get_supabase_client()
        response = supabase.table("demarches").select("commune").execute()
        communes = {row["commune"] for row in (response.data or []) if row.get("commune")}
        return sorted(communes)
    except Exception as e:
        print(f"⚠️ Impossible de récupérer la liste des communes ({e}).")
        return []


def list_demarches(commune: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Liste complète des démarches visibles pour une commune donnée : celles taguées
    pour cette commune + celles taguées "National" (qui concernent tout le monde).
    Si commune est None ou "National", retourne tout sans filtre.
    """
    supabase = get_supabase_client()
    builder = supabase.table("demarches").select("*")
    if commune and commune != "National":
        builder = builder.in_("commune", [commune, "National"])
    response = builder.order("categorie").execute()
    return response.data if response.data else []


def get_demarche_by_id(demarche_id: str) -> Optional[Dict[str, Any]]:
    """Une démarche précise par id, ou None si elle n'existe pas."""
    supabase = get_supabase_client()
    response = supabase.table("demarches").select("*").eq("id", demarche_id).limit(1).execute()
    if response.data:
        return response.data[0]
    return None
