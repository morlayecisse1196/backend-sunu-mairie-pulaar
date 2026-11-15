"""
Vecteurs de recherche des fiches d'information (mode information, RAG).

Le mode information retrouve une fiche par SIMILARITÉ : la question du citoyen
et le nom de la démarche sont transformés en vecteurs, et comparés. Une fiche
ajoutée ou renommée sans passer par ce script reste donc invisible — la
recherche ne la trouvera jamais, sans qu'aucune erreur ne le signale.

À lancer après toute migration qui ajoute ou renomme une fiche :

    venv\\Scripts\\python.exe seed_embeddings.py          (Windows)
    ./venv/bin/python seed_embeddings.py                 (Linux, VPS)
    ./venv/Scripts/python.exe seed_embeddings.py --verifier   (sans rien écrire)

POURQUOI LE PYTHON DU VENV

`pgvector`, `psycopg` et `sentence-transformers` sont installés dans le venv
du projet, pas dans le Python du système. Lancé avec le mauvais interpréteur,
ce script échouait sur un `ModuleNotFoundError` brut, sans dire lequel utiliser.
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

from services.console import adoucir_sortie

MODELE = "paraphrase-multilingual-MiniLM-L12-v2"

COMMANDE_VENV = (
    r"venv\Scripts\python.exe seed_embeddings.py" if os.name == "nt"
    else "./venv/bin/python seed_embeddings.py"
)


def _sortir(message: str) -> None:
    print(message)
    raise SystemExit(1)


def _dependances():
    """Les modules lourds, importés seulement quand on en a besoin."""
    try:
        import psycopg
        from pgvector.psycopg import register_vector
        from sentence_transformers import SentenceTransformer
    except ModuleNotFoundError as exc:
        _sortir(
            f"Module manquant : {exc.name}.\n"
            f"Ce script demande les dependances du projet, installees dans le venv.\n"
            f"Lancez-le avec le Python du venv :\n\n    {COMMANDE_VENV}\n\n"
            f"Si le venv lui-meme ne les a pas : venv\\Scripts\\pip install -r requirements.txt"
        )
    return psycopg, register_vector, SentenceTransformer


def texte_a_vectoriser(nom: str | None, categorie: str | None) -> str:
    """Ce qui est comparé à la question du citoyen : le nom, puis la catégorie."""
    return " ".join(p.strip() for p in (nom or "", categorie or "") if p and p.strip())


def main(verifier: bool = False) -> int:
    adoucir_sortie()
    load_dotenv()

    url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL")
    if not url:
        _sortir(
            "DATABASE_URL absent du .env.\n"
            "Ce script se connecte directement a Postgres (pgvector) : l'URL de la base "
            "est indispensable, et ne doit jamais etre passee en argument de ligne de "
            "commande (elle resterait dans l'historique du terminal)."
        )

    psycopg, register_vector, SentenceTransformer = _dependances()

    try:
        connexion = psycopg.connect(url)
    except psycopg.OperationalError as exc:
        # Le cas réel : le mot de passe de la base a changé, le .env non.
        _sortir(
            f"Connexion a la base impossible ({type(exc).__name__}).\n"
            "Verifiez DATABASE_URL dans le .env du backend : le mot de passe de la base "
            "a-t-il change ?\n"
            "La recherche semantique du mode information utilise la MEME URL : si elle est "
            "fausse, l'agent repond avec la recherche par mots-cles, sans que rien ne le signale."
        )

    with connexion as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT d.id, d.nom_demarche, d.categorie, e.contenu
                FROM demarches d
                LEFT JOIN demarches_embeddings e ON e.demarche_id = d.id
                ORDER BY d.categorie, d.nom_demarche;
            """)
            lignes = cur.fetchall()

            manquantes = [(i, n, c) for i, n, c, contenu in lignes
                          if contenu != texte_a_vectoriser(n, c)]
            print(f"{len(lignes)} fiche(s), {len(manquantes)} a (re)vectoriser.")
            for _id, nom, categorie in manquantes:
                print(f"  - {nom} ({categorie})")

            if verifier:
                print("\nRien n'a ete ecrit (--verifier).")
                return 0
            if not manquantes:
                print("Tout est deja a jour : la recherche retrouve toutes les fiches.")
                return 0

            cur.execute("""
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'public.demarches_embeddings'::regclass
                  AND contype IN ('u', 'p')
                  AND conkey = (
                      SELECT array_agg(attnum) FROM pg_attribute
                      WHERE attrelid = 'public.demarches_embeddings'::regclass
                        AND attname = 'demarche_id');
            """)
            if not cur.fetchone():
                # Sans unicite, l'ecriture echoue sur « no unique or exclusion
                # constraint matching the ON CONFLICT specification » et AUCUN
                # vecteur n'est ecrit : la recherche ne trouve plus rien.
                _sortir(
                    "La table demarches_embeddings n'a pas de contrainte d'unicite sur "
                    "demarche_id : impossible de mettre les vecteurs a jour sans risquer des "
                    "doublons.\nAppliquez la migration 032, puis relancez ce script :\n\n"
                    "    venv\\Scripts\\python.exe scripts\\migrer.py"
                )

            # Le modèle pèse plusieurs centaines de Mo : chargé seulement s'il
            # y a vraiment quelque chose à vectoriser.
            print(f"\nChargement du modele {MODELE}...")
            modele = SentenceTransformer(MODELE)
            for demarche_id, nom, categorie in manquantes:
                contenu = texte_a_vectoriser(nom, categorie)
                cur.execute("""
                    INSERT INTO demarches_embeddings (demarche_id, contenu, embedding)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (demarche_id)
                    DO UPDATE SET embedding = EXCLUDED.embedding, contenu = EXCLUDED.contenu;
                """, (demarche_id, contenu, modele.encode(contenu).tolist()))
            conn.commit()

    print(f"\n{len(manquantes)} fiche(s) vectorisee(s). Le mode information les retrouve maintenant.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(verifier="--verifier" in sys.argv))
