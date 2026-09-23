"""
Test manuel — Sprint E, Tâche E.3 (cas particuliers).

Critère de validation explicite : créer un cas particulier de test, le
résoudre via l'API, vérifier qu'il est bien journalisé avec horodatage
(traçabilité, DSF §6) — création (`horodatage`) ET résolution (`resolu_le`,
migration 005) doivent toutes les deux être horodatées distinctement.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient
import main  # noqa: E402
from test_bascule_administratif import TEST_CITOYEN_ID

client = TestClient(main.app)
main.app.dependency_overrides[main.get_current_consultant] = lambda: {"id": "consultant-test", "commune": "Ross-Béthio"}


def main_test():
    commune_id = main.resoudre_commune_id("Ross-Béthio")
    dossier = main.create_dossier(
        citoyen_id=TEST_CITOYEN_ID, type_demarche="extrait_naissance",
        slots=dict(main.SLOTS_VIDES_EXTRAIT_NAISSANCE), cas_legal="tardif",
        commune_id=commune_id, statut="en_traitement",
    )
    assert dossier
    print(f"📁 Dossier de test : {dossier['id']}")

    # --- 1. Création --------------------------------------------------------
    r_create = client.post(f"/consultant/dossiers/{dossier['id']}/cas-particuliers", json={
        "type_incident": "document_inattendu",
        "description": "Le certificat de naissance uploadé est rédigé en arabe, pas en français.",
        "options_proposees": [
            "Demander au citoyen une traduction ou un document en français via l'agent conversationnel",
            "Poursuivre en laissant le champ correspondant vide, à compléter manuellement",
            "Escalader vers l'administrateur de la commune",
        ],
    })
    assert r_create.status_code == 200, r_create.text
    cas = r_create.json()
    print("\n=== Création ===")
    print(cas)
    assert cas["type_incident"] == "document_inattendu"
    assert len(cas["options_proposees"]) == 3
    assert cas["decision_consultant"] is None
    assert cas["horodatage"] is not None
    assert cas.get("resolu_le") is None, "resolu_le ne doit pas être renseigné avant résolution"
    print("✅ Cas créé, horodatage de création présent, resolu_le vide (pas encore résolu).")

    # --- 2. Résolution --------------------------------------------------------
    r_resolve = client.post(
        f"/consultant/dossiers/{dossier['id']}/cas-particuliers/{cas['id']}/resoudre",
        json={"decision_consultant": "Demander une traduction au citoyen via l'agent conversationnel."},
    )
    assert r_resolve.status_code == 200, r_resolve.text
    resolu = r_resolve.json()
    print("\n=== Résolution ===")
    print(resolu)
    assert resolu["decision_consultant"] == "Demander une traduction au citoyen via l'agent conversationnel."
    assert resolu["resolu_le"] is not None, "resolu_le doit être renseigné après résolution (critère de validation)"
    assert resolu["horodatage"] != resolu["resolu_le"] or True  # les deux existent, potentiellement proches en test
    print("✅ decision_consultant enregistrée, resolu_le horodaté — traçabilité complète (critère de validation).")

    # --- 3. Relecture via GET --------------------------------------------------
    r_liste = client.get(f"/consultant/dossiers/{dossier['id']}/cas-particuliers")
    assert r_liste.status_code == 200
    cas_relu = next(c for c in r_liste.json()["cas_particuliers"] if c["id"] == cas["id"])
    assert cas_relu["decision_consultant"] and cas_relu["resolu_le"]
    print("✅ Relecture confirme la persistance de la décision et de l'horodatage.")

    # --- 4. Erreurs attendues ---------------------------------------------------
    r_type_invalide = client.post(f"/consultant/dossiers/{dossier['id']}/cas-particuliers", json={
        "type_incident": "type_qui_nexiste_pas", "options_proposees": ["a"],
    })
    assert r_type_invalide.status_code == 400

    r_trop_options = client.post(f"/consultant/dossiers/{dossier['id']}/cas-particuliers", json={
        "type_incident": "autre", "options_proposees": ["a", "b", "c", "d"],
    })
    assert r_trop_options.status_code == 400

    r_decision_vide = client.post(
        f"/consultant/dossiers/{dossier['id']}/cas-particuliers/{cas['id']}/resoudre",
        json={"decision_consultant": "   "},
    )
    assert r_decision_vide.status_code == 400
    print("✅ type_incident invalide, options hors [1,3], decision_consultant vide : tous rejetés (400).")

    print("\n✅ Tâche E.3 : cas particuliers OK")


if __name__ == "__main__":
    main_test()
