import os
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# `SUPABASE_JWT_SECRET` était lu ici et utilisé NULLE PART ailleurs : depuis la
# revue de sécurité du 2026-09-14, `auth.py` n'accepte que des signatures
# ASYMÉTRIQUES vérifiées contre le JWKS du projet (ES256/RS256/EdDSA), jamais
# HS256. Garder le secret partagé en mémoire du processus n'apportait donc
# aucune fonctionnalité, seulement une surface d'exposition (journaux, dumps,
# messages d'erreur) et la tentation de réintroduire une vérification
# symétrique — exactement l'attaque de confusion d'algorithme que la revue a
# fermée. La variable peut rester dans `.env`, elle n'est plus chargée.

# --- Origines autorisées pour CORS ---------------------------------------
#
# Il y a maintenant DEUX fronts web distincts : l'espace consultant/admin et
# (à venir) l'espace citoyen, qui ne tourneront pas sur la même origine. Or
# `allow_origins` ne recevait qu'une seule valeur : la deuxième origine se
# faisait refuser en 400 au preflight, sans message utile côté navigateur
# (vérifié : preflight depuis localhost:3001 → 400 Bad Request).
#
# `FRONTEND_URLS` (ou `FRONTEND_URL`, conservé pour ne pas casser les `.env`
# existants) accepte donc une liste séparée par des virgules :
#
#   FRONTEND_URLS=https://agents.exemple.sn,https://citoyen.exemple.sn
#
# Les origines restent TOUJOURS énumérées explicitement, jamais `*` : le
# middleware envoie `allow_credentials=True`, et la combinaison `*` +
# credentials est refusée par les navigateurs — un `*` ici donnerait un CORS
# qui « marche » en test et casse dès qu'un jeton circule.

# Les deux ports de dev Next.js les plus courants, en `localhost` et en
# `127.0.0.1` : ce sont deux origines différentes pour un navigateur, et ouvrir
# le front par l'une puis l'autre est le genre d'erreur qui coûte une heure.
ORIGINES_DEV_PAR_DEFAUT = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
)


def _lire_origines_cors() -> list[str]:
    brut = os.getenv("FRONTEND_URLS") or os.getenv("FRONTEND_URL") or ""
    # Une barre oblique finale fait une origine différente de celle que le
    # navigateur envoie dans l'en-tête `Origin` : elle est retirée ici plutôt
    # que de laisser un déploiement échouer sur un caractère.
    origines = [morceau.strip().rstrip("/") for morceau in brut.split(",")]
    origines = [origine for origine in origines if origine]

    if not origines:
        return list(ORIGINES_DEV_PAR_DEFAUT)

    # En production on ne veut QUE les origines déclarées. Mais tant que la
    # liste ne contient que du localhost, on est en développement : on ajoute
    # les autres ports de dev, sinon poser `FRONTEND_URL=http://localhost:3000`
    # dans `.env` rebloquerait silencieusement le second front.
    def est_local(origine: str) -> bool:
        return "localhost" in origine or "127.0.0.1" in origine

    if all(est_local(origine) for origine in origines):
        for defaut in ORIGINES_DEV_PAR_DEFAUT:
            if defaut not in origines:
                origines.append(defaut)

    return origines


ORIGINES_CORS = _lire_origines_cors()

# Conservé pour compatibilité : première origine déclarée, utile pour
# construire un lien absolu vers le front (courriels, redirections).
FRONTEND_URL = ORIGINES_CORS[0]
