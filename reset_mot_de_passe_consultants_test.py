"""
Script ponctuel — le mot de passe généré par create_consultant() (secrets.token_urlsafe,
cf. admin_repo.py) n'est JAMAIS stocké en clair : une fois le message affiché au moment
de la création perdu (cf. test_creer_consultant_web*.py), il est irrécupérable. Seule
option : le RÉINITIALISER (pas recréer le compte — même mécanisme que set_consultant_actif,
supabase.auth.admin.update_user_by_id), pour les deux comptes consultant de test connus.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import secrets
from dotenv import load_dotenv
load_dotenv()

from supabase_client import get_supabase_client

COMPTES = [
    "consultant.test.f1@sunu-mairie.local",   # commune Ross-Béthio
    "consultant.test.f2.dakar@sunu-mairie.local",  # commune Dakar
]

supabase = get_supabase_client()
existants = {u.email: u.id for u in supabase.auth.admin.list_users()}

for email in COMPTES:
    user_id = existants.get(email)
    if not user_id:
        print(f"⚠️ Compte introuvable : {email} (jamais créé, ou supprimé depuis)")
        continue
    nouveau_mdp = secrets.token_urlsafe(12)
    supabase.auth.admin.update_user_by_id(user_id, {"password": nouveau_mdp})
    print(f"EMAIL={email}")
    print(f"PASSWORD={nouveau_mdp}")
    print()
