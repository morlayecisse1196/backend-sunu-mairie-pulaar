import json

import httpx
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from jose import jwk, jwt

import auth

KID = "cle-test-1"


@pytest.fixture
def cle_ec():
    privee = ec.generate_private_key(ec.SECP256R1())
    pem = privee.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    publique = jwk.construct(pem, algorithm="ES256").public_key().to_dict()
    publique.update({"kid": KID, "alg": "ES256", "use": "sig"})
    return pem, publique


@pytest.fixture
def jwks_simule(monkeypatch, cle_ec):
    _, publique = cle_ec
    appels = {"n": 0, "forces": 0}

    async def faux_recuperer(forcer_refresh: bool = False):
        appels["n"] += 1
        if forcer_refresh:
            appels["forces"] += 1
        return {"keys": [publique]}

    monkeypatch.setattr(auth, "_recuperer_jwks", faux_recuperer)
    return appels


def _claims(**extra):
    maintenant = int(time.time())
    base = {"sub": "user-1", "email": "a@b.sn", "aud": "authenticated", "role": "authenticated", "exp": maintenant + 3600}
    base.update(extra)
    return base


async def test_jeton_es256_valide_expose_exp(cle_ec, jwks_simule):
    pem, _ = cle_ec
    token = jwt.encode(_claims(), pem, algorithm="ES256", headers={"kid": KID})
    resultat = await auth.verify_token(token)
    assert resultat["sub"] == "user-1"
    assert isinstance(resultat["exp"], int)


async def test_hs256_signe_avec_la_cle_publique_est_refuse(cle_ec, jwks_simule):
    _, publique = cle_ec
    token = jwt.encode(_claims(), json.dumps(publique), algorithm="HS256", headers={"kid": KID})
    with pytest.raises(HTTPException) as exc:
        await auth.verify_token(token)
    assert exc.value.status_code == 401
    assert "algorithme non autorisé" in exc.value.detail


async def test_jeton_expire_refuse(cle_ec, jwks_simule):
    pem, _ = cle_ec
    token = jwt.encode(_claims(exp=int(time.time()) - 10), pem, algorithm="ES256", headers={"kid": KID})
    with pytest.raises(HTTPException):
        await auth.verify_token(token)


async def test_kid_inconnu_refuse(cle_ec, jwks_simule):
    pem, _ = cle_ec
    token = jwt.encode(_claims(), pem, algorithm="ES256", headers={"kid": "inconnu"})
    with pytest.raises(HTTPException) as exc:
        await auth.verify_token(token)
    assert "clé de signature inconnue" in exc.value.detail


async def test_refresh_force_du_jwks_est_limite_dans_le_temps(monkeypatch):
    appels = {"reseau": 0}

    class FausseReponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"keys": []}

    class FauxClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            appels["reseau"] += 1
            return FausseReponse()

    monkeypatch.setattr(auth.httpx, "AsyncClient", FauxClient)
    monkeypatch.setattr(auth, "_jwks_cache", {})
    monkeypatch.setattr(auth, "_dernier_refresh", 0.0)

    await auth._recuperer_jwks()
    for _ in range(20):
        await auth._recuperer_jwks(forcer_refresh=True)
    # Premier chargement + aucun refresh forcé supplémentaire dans la fenêtre de 60 s.
    assert appels["reseau"] == 1


# ============================================================================
# Préchargement des clés au démarrage
# ============================================================================


async def test_le_prechauffage_remplit_le_cache(monkeypatch, cle_ec):
    # Sans lui, le premier citoyen paie l'attente réseau ; sur une connexion
    # lente, la vérification échoue et repart vers Supabase Auth à CHAQUE
    # requête (~560 ms), au lieu de quelques microsecondes en local.
    _, publique = cle_ec
    appels = {"n": 0}

    async def faux_recuperer(forcer_refresh: bool = False):
        appels["n"] += 1
        auth._jwks_cache = {"keys": [publique]}
        return auth._jwks_cache

    monkeypatch.setattr(auth, "_jwks_cache", {})
    monkeypatch.setattr(auth, "_recuperer_jwks", faux_recuperer)
    assert await auth.prechauffer_jwks() is True
    assert appels["n"] == 1


async def test_un_jwks_injoignable_n_empeche_pas_le_demarrage(monkeypatch):
    # Le serveur doit démarrer même si Supabase est injoignable : les jetons
    # seront vérifiés à distance, plus lentement, mais le service répond.
    async def en_panne(forcer_refresh: bool = False):
        raise httpx.ConnectTimeout("réseau")

    monkeypatch.setattr(auth, "_recuperer_jwks", en_panne)
    assert await auth.prechauffer_jwks() is False


def test_le_delai_du_jwks_laisse_le_temps_a_une_connexion_lente():
    # Mesuré sur la connexion de développement : entre 2 et 20 secondes.
    # À 5 secondes, le JWKS expirait à presque tous les démarrages.
    assert auth.DELAI_JWKS_SECONDES >= 15


async def test_le_delai_est_bien_applique_a_la_requete(monkeypatch):
    # La constante ne sert à rien si le client HTTP garde son propre délai.
    vus = {}

    class FauxClient:
        def __init__(self, timeout=None):
            vus["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def get(self, _url):
            class Reponse:
                def raise_for_status(self):
                    return None

                def json(self):
                    return {"keys": []}
            return Reponse()

    monkeypatch.setattr(auth, "_jwks_cache", {})
    monkeypatch.setattr(auth.httpx, "AsyncClient", FauxClient)
    await auth._recuperer_jwks()
    assert vus["timeout"] == auth.DELAI_JWKS_SECONDES
