import os
import psycopg
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

# 1. Connexion à Supabase
conn = psycopg.connect(os.getenv("SUPABASE_URL"))
register_vector(conn)
cur = conn.cursor()

# 2. Charger le modèle d'embeddings
model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

# 3. Récupérer toutes les démarches existantes
cur.execute("SELECT id, nom_demarche, categorie FROM demarches;")
rows = cur.fetchall()

for demarche_id, nom, categorie in rows:
    # 4. Créer le texte à vectoriser
    texte_a_vectoriser = f"{nom} {categorie}"
    
    # 5. Générer l'embedding (vecteur de 384 dimensions)
    embedding = model.encode(texte_a_vectoriser).tolist()
    
    # 6. Insérer ou mettre à jour dans la table demarches_embeddings
    cur.execute("""
        INSERT INTO demarches_embeddings (demarche_id, contenu, embedding)
        VALUES (%s, %s, %s)
        ON CONFLICT (demarche_id) 
        DO UPDATE SET embedding = EXCLUDED.embedding, contenu = EXCLUDED.contenu;
    """, (demarche_id, texte_a_vectoriser, embedding))

conn.commit()
print("✅ Embeddings générés avec succès !")