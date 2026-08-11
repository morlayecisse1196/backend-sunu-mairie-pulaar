import os
import psycopg
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

load_dotenv()

# 1. Connexion à la base
database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise ValueError("DATABASE_URL non défini")

conn = psycopg.connect(database_url)
register_vector(conn)
cur = conn.cursor()

# 2. Charger le modèle d'embeddings
model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

# 3. Récupérer toutes les démarches
cur.execute("SELECT id, nom_demarche, categorie FROM demarches;")
rows = cur.fetchall()

for demarche_id, nom, categorie in rows:
    texte_a_vectoriser = f"{nom} {categorie}"
    embedding = model.encode(texte_a_vectoriser).tolist()
    
    cur.execute("""
        INSERT INTO demarches_embeddings (demarche_id, contenu, embedding)
        VALUES (%s, %s, %s)
        ON CONFLICT (demarche_id) 
        DO UPDATE SET embedding = EXCLUDED.embedding, contenu = EXCLUDED.contenu;
    """, (demarche_id, texte_a_vectoriser, embedding))

conn.commit()
print("✅ Embeddings générés avec succès !")
cur.close()
conn.close()