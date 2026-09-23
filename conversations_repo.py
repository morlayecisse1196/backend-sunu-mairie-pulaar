"""
conversations_repo.py — historique des conversations mobile (migration 010).

Persiste réellement chaque tour de dialogue (mode information ET
administratif, cf. websocket_endpoint/emettre_reponse_pulaar_et_tts, main.py)
dans `conversations`/`messages`, jusqu'ici jamais écrits nulle part (seul
`sessions`/`dossier_sessions` existaient, en mémoire process, perdus au
redémarrage). Un `session_id` correspond à UNE conversation (créée au premier
tour, mise à jour ensuite si son mode/dossier_id évoluent — ex. bascule
information -> administratif en cours de route).

Même principe défensif que dossiers_repo.py : un échec d'écriture ici ne doit
JAMAIS faire tomber le dialogue vocal en cours — l'appelant (main.py) doit
traiter tout retour `None`/liste vide comme non bloquant.
"""
from datetime import datetime, timezone
from typing import Optional

from supabase_client import get_supabase_client

TITRE_MAX_LONGUEUR = 60


def _titre_depuis_message(message: Optional[str]) -> str:
    if not message or not message.strip():
        return "Nouvelle conversation"
    texte = message.strip()
    return texte if len(texte) <= TITRE_MAX_LONGUEUR else texte[:TITRE_MAX_LONGUEUR - 1].rstrip() + "…"


def get_or_create_conversation(
    session_id: str, citoyen_id: str, mode: str,
    dossier_id: Optional[str] = None, premier_message: Optional[str] = None,
) -> Optional[dict]:
    """
    Retourne la conversation liée à `session_id`, la crée si absente (titre
    dérivé de `premier_message`, ignoré si la conversation existe déjà — le
    titre ne change plus une fois posé, même principe que Claude web). Met à
    jour `mode`/`dossier_id` si la conversation existante a évolué (ex. la
    bascule information -> administratif survient en cours de session).
    """
    try:
        supabase = get_supabase_client()
        existante = (
            supabase.table("conversations").select("*").eq("session_id", session_id).limit(1).execute()
        )
        if existante.data:
            conversation = existante.data[0]
            maj = {}
            if mode != conversation["mode"]:
                maj["mode"] = mode
            if dossier_id and conversation.get("dossier_id") != dossier_id:
                maj["dossier_id"] = dossier_id
            if maj:
                maj["updated_at"] = datetime.now(timezone.utc).isoformat()
                supabase.table("conversations").update(maj).eq("id", conversation["id"]).execute()
                conversation = {**conversation, **maj}
            return conversation

        nouvelle = {
            "citoyen_id": citoyen_id, "session_id": session_id, "mode": mode,
            "dossier_id": dossier_id, "titre": _titre_depuis_message(premier_message),
        }
        response = supabase.table("conversations").insert(nouvelle).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"⚠️ get_or_create_conversation échoué (session {session_id}) : {e} — historique non persisté pour ce tour.")
        return None


def ajouter_message(
    conversation_id: str, role: str, contenu_fr: str, contenu_pulaar: Optional[str] = None,
) -> Optional[dict]:
    """Insère un message et touche `conversations.updated_at` (tri de la liste, Feature 2)."""
    try:
        supabase = get_supabase_client()
        response = supabase.table("messages").insert({
            "conversation_id": conversation_id, "role": role,
            "contenu_fr": contenu_fr, "contenu_pulaar": contenu_pulaar,
        }).execute()
        supabase.table("conversations").update(
            {"updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", conversation_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"⚠️ ajouter_message échoué (conversation {conversation_id}, role={role}) : {e}")
        return None


def mettre_a_jour_pulaar(message_id: str, contenu_pulaar: str) -> None:
    """Complète un message assistant avec sa version pulaar, connue seulement après la traduction en flux."""
    try:
        supabase = get_supabase_client()
        supabase.table("messages").update({"contenu_pulaar": contenu_pulaar}).eq("id", message_id).execute()
    except Exception as e:
        print(f"⚠️ mettre_a_jour_pulaar échoué (message {message_id}) : {type(e).__name__}")


def list_conversations_citoyen(citoyen_id: str) -> list:
    """Le plus récemment actif d'abord — même logique de tri qu'une liste de chats Claude web."""
    try:
        supabase = get_supabase_client()
        response = (
            supabase.table("conversations").select("*")
            .eq("citoyen_id", citoyen_id).order("updated_at", desc=True).execute()
        )
        return response.data or []
    except Exception as e:
        print(f"⚠️ list_conversations_citoyen échoué (citoyen {citoyen_id}) : {e}")
        return []


def get_conversation(conversation_id: str) -> Optional[dict]:
    try:
        supabase = get_supabase_client()
        response = supabase.table("conversations").select("*").eq("id", conversation_id).limit(1).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"⚠️ get_conversation échoué ({conversation_id}) : {e}")
        return None


def list_messages(conversation_id: str) -> list:
    """Ordre chronologique (le plus ancien d'abord) — ordre naturel de lecture d'un transcript."""
    try:
        supabase = get_supabase_client()
        response = (
            supabase.table("messages").select("*")
            .eq("conversation_id", conversation_id).order("created_at").execute()
        )
        return response.data or []
    except Exception as e:
        print(f"⚠️ list_messages échoué (conversation {conversation_id}) : {e}")
        return []


def get_message(message_id: str) -> Optional[dict]:
    try:
        supabase = get_supabase_client()
        response = supabase.table("messages").select("*").eq("id", message_id).limit(1).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"⚠️ get_message échoué ({message_id}) : {e}")
        return None
