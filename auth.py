import os
from jose import jwt, JWTError
from fastapi import HTTPException, WebSocketException, status
from supabase_client import get_supabase_client

SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")


async def verify_token(token: str) -> dict:
    """
    Vérifie le JWT Supabase en interrogeant directement l'API Auth.
    Retourne les données utilisateur si valide.
    """
    supabase = get_supabase_client()
    try:
        # Cette méthode valide le token et retourne l'utilisateur
        user_response = supabase.auth.get_user(token)
        # user_response est un objet UserResponse avec un attribut 'user'
        user = user_response.user
        return {
            "sub": user.id,
            "email": user.email,
            # Autres champs utiles
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token invalide: {str(e)}")

async def get_user_profile(user_id: str) -> dict:
    """
    Récupère la commune de l'utilisateur depuis la table profiles.
    """
    supabase = get_supabase_client()
    try:
        response = supabase.table("profiles").select("commune").eq("id", user_id).execute()
        if response.data:
            return response.data[0]
        return {"commune": "National"}
    except Exception:
        return {"commune": "National"}