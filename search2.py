import os
import psycopg
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Any, Optional

# Charger le modèle une fois au démarrage
model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

# Seuil de similarité cosinus en dessous duquel un résultat est considéré
# comme non pertinent (évite de répondre avec une démarche sans rapport).
SIMILARITY_THRESHOLD = 0.35

def get_db_connection():
    """Établit une connexion directe à la base PostgreSQL."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL non défini dans le fichier .env")

    conn = psycopg.connect(database_url)
    register_vector(conn)  # Active le support des vecteurs
    return conn

def search_demarches(query: str, commune: Optional[str] = None, limit: int = 3) -> List[Dict[str, Any]]:
    """
    Recherche sémantique avec pgvector (embeddings), avec filtrage optionnel par commune.
    Ne retourne que les résultats dont la similarité dépasse SIMILARITY_THRESHOLD.
    """
    # 1. Générer l'embedding de la question
    query_embedding = model.encode(query).tolist()

    conn = get_db_connection()
    cur = conn.cursor()

    filtre_commune = ""
    params = [query_embedding]
    if commune and commune != "National":
        # Une démarche "National" concerne tout le monde : on l'inclut toujours
        # en plus de la commune de l'utilisateur (voir même correction dans search.py).
        filtre_commune = "WHERE d.commune IN (%s, 'National')"
        params.append(commune)

    params.extend([query_embedding, limit])

    cur.execute(f"""
        SELECT
            d.id,
            d.categorie,
            d.nom_demarche,
            d.documents_requis,
            d.conditions,
            d.cout,
            d.delai,
            d.lieu,
            d.questions_agent,
            d.alertes,
            d.regles_speciales,
            (1 - (de.embedding <=> %s::vector)) as similarite
        FROM demarches_embeddings de
        JOIN demarches d ON de.demarche_id = d.id
        {filtre_commune}
        ORDER BY de.embedding <=> %s::vector
        LIMIT %s;
    """, params)

    results = cur.fetchall()
    cur.close()
    conn.close()

    if not results:
        return []

    columns = ['id', 'categorie', 'nom_demarche', 'documents_requis',
               'conditions', 'cout', 'delai', 'lieu', 'questions_agent',
               'alertes', 'regles_speciales', 'similarite']

    demarches = [dict(zip(columns, row)) for row in results]
    return [d for d in demarches if d.get('similarite', 0) >= SIMILARITY_THRESHOLD]

def format_demarche_pour_prompt(demarche: Dict[str, Any]) -> str:
    # Identique à la version précédente
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