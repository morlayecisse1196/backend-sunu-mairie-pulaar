"""
Seed de la table `communes` — Sprint A, Tâche A.2 (MEMOIR2/SUNU_MAIRIE_PROMPTS.md).

Utilise le client REST Supabase (supabase_client.py), pas une connexion directe
psycopg comme seed_embeddings.py : DATABASE_URL pointe vers un hôte IPv6 souvent
injoignable en dev local (même problème déjà documenté dans main.py,
search_demarches()). La table `communes` n'a pas besoin de pgvector, donc rien
n'oblige à passer par la connexion directe ici — le REST client suffit et évite
ce point de friction connu.

Deux sources, traitées différemment :

1. Communes avec métadonnées administratives CONFIRMÉES (région/département/
   arrondissement), reprises telles quelles des exemples XML fournis dans
   README-MISE-A-JOUR-APP/ (extrait_naissance_exemple_ordinaire.xml et
   extrait_naissance_exemple_suppletif.xml) : Ross-Béthio et Dindéfélo.

2. Communes déjà utilisées dans `demarches.commune` (RAG informationnel
   existant, ex. "Dakar") mais dont on n'a AUCUNE source fiable pour
   région/département/arrondissement dans ce projet. Par prudence — même
   principe que pour la phonétique pulaar (ANCIEN_CODE_HF_SPACE/service_tts.py) —
   on n'invente pas ces valeurs administratives. Elles sont insérées avec
   région/département/arrondissement à NULL et un avertissement est affiché ;
   à compléter manuellement via l'interface admin (Sprint G, Tâche G.1) ou une
   future mise à jour de ce script.

"National" n'est PAS une commune réelle : c'est une valeur-sentinelle utilisée
par le RAG informationnel (demarches.commune, profiles.commune) pour signifier
"s'applique à tout le monde" (cf. search.py, demarches_repo.py). Un dossier
administratif (table `dossiers`) est toujours déposé dans une mairie précise,
donc "National" est explicitement exclu de la table `communes`.
"""
import sys
from dotenv import load_dotenv

# Évite un crash sur les emoji des print() ci-dessous quand la console Windows
# est en cp1252 (terminal par défaut hors Windows Terminal/UTF-8).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

from supabase_client import get_supabase_client
from demarches_repo import list_communes

# ----------------------------------------------------------------------------
# 1. Communes avec métadonnées confirmées (source : XML d'exemple fournis)
# ----------------------------------------------------------------------------
COMMUNES_CONFIRMEES = [
    {
        "nom": "Ross-Béthio",
        "region": "Saint-Louis",
        "departement": "Dagana",
        "arrondissement": "Ndiaye",
    },
    {
        "nom": "Dindéfélo",
        "region": "Kédougou",
        "departement": "Kédougou",
        "arrondissement": "Bandafassi",
    },
]

# Valeur-sentinelle du RAG informationnel, à ne jamais traiter comme une commune.
COMMUNE_SENTINELLE_A_EXCLURE = "National"


def main():
    supabase = get_supabase_client()

    # --- 1. Communes à métadonnées confirmées -------------------------------
    supabase.table("communes").upsert(
        COMMUNES_CONFIRMEES, on_conflict="nom"
    ).execute()
    for c in COMMUNES_CONFIRMEES:
        print(f"✅ Commune confirmée insérée/mise à jour : {c['nom']}")

    # --- 2. Communes découvertes dans demarches.commune ----------------------
    communes_demarches = set(list_communes())
    communes_demarches.discard(COMMUNE_SENTINELLE_A_EXCLURE)

    noms_confirmes = {c["nom"] for c in COMMUNES_CONFIRMEES}
    a_completer = sorted(communes_demarches - noms_confirmes)

    if a_completer:
        payload = [
            {"nom": nom, "region": None, "departement": None, "arrondissement": None}
            for nom in a_completer
        ]
        # ignore_duplicates=True : ne pas écraser des métadonnées déjà saisies
        # manuellement (ex. via l'admin) pour une commune qui existerait déjà.
        supabase.table("communes").upsert(
            payload, on_conflict="nom", ignore_duplicates=True
        ).execute()

    print(f"✅ {len(COMMUNES_CONFIRMEES)} commune(s) confirmée(s) traitée(s).")
    if a_completer:
        print(
            f"⚠️  {len(a_completer)} commune(s) insérée(s) SANS région/département/"
            f"arrondissement (métadonnées non disponibles dans ce projet) : "
            f"{', '.join(a_completer)}. À compléter manuellement (Sprint G, "
            f"interface admin) avant de s'appuyer dessus pour l'en-tête "
            f"administratif d'un document généré."
        )
    print("✅ Seed communes terminé.")


if __name__ == "__main__":
    main()
