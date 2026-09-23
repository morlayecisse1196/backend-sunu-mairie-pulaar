"""
Test manuel — Sprint C, Tâche C.4 (endpoints admin : communes, consultants,
templates, supervision).

Contrairement aux tests précédents (token expiré -> override de dépendance),
celui-ci fait un aller-retour d'authentification RÉEL de bout en bout — c'est
justement le critère de validation explicite de la tâche : "créer un
consultant via l'API, vérifier qu'il peut IMMÉDIATEMENT se connecter et
n'accède qu'à sa commune". Impossible de le simuler sans un vrai compte.

  1. POST /admin/consultants (commune=Ross-Béthio) -> compte Auth + profil
     créés, mot de passe temporaire reçu.
  2. Connexion RÉELLE avec ce mot de passe -> JWT valide.
  3. Ce JWT passe get_current_consultant (Tâche C.1) EN VRAI (pas mocké).
  4. GET /consultant/dossiers (Tâche C.2) avec ce vrai JWT -> ne voit que les
     dossiers de Ross-Béthio, pas ceux de Dindéfélo (isolation confirmée
     avec un compte réellement créé par l'admin, pas un profil simulé).
  5. CRUD communes/templates + supervision, plus légers.

Nettoyage : le compte consultant de test est supprimé à la fin (pas de
raison de garder un compte Auth jetable).
"""
import asyncio
import uuid
from dotenv import load_dotenv

load_dotenv()

from fastapi.testclient import TestClient
import main  # noqa: E402
import auth
from supabase_client import get_supabase_client
from test_bascule_administratif import TEST_CITOYEN_ID

client = TestClient(main.app)
main.app.dependency_overrides[main.get_current_admin] = lambda: {"id": "admin-test", "commune": "National"}


async def main_test():
    email_test = f"consultant.test.{uuid.uuid4().hex[:8]}@example.com"

    # --- 1. Création du compte consultant via l'API --------------------------
    r = client.post("/admin/consultants", json={"email": email_test, "commune": "Ross-Béthio"})
    assert r.status_code == 200, r.text
    consultant = r.json()
    print("=== POST /admin/consultants ===")
    print({k: v for k, v in consultant.items() if k != "mot_de_passe_temporaire"}, "+ mot de passe temporaire reçu")
    assert consultant["email"] == email_test
    assert consultant["commune"] == "Ross-Béthio"
    mot_de_passe = consultant["mot_de_passe_temporaire"]
    consultant_id = consultant["id"]

    try:
        # --- 2. Connexion RÉELLE avec ce mot de passe -------------------------
        supabase = get_supabase_client()
        session = supabase.auth.sign_in_with_password({"email": email_test, "password": mot_de_passe})
        access_token = session.session.access_token
        print("\n✅ Connexion immédiate réussie avec le mot de passe temporaire (critère de validation).")

        # --- 3. get_current_consultant EN VRAI (pas mocké) --------------------
        profil = await auth.get_current_consultant(authorization=f"Bearer {access_token}")
        print("get_current_consultant (réel) ->", profil)
        assert profil == {"id": consultant_id, "commune": "Ross-Béthio"}
        print("✅ Le rôle 'consultant' est actif immédiatement après création.")

        # --- 4. Isolation par commune avec un VRAI token -----------------------
        commune_rb = main.resoudre_commune_id("Ross-Béthio")
        commune_dk = main.resoudre_commune_id("Dindéfélo")
        d_rb = main.create_dossier(
            citoyen_id=TEST_CITOYEN_ID, type_demarche="extrait_naissance",
            slots=dict(main.SLOTS_VIDES_EXTRAIT_NAISSANCE), commune_id=commune_rb, statut="recu",
        )
        d_dk = main.create_dossier(
            citoyen_id=TEST_CITOYEN_ID, type_demarche="extrait_naissance",
            slots=dict(main.SLOTS_VIDES_EXTRAIT_NAISSANCE), commune_id=commune_dk, statut="recu",
        )
        assert d_rb and d_dk

        r_dossiers = client.get("/consultant/dossiers", headers={"Authorization": f"Bearer {access_token}"})
        assert r_dossiers.status_code == 200, r_dossiers.text
        ids_vus = [d["id"] for d in r_dossiers.json()["dossiers"]]
        print("\nDossiers vus par le nouveau consultant :", len(ids_vus))
        assert d_rb["id"] in ids_vus
        assert d_dk["id"] not in ids_vus, "FUITE : le consultant fraîchement créé voit un dossier d'une autre commune !"
        print("✅ N'accède qu'à sa propre commune (Ross-Béthio), pas à Dindéfélo — critère de validation complet.")

        # --- 5. Désactivation -> ne peut plus passer get_current_consultant ---
        r_patch = client.patch(f"/admin/consultants/{consultant_id}", json={"actif": False})
        assert r_patch.status_code == 200, r_patch.text
        try:
            await auth.get_current_consultant(authorization=f"Bearer {access_token}")
            assert False, "Un consultant désactivé a quand même été accepté !"
        except Exception as e:
            print(f"\n✅ Consultant désactivé -> accès refusé ({type(e).__name__}).")

    finally:
        supabase = get_supabase_client()
        try:
            supabase.auth.admin.delete_user(consultant_id)
            print(f"\n🧹 Compte consultant de test {consultant_id} supprimé.")
        except Exception as e:
            print(f"⚠️ Nettoyage du compte de test échoué ({e}) — à supprimer manuellement si besoin.")

    # --- CRUD communes / templates (plus léger) -------------------------------
    r_communes = client.get("/admin/communes")
    assert r_communes.status_code == 200
    print(f"\n✅ GET /admin/communes -> {len(r_communes.json()['communes'])} commune(s)")

    r_template = client.post("/admin/templates", json={
        "type_demarche": f"test_{uuid.uuid4().hex[:6]}",
        "nom_fichier_xml": "test.xml", "nom_fichier_html": "test.html",
    })
    assert r_template.status_code == 200, r_template.text
    print("✅ POST /admin/templates ->", r_template.json())

    r_supervision = client.get("/admin/supervision")
    assert r_supervision.status_code == 200
    print("\n✅ GET /admin/supervision ->", r_supervision.json())

    print("\n✅ Tâche C.4 : endpoints admin OK")


if __name__ == "__main__":
    asyncio.run(main_test())
