"""
Test manuel — Tâche 7.1 du roadmap mobile (FLUTTER_APP_PROMPTS.md) : endpoints
citoyen pour le suivi de dossier + validation du document généré (Flux §2.7).

Critères de validation manuelle explicites :
  1. Un dossier de test amené jusqu'à 'en_attente_validation_citoyen' (parcours
     F.5 déjà validé côté web) apparaît dans GET /mes-dossiers du bon citoyen,
     avec une URL signée du PDF exploitable.
  2. POST .../valider fait passer le statut à 'finalise' — vérifié en base.
  3. POST .../demander-corrections fait apparaître le dossier en
     'corrections_demandees', et la remarque est journalisée avec source='citoyen'.
  4. Un citoyen B ne peut ni lire ni agir sur un dossier du citoyen A (403).
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

import httpx
from fastapi.testclient import TestClient
import main  # noqa: E402
from dossiers_repo import get_dossier, get_supabase_client
from test_document_generator import creer_dossier_complet
from test_bascule_administratif import TEST_CITOYEN_ID, TEST_COMMUNE

client = TestClient(main.app)

CITOYEN_A = TEST_CITOYEN_ID
EMAIL_CITOYEN_B = "citoyen.test.mobile.g@sunu-mairie.local"


def preparer_citoyen_b() -> str:
    """Second citoyen réel (profil minimal), pour le test d'isolation 403."""
    supabase = get_supabase_client()
    for u in supabase.auth.admin.list_users():
        if u.email == EMAIL_CITOYEN_B:
            supabase.auth.admin.delete_user(u.id)
            break
    reponse = supabase.auth.admin.create_user({"email": EMAIL_CITOYEN_B, "password": "peu-importe-1234", "email_confirm": True})
    citoyen_b_id = reponse.user.id
    supabase.table("profiles").upsert({"id": citoyen_b_id, "commune": TEST_COMMUNE, "role": "citoyen"}, on_conflict="id").execute()
    return citoyen_b_id


def amener_a_validation_citoyen(numero_acte_unique: str) -> str:
    """Reproduit le parcours F.5 déjà validé côté web (analyse -> génération -> validation consultant)
    pour obtenir un dossier réellement en 'en_attente_validation_citoyen', pas un statut forcé à la main."""
    dossier = creer_dossier_complet(numero_acte=numero_acte_unique)
    dossier_id = dossier["id"]

    # creer_dossier_complet() (test_document_generator.py) crée toujours sous
    # Ross-Béthio, indépendamment de TEST_COMMUNE ("Dakar") utilisée pour le
    # citoyen lui-même — le consultant qui génère/valide doit donc être scopé
    # sur la commune RÉELLE du dossier, pas celle du profil citoyen.
    main.app.dependency_overrides[main.get_current_consultant] = lambda: {"id": "consultant-test", "commune": "Ross-Béthio"}
    r_gen = client.post(f"/consultant/dossiers/{dossier_id}/generer")
    assert r_gen.status_code == 200, r_gen.text
    r_valider = client.post(f"/consultant/dossiers/{dossier_id}/valider")
    assert r_valider.status_code == 200, r_valider.text
    del main.app.dependency_overrides[main.get_current_consultant]

    dossier_relu = get_dossier(dossier_id)
    assert dossier_relu["statut"] == "en_attente_validation_citoyen", dossier_relu["statut"]
    return dossier_id


def main_test():
    citoyen_b_id = preparer_citoyen_b()
    print(f"👤 Citoyen B (isolation) : {citoyen_b_id}")

    # ==========================================================================
    # Scénario 1 : validation (le citoyen accepte le document tel quel)
    # ==========================================================================
    print("\n=== Préparation dossier A (jusqu'à en_attente_validation_citoyen) ===")
    dossier_a = amener_a_validation_citoyen("0000000000000000701")
    print(f"📁 Dossier A : {dossier_a}")

    main.app.dependency_overrides[main.get_current_user] = lambda: {"id": CITOYEN_A, "commune": TEST_COMMUNE}

    print("\n=== 1. GET /mes-dossiers (doit contenir le dossier A) ===")
    r_liste = client.get("/mes-dossiers")
    assert r_liste.status_code == 200, r_liste.text
    ids = [d["id"] for d in r_liste.json()["dossiers"]]
    assert dossier_a in ids
    print(f"✅ Dossier A présent dans /mes-dossiers ({len(ids)} dossier(s) au total pour ce citoyen).")

    print("\n=== 2. GET /mes-dossiers/{id} — document généré + URL signée exploitable ===")
    r_detail = client.get(f"/mes-dossiers/{dossier_a}")
    assert r_detail.status_code == 200, r_detail.text
    detail = r_detail.json()
    assert detail["document_genere"] is not None
    url_signee = detail["document_genere"]["url_signee"]
    assert url_signee
    r_pdf = httpx.get(url_signee)
    assert r_pdf.status_code == 200
    assert r_pdf.headers.get("content-type") == "application/pdf"
    print(f"✅ PDF réellement téléchargeable via l'URL signée ({len(r_pdf.content)} octets, application/pdf).")

    print("\n=== 3. Isolation — citoyen B ne peut PAS lire/agir sur le dossier A ===")
    main.app.dependency_overrides[main.get_current_user] = lambda: {"id": citoyen_b_id, "commune": TEST_COMMUNE}
    assert client.get(f"/mes-dossiers/{dossier_a}").status_code == 403
    assert client.post(f"/mes-dossiers/{dossier_a}/valider").status_code == 403
    assert client.post(f"/mes-dossiers/{dossier_a}/demander-corrections", json={"texte": "x"}).status_code == 403
    print("✅ GET détail, POST valider, POST demander-corrections tous refusés (403) au citoyen B.")

    print("\n=== 4. Validation par le vrai propriétaire (citoyen A) ===")
    main.app.dependency_overrides[main.get_current_user] = lambda: {"id": CITOYEN_A, "commune": TEST_COMMUNE}
    r_valider = client.post(f"/mes-dossiers/{dossier_a}/valider")
    assert r_valider.status_code == 200, r_valider.text
    print("Réponse :", r_valider.json())

    dossier_a_relu = get_dossier(dossier_a)
    print(f"En base : statut={dossier_a_relu['statut']!r}")
    assert dossier_a_relu["statut"] == "finalise"
    print("✅ Statut EN BASE = 'finalise' — critère de validation respecté.")

    print("\n=== 5. Re-valider un dossier déjà finalisé (attendu : 400) ===")
    r_double = client.post(f"/mes-dossiers/{dossier_a}/valider")
    assert r_double.status_code == 400, r_double.text
    print("✅ Double validation refusée :", r_double.json()["detail"])

    # ==========================================================================
    # Scénario 2 : demande de corrections
    # ==========================================================================
    print("\n\n=== Préparation dossier B (jusqu'à en_attente_validation_citoyen) ===")
    dossier_b = amener_a_validation_citoyen("0000000000000000702")
    print(f"📁 Dossier B : {dossier_b}")

    print("\n=== 6. POST /mes-dossiers/{id}/demander-corrections ===")
    texte_remarque = "Le nom de la mère est mal orthographié sur le document généré."
    r_corrections = client.post(f"/mes-dossiers/{dossier_b}/demander-corrections", json={"texte": texte_remarque})
    assert r_corrections.status_code == 200, r_corrections.text
    print("Réponse :", r_corrections.json())

    dossier_b_relu = get_dossier(dossier_b)
    assert dossier_b_relu["statut"] == "corrections_demandees", dossier_b_relu["statut"]
    print("✅ Statut EN BASE = 'corrections_demandees'.")

    remarque = r_corrections.json()["remarque"]
    assert remarque["source"] == "citoyen"
    assert remarque["texte"] == texte_remarque
    assert remarque["dossier_id"] == dossier_b
    print(f"✅ Remarque journalisée : source={remarque['source']!r}, texte={remarque['texte']!r}.")

    print("\n=== 7. texte vide -> 400 ===")
    r_vide = client.post(f"/mes-dossiers/{dossier_a}/demander-corrections", json={"texte": "   "})
    assert r_vide.status_code == 400
    print("✅ Texte vide rejeté.")

    print("\n✅ Tâche 7.1 (mobile) : endpoints citoyen pour le suivi de dossier — OK")


if __name__ == "__main__":
    main_test()
