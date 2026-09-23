import asyncio
import os
import time
from typing import Optional

import httpx
from fastapi import HTTPException, Header
from jose import jwt, JWTError

from supabase_client import get_supabase_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"

# Algorithmes ASYMÉTRIQUES uniquement (projet Supabase en "JWT Signing Keys",
# constaté : ES256). Correctif de sécurité (revue 2026-09-14) : l'algorithme
# était auparavant lu dans l'en-tête NON VÉRIFIÉ du jeton puis passé tel quel
# à jwt.decode — la liste des algorithmes acceptés doit toujours être fixée
# côté serveur, jamais choisie par le porteur du jeton (attaques de confusion
# d'algorithme, `alg: none`, HS256 signé avec la clé publique…).
ALGORITHMES_AUTORISES = frozenset({"ES256", "RS256", "EdDSA"})

# Un `kid` inconnu déclenche un rafraîchissement du JWKS (rotation de clé
# côté Supabase) — mais au plus une fois par intervalle : sans cette limite,
# n'importe qui pouvait forcer un appel réseau par requête en inventant des kid.
INTERVALLE_MIN_REFRESH_JWKS_SECONDES = 60.0

# Cinq secondes ne suffisaient pas sur une connexion lente : le JWKS expirait
# à presque tous les démarrages, et CHAQUE requête repartait alors vers
# Supabase Auth (~560 ms, cf. `verify_token`). Ce délai n'est payé qu'une
# fois, au premier jeton vérifié : ensuite le JWKS est en mémoire.
DELAI_JWKS_SECONDES = float(os.getenv("DELAI_JWKS_SECONDES", "20"))

_jwks_cache: dict = {}
_dernier_refresh: float = 0.0
_verrou_jwks = asyncio.Lock()


async def _recuperer_jwks(forcer_refresh: bool = False) -> dict:
    """JWKS du projet, mis en cache mémoire ; appel réseau NON bloquant pour l'event loop."""
    global _jwks_cache, _dernier_refresh
    if _jwks_cache and not forcer_refresh:
        return _jwks_cache
    async with _verrou_jwks:
        maintenant = time.monotonic()
        if _jwks_cache and (not forcer_refresh or maintenant - _dernier_refresh < INTERVALLE_MIN_REFRESH_JWKS_SECONDES):
            return _jwks_cache
        async with httpx.AsyncClient(timeout=DELAI_JWKS_SECONDES) as client:
            reponse = await client.get(JWKS_URL)
            reponse.raise_for_status()
        _jwks_cache = reponse.json()
        _dernier_refresh = time.monotonic()
        return _jwks_cache


async def prechauffer_jwks() -> bool:
    """
    Charge le JWKS au démarrage, pour que le premier citoyen ne paie pas
    l'attente. Un échec n'empêche jamais le serveur de démarrer : la
    vérification retombera sur Supabase Auth, plus lente mais correcte.
    """
    try:
        await _recuperer_jwks()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ JWKS non préchargé ({type(exc).__name__}) : les jetons seront "
              f"vérifiés par Supabase Auth, plus lentement.")
        return False


async def _cle_pour_kid(kid: str, forcer_refresh: bool = False) -> Optional[dict]:
    jwks = await _recuperer_jwks(forcer_refresh)
    for cle in jwks.get("keys", []):
        if cle.get("kid") == kid:
            return cle
    return None


def _refuser(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=f"Token invalide: {detail}")


async def verify_token(token: str) -> dict:
    """
    Vérifie le JWT Supabase EN LOCAL (clé publique du JWKS, < 1 ms une fois le
    cache rempli) — évite un aller-retour réseau vers Supabase Auth à chaque
    requête (~560 ms mesurés auparavant).

    Retourne `{sub, email, exp, role}`. `exp` (horodatage UNIX) permet au
    WebSocket v2 de savoir quand exiger un renouvellement du jeton.
    """
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as e:
        raise _refuser(str(e))

    alg = header.get("alg")
    kid = header.get("kid")
    if alg not in ALGORITHMES_AUTORISES:
        raise _refuser(f"algorithme non autorisé ({alg!r})")
    if not kid:
        raise _refuser("identifiant de clé (kid) absent")

    try:
        cle = await _cle_pour_kid(kid)
        if cle is None:
            cle = await _cle_pour_kid(kid, forcer_refresh=True)
        if cle is None:
            raise _refuser("clé de signature inconnue (JWKS)")
        if cle.get("alg") and cle["alg"] != alg:
            raise _refuser("algorithme incohérent avec la clé de signature")

        payload = jwt.decode(token, cle, algorithms=[alg], audience="authenticated")
    except JWTError as e:
        raise _refuser(str(e))
    except httpx.HTTPError as e:
        # JWKS injoignable (incident réseau ponctuel) : repli sur la
        # vérification distante par Supabase Auth, exécutée hors event loop.
        print(f"⚠️ JWKS injoignable ({type(e).__name__}), repli sur supabase.auth.get_user().")
        try:
            user = (await asyncio.to_thread(lambda: get_supabase_client().auth.get_user(token))).user
        except Exception as e2:
            raise _refuser(type(e2).__name__)
        return {"sub": user.id, "email": user.email, "exp": None, "role": "authenticated"}

    return {
        "sub": payload.get("sub"),
        "email": payload.get("email"),
        "exp": payload.get("exp"),
        "role": payload.get("role"),
    }


def _lire_profil_sync(user_id: str) -> dict:
    supabase = get_supabase_client()
    response = supabase.table("profiles").select("commune, role").eq("id", user_id).execute()
    if response.data:
        return response.data[0]
    return {"commune": "National", "role": "citoyen"}


async def get_user_profile(user_id: str) -> dict:
    """
    Commune et rôle de l'utilisateur (table profiles). Lecture exécutée hors
    event loop. En cas d'échec : rôle « citoyen » (moindre privilège, jamais
    un rôle élevé par défaut).
    """
    try:
        return await asyncio.to_thread(_lire_profil_sync, user_id)
    except Exception:
        return {"commune": "National", "role": "citoyen"}


async def _authentifier(authorization: Optional[str]) -> tuple:
    """Vérifie le token et retourne (user_id, profile)."""
    # En-tête absent : 401 (session à renouveler) plutôt que le 422 de
    # validation FastAPI, que le front web interpréterait comme une erreur de
    # requête au lieu d'une session expirée.
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentification requise")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Format Authorization invalide")
    token = authorization.split(" ", 1)[1]
    payload = await verify_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token invalide")
    profile = await get_user_profile(user_id)
    # L'e-mail vient du token, pas de `profiles` : c'est l'identité que le
    # journal d'audit doit conserver même si le compte est supprimé ensuite.
    return user_id, {**profile, "email": payload.get("email")}


async def get_current_consultant(authorization: Optional[str] = Header(None)) -> dict:
    """
    Exige role='consultant'. Le filtrage par commune sur les dossiers reste
    applicatif, endpoint par endpoint (cf. §5.6 du roadmap).
    """
    user_id, profile = await _authentifier(authorization)
    if profile.get("role") != "consultant":
        raise HTTPException(status_code=403, detail="Accès réservé aux consultants")
    return {
        "id": user_id,
        "commune": profile.get("commune", "National"),
        "role": "consultant",
        "email": profile.get("email"),
    }


async def get_current_admin(authorization: Optional[str] = Header(None)) -> dict:
    """Exige role='admin'."""
    user_id, profile = await _authentifier(authorization)
    if profile.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs")
    return {
        "id": user_id,
        "commune": profile.get("commune", "National"),
        "role": "admin",
        "email": profile.get("email"),
    }


async def get_current_profile(authorization: Optional[str] = Header(None)) -> dict:
    """Sans exigence de rôle — utilisé par /me (redirection web selon le rôle) et les routes communes."""
    user_id, profile = await _authentifier(authorization)
    return {
        "id": user_id,
        "role": profile.get("role", "citoyen"),
        "commune": profile.get("commune", "National"),
        "email": profile.get("email"),
    }


async def get_current_citoyen(authorization: Optional[str] = Header(None)) -> dict:
    """Tout utilisateur authentifié, vu comme citoyen (routes mobiles) — même forme que main.get_current_user."""
    user_id, profile = await _authentifier(authorization)
    return {"id": user_id, "commune": profile.get("commune", "National"), "role": profile.get("role", "citoyen")}
