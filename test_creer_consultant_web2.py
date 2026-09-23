"""
Script ponctuel — second compte consultant (commune Dakar), pour valider le
critère F.2 : la liste reflète EXACTEMENT la commune du consultant connecté,
vérifié avec deux comptes différents (Ross-Béthio vs Dakar).
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from admin_repo import create_consultant
from supabase_client import get_supabase_client

EMAIL = "consultant.test.f2.dakar@sunu-mairie.local"
COMMUNE = "Dakar"

supabase = get_supabase_client()

existants = supabase.auth.admin.list_users()
for u in existants:
    if u.email == EMAIL:
        print(f"ℹ️ Compte existant {EMAIL} trouvé, suppression pour recréation propre.")
        supabase.auth.admin.delete_user(u.id)
        break

resultat = create_consultant(EMAIL, COMMUNE)
assert resultat, "Échec de la création du consultant de test"
print("EMAIL=" + resultat["email"])
print("PASSWORD=" + resultat["mot_de_passe_temporaire"])
print("COMMUNE=" + resultat["commune"])
