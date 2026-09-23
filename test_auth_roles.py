"""
Test manuel — Sprint C, Tâche C.1 (dépendances d'auth par rôle).

TEST_SUPABASE_TOKEN (.env) est expiré (cf. Tâche B.5) et n'a de toute façon
rien à voir avec ce qui est testé ici (la vérification du RÔLE, pas la
validité du JWT — déjà couverte ailleurs). On monkeypatch donc
auth.verify_token/auth.get_user_profile plutôt que d'aller régénérer un
token, pour isoler précisément la logique de rôle.

Vérifie :
  1. Un profil role='citoyen' (réel, TEST_CITOYEN_ID) -> 403 sur
     get_current_consultant ET get_current_admin (le critère de validation
     manuelle explicite de la tâche).
  2. Un profil role='consultant'/'admin' (simulé) -> laisse passer, avec le
     bon id/commune dans le retour.
"""
import asyncio
from dotenv import load_dotenv

load_dotenv()

from fastapi import HTTPException
import auth
from test_bascule_administratif import TEST_CITOYEN_ID  # profil réel, role='citoyen'


async def _verify_token_simule(token):
    return {"sub": TEST_CITOYEN_ID, "email": "test@example.com"}


async def main_test():
    auth.verify_token = _verify_token_simule

    # --- 1. Cas négatif (critère de validation explicite de la tâche) -------
    print("=== role='citoyen' sur get_current_consultant (attendu: 403) ===")
    try:
        await auth.get_current_consultant(authorization="Bearer peu-importe")
        assert False, "get_current_consultant a laissé passer un citoyen !"
    except HTTPException as e:
        print(f"-> {e.status_code} {e.detail}")
        assert e.status_code == 403

    print("\n=== role='citoyen' sur get_current_admin (attendu: 403) ===")
    try:
        await auth.get_current_admin(authorization="Bearer peu-importe")
        assert False, "get_current_admin a laissé passer un citoyen !"
    except HTTPException as e:
        print(f"-> {e.status_code} {e.detail}")
        assert e.status_code == 403

    # --- 2. Cas positifs (rôle simulé, sans toucher le vrai profil de test) --
    profil_original = auth.get_user_profile

    async def _profil_consultant(user_id):
        return {"commune": "Dakar", "role": "consultant"}

    async def _profil_admin(user_id):
        return {"commune": "National", "role": "admin"}

    print("\n=== role='consultant' sur get_current_consultant (attendu: 200/passe) ===")
    auth.get_user_profile = _profil_consultant
    try:
        result = await auth.get_current_consultant(authorization="Bearer peu-importe")
        print("->", result)
        assert result == {"id": TEST_CITOYEN_ID, "commune": "Dakar"}
    finally:
        auth.get_user_profile = profil_original

    print("\n=== role='admin' sur get_current_admin (attendu: 200/passe) ===")
    auth.get_user_profile = _profil_admin
    try:
        result = await auth.get_current_admin(authorization="Bearer peu-importe")
        print("->", result)
        assert result == {"id": TEST_CITOYEN_ID, "commune": "National"}
    finally:
        auth.get_user_profile = profil_original

    print("\n✅ Tâche C.1 : dépendances de rôle OK (403 pour un mauvais rôle, passe pour le bon)")


if __name__ == "__main__":
    asyncio.run(main_test())
