from supabase_client import get_supabase_client
from typing import List, Dict, Any, Optional
import re

STOPWORDS = {
    'je', 'tu', 'il', 'elle', 'on', 'nous', 'vous', 'ils', 'elles',
    'le', 'la', 'les', 'un', 'une', 'des', 'du', 'de', 'pour',
    'avec', 'sans', 'par', 'dans', 'sur', 'sous', 'entre',
    'et', 'ou', 'mais', 'donc', 'car', 'ni',
    'que', 'qui', 'quoi', 'dont', 'où',
    'est', 'ce', 'ça', 'cela',
    'faire', 'veux', 'vais', 'aller', 'avoir', 'être', 'suis',
    'moi', 'toi', 'lui', 'eux',
    'si', 'alors', 'quand', 'comment', 'pourquoi', 'combien',
    'est-ce', 'que', 'qu\'', 'qu'
}

def search_demarches(query: str, commune: Optional[str] = None, limit: int = 3) -> List[Dict[str, Any]]:
    """
    Recherche les démarches correspondant à la question du citoyen,
    avec possibilité de filtrer par commune.
    """
    supabase = get_supabase_client()
    words = re.findall(r'\b\w+\b', query.lower())
    keywords = [w for w in words if len(w) >= 3 and w not in STOPWORDS]
    
    # Construction de la requête de base
    builder = supabase.table("demarches").select("*")
    
    # Filtrage par commune : une démarche "National" concerne tout le monde,
    # donc on inclut toujours National en plus de la commune de l'utilisateur
    # (un simple .eq() exclurait à tort les démarches nationales).
    if commune and commune != "National":
        builder = builder.in_("commune", [commune, "National"])
    
    if not keywords:
        response = builder.limit(limit).execute()
        return response.data if response.data else []
    
    # Construction de la condition OR pour les mots-clés
    conditions = []
    for kw in keywords[:5]:
        conditions.append(f"nom_demarche.ilike.%{kw}%")
        conditions.append(f"categorie.ilike.%{kw}%")
    or_condition = ",".join(conditions)
    
    response = builder.or_(or_condition).limit(limit).execute()
    return response.data if response.data else []

def format_demarche_pour_prompt(demarche: Dict[str, Any]) -> str:
    return f"""
Nom de la démarche : {demarche.get('nom_demarche', '')}
Catégorie : {demarche.get('categorie', '')}
Documents requis : {', '.join(demarche.get('documents_requis', []))}
Conditions : {', '.join(demarche.get('conditions', []))}
Coût : {demarche.get('cout', '')}
Délai : {demarche.get('delai', '')}
Lieu : {demarche.get('lieu', '')}
Questions à poser au citoyen : {', '.join(demarche.get('questions_agent', []))}
Alertes importantes : {', '.join(demarche.get('alertes', []))}
Règles spéciales : {demarche.get('regles_speciales', '')}
"""