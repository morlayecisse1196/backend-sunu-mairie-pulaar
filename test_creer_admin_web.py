"""
Script ponctuel — crée un compte admin réel pour la vérification manuelle en
navigateur des écrans G.1 (/admin/communes, /admin/communes/[id]). Pas de
create_admin() dédié dans admin_repo.py (seul create_consultant existe) :
on reproduit la même mécanique directement ici.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import secrets
from dotenv import load_dotenv
load_dotenv()

from supabase_client import get_supabase_client

EMAIL = "admin.test.g1@sunu-mairie.local"

supabase = get_supabase_client()

existants = supabase.auth.admin.list_users()
for u in existants:
    if u.email == EMAIL:
        print(f"ℹ️ Compte existant {EMAIL} trouvé, suppression pour recréation propre.")
        supabase.auth.admin.delete_user(u.id)
        break

mot_de_passe = secrets.token_urlsafe(12)
reponse_auth = supabase.auth.admin.create_user({"email": EMAIL, "password": mot_de_passe, "email_confirm": True})
user_id = reponse_auth.user.id
supabase.table("profiles").upsert({"id": user_id, "commune": "National", "role": "admin"}, on_conflict="id").execute()

print("EMAIL=" + EMAIL)
print("PASSWORD=" + mot_de_passe)
