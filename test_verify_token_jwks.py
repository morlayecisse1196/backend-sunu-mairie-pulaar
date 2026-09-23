"""
Test manuel — validation du correctif de perf (vérification JWT locale via
JWKS, cf. discussion "pourquoi l'appli web est lente"). Pas dans le roadmap
d'origine, ajouté pour ne pas avoir régressé auth.verify_token en le
réécrivant.

Vérifie avec un VRAI token JWT (login Supabase réel, signé ES256 par ce
projet) :
  1. Un token valide est accepté, sub/email corrects, sans throw.
  2. Un token altéré (signature cassée) est rejeté (401).
  3. Un token bien formé mais avec un kid inconnu est rejeté (401), pas un
     crash serveur.
"""
import asyncio
import os
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import httpx
from dotenv import load_dotenv

load_dotenv()

import auth  # noqa: E402
from fastapi import HTTPException

SUPABASE_URL = os.getenv("SUPABASE_URL")
ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im50bXFuaHl6cGV2YmZvc29wbWp5Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODYwNDY4MjcsImV4cCI6MjEwMTYyMjgyN30.l1YyTpNa_Bx98r2Bn7wMMw98ojjmF8GaKcjsu1MEsOE"


def obtenir_token_reel() -> str:
    r = httpx.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={"apikey": ANON_KEY, "Content-Type": "application/json"},
        json={"email": "consultant.test.f1@sunu-mairie.local", "password": "KVenhT8H_wSKurZB"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


async def main_test():
    token = obtenir_token_reel()
    print(f"Token réel obtenu ({len(token)} caractères)")

    # --- 1. Token valide -----------------------------------------------------
    resultat = await auth.verify_token(token)
    print("verify_token(token valide) ->", resultat)
    assert resultat["sub"], "sub manquant"
    assert resultat["email"] == "consultant.test.f1@sunu-mairie.local"
    print("✅ Token valide accepté, sub/email corrects.")

    # --- 2. Signature altérée -------------------------------------------------
    parties = token.split(".")
    signature_cassee = parties[0] + "." + parties[1] + "." + "AAAA" + parties[2][4:]
    try:
        await auth.verify_token(signature_cassee)
        assert False, "Un token à la signature cassée a été accepté !"
    except HTTPException as e:
        assert e.status_code == 401
        print(f"✅ Signature altérée rejetée : {e.status_code} {e.detail}")

    # --- 3. kid inconnu (rotation de clé simulée) -----------------------------
    import base64
    import json as jsonlib

    header_b64 = parties[0]
    header_b64 += "=" * (-len(header_b64) % 4)
    header = jsonlib.loads(base64.urlsafe_b64decode(header_b64))
    header["kid"] = "kid-qui-nexiste-pas"
    nouveau_header_b64 = base64.urlsafe_b64encode(jsonlib.dumps(header).encode()).decode().rstrip("=")
    token_kid_invalide = nouveau_header_b64 + "." + parties[1] + "." + parties[2]
    try:
        await auth.verify_token(token_kid_invalide)
        assert False, "Un token avec un kid inconnu a été accepté !"
    except HTTPException as e:
        assert e.status_code == 401
        print(f"✅ kid inconnu rejeté proprement (pas de crash serveur) : {e.status_code} {e.detail}")

    print("\n✅ verify_token (JWKS local) : OK — accepte un vrai token, rejette signature cassée et kid inconnu.")


if __name__ == "__main__":
    asyncio.run(main_test())
