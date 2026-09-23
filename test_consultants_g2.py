"""
Test manuel — Sprint G, Tâche G.2 (CRUD consultants). Critère de validation
explicite : créer un consultant, le désactiver -> vérifier qu'il ne peut plus
se connecter côté web (401/403), SANS supprimer ses dossiers déjà traités.

Utilise de VRAIS appels à l'API Auth Supabase pour la tentative de connexion
(pas un bypass de dépendance) — c'est exactement ce que fait
supabase.auth.signInWithPassword() côté frontend (Tâche F.1/login).
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import os
import httpx
from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient
import main  # noqa: E402
from supabase_client import get_supabase_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im50bXFuaHl6cGV2YmZvc29wbWp5Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODYwNDY4MjcsImV4cCI6MjEwMTYyMjgyN30.l1YyTpNa_Bx98r2Bn7wMMw98ojjmF8GaKcjsu1MEsOE"
EMAIL_TEST = "consultant.test.g2@sunu-mairie.local"

client = TestClient(main.app)
main.app.dependency_overrides[main.get_current_admin] = lambda: {"id": "admin-test", "commune": "National"}


def tenter_login(email: str, mot_de_passe: str) -> httpx.Response:
    return httpx.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={"apikey": ANON_KEY, "Content-Type": "application/json"},
        json={"email": email, "password": mot_de_passe},
        timeout=10,
    )


def main_test():
    supabase = get_supabase_client()

    # Repartir propre si le script a déjà tourné.
    for u in supabase.auth.admin.list_users():
        if u.email == EMAIL_TEST:
            supabase.auth.admin.delete_user(u.id)
            break

    # --- 1. Création (POST /admin/consultants) ----------------------------------
    print("=== 1. Création du consultant ===")
    r_creer = client.post("/admin/consultants", json={"email": EMAIL_TEST, "commune": "Ross-Béthio"})
    assert r_creer.status_code == 200, r_creer.text
    consultant = r_creer.json()
    consultant_id = consultant["id"]
    mot_de_passe = consultant["mot_de_passe_temporaire"]
    print(f"✅ Consultant créé : {consultant_id} ({EMAIL_TEST}, commune Ross-Béthio)")

    # --- 2. Se connecte normalement AVANT désactivation --------------------------
    print("\n=== 2. Connexion AVANT désactivation (attendu : 200) ===")
    r_login_avant = tenter_login(EMAIL_TEST, mot_de_passe)
    assert r_login_avant.status_code == 200, r_login_avant.text
    token_avant = r_login_avant.json()["access_token"]
    print("✅ Connexion réussie, token obtenu.")

    # TestClient partage le process Python avec main.py mais pas les vraies
    # requêtes réseau vers Supabase Auth — on utilise httpx direct contre le
    # serveur uvicorn réellement démarré (127.0.0.1:8000) pour cette partie,
    # afin de tester le VRAI chemin qu'emprunte le frontend, token compris.
    r_dossiers_avant_reel = httpx.get(
        "http://127.0.0.1:8000/consultant/dossiers", headers={"Authorization": f"Bearer {token_avant}"}
    )
    assert r_dossiers_avant_reel.status_code == 200, r_dossiers_avant_reel.text
    nb_dossiers_avant = len(r_dossiers_avant_reel.json()["dossiers"])
    print(f"✅ Accès à /consultant/dossiers confirmé — {nb_dossiers_avant} dossier(s) visibles pour Ross-Béthio.")

    # --- 3. Désactivation (PATCH /admin/consultants/{id}) ------------------------
    print("\n=== 3. Désactivation ===")
    r_desactiver = client.patch(f"/admin/consultants/{consultant_id}", json={"actif": False})
    assert r_desactiver.status_code == 200, r_desactiver.text
    print("✅ Consultant désactivé (ban_duration côté Supabase Auth).")

    r_liste = client.get("/admin/consultants")
    consultant_relu = next(c for c in r_liste.json()["consultants"] if c["id"] == consultant_id)
    assert consultant_relu["actif"] is False, "La liste admin ne reflète pas la désactivation !"
    print("✅ GET /admin/consultants confirme actif=False.")

    # --- 4. CRITÈRE DE VALIDATION : connexion refusée APRÈS désactivation --------
    print("\n=== 4. Connexion APRÈS désactivation (attendu : rejet, 400/401) ===")
    r_login_apres = tenter_login(EMAIL_TEST, mot_de_passe)
    print(f"Statut : {r_login_apres.status_code}, corps : {r_login_apres.text}")
    assert r_login_apres.status_code in (400, 401), (
        f"Le consultant désactivé a pu obtenir un token ! (statut {r_login_apres.status_code})"
    )
    assert "access_token" not in r_login_apres.json(), "Un access_token a été délivré malgré la désactivation !"
    print("✅ Connexion refusée après désactivation — le compte ne peut plus obtenir de session du tout.")

    # --- 5. CRITÈRE DE VALIDATION : les dossiers n'ont PAS disparu ---------------
    print("\n=== 5. Vérifie que les dossiers de Ross-Béthio n'ont pas été supprimés ===")
    # Un consultant désactivé ne peut plus se connecter — on relit via un AUTRE
    # consultant actif de la même commune (déjà créé dans une tâche précédente),
    # exactement ce qu'un vrai collègue verrait après la désactivation.
    r_login_autre = tenter_login("consultant.test.f1@sunu-mairie.local", "KVenhT8H_wSKurZB")
    assert r_login_autre.status_code == 200, r_login_autre.text
    token_autre = r_login_autre.json()["access_token"]
    r_dossiers_apres = httpx.get(
        "http://127.0.0.1:8000/consultant/dossiers", headers={"Authorization": f"Bearer {token_autre}"}
    )
    assert r_dossiers_apres.status_code == 200
    nb_dossiers_apres = len(r_dossiers_apres.json()["dossiers"])
    print(f"Dossiers Ross-Béthio avant désactivation : {nb_dossiers_avant} — après : {nb_dossiers_apres}")
    assert nb_dossiers_apres == nb_dossiers_avant, "Des dossiers ont disparu après la désactivation du consultant !"
    print("✅ Aucun dossier supprimé — la désactivation n'a touché que le compte Auth, pas les données de la commune.")

    # --- 6. Bonus : réactivation redonne l'accès ---------------------------------
    print("\n=== 6. Réactivation ===")
    r_reactiver = client.patch(f"/admin/consultants/{consultant_id}", json={"actif": True})
    assert r_reactiver.status_code == 200
    r_login_reactive = tenter_login(EMAIL_TEST, mot_de_passe)
    assert r_login_reactive.status_code == 200, r_login_reactive.text
    print("✅ Réactivé : la connexion refonctionne avec le même mot de passe.")

    print("\n✅ Tâche G.2 : création, désactivation (connexion refusée), dossiers intacts, réactivation — OK")


if __name__ == "__main__":
    main_test()
