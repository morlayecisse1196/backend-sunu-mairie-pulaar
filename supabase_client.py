import os
from dotenv import load_dotenv
from supabase import create_client, Client

# Charger le .env ICI, et pas seulement dans config.py : ces deux constantes
# sont lues à l'IMPORT du module, si bien que tout dépendait de l'ordre des
# imports. `main.py` importe `config` en premier, donc le serveur marchait ;
# un script qui importe un repo sans passer par `config` héritait d'un
# SUPABASE_URL vide et échouait sur « supabase_url is required », loin de la
# cause. `load_dotenv` n'écrase jamais une variable déjà posée dans
# l'environnement : la configuration d'un vrai déploiement reste prioritaire.
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Singleton — mesuré empiriquement à ~600ms par appel à create_client() (setup
# de connexion), contre ~0ms en réutilisant la même instance. Avant ce
# correctif, chaque fonction repo (dossiers_repo.py, admin_repo.py, etc.)
# appelait get_supabase_client() séparément, donc un seul clic consultant
# (ex. ouvrir un dossier = auth + profil + dossier + commune + documents + N
# formulaires) recréait le client 5 à 10 fois — la cause principale de la
# lenteur perçue côté web (cf. diagnostic Tâche F.3→F.4). Le client
# supabase-py est thread-safe pour un usage en lecture/écriture de ce type.
_client: Client | None = None


def get_supabase_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client