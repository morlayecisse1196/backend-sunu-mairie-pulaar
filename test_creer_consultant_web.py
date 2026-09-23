"""
Script ponctuel — pas un test automatisé permanent : crée (ou réutilise) un
compte consultant réel dans Supabase Auth, pour valider F.1 de bout en bout
(vraie page de login Next.js -> vraie session Supabase -> vrai appel API).
Affiche l'email et le mot de passe temporaire en clair, uniquement en local.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from admin_repo import create_consultant
from supabase_client import get_supabase_client

EMAIL = "consultant.test.f1@sunu-mairie.local"
COMMUNE = "Ross-Béthio"

supabase = get_supabase_client()

# Si le compte existe déjà (script relancé), on ne peut pas relire son mot de
# passe (jamais restocké en clair, cf. admin_repo.create_consultant) — dans
# ce cas on le supprime et on le recrée pour ce test ponctuel.
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
