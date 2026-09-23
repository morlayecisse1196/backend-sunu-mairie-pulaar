"""
Test manuel — Sprint F, Tâche F.2, critère de validation explicite : "la
liste reflète exactement les dossiers de la commune du consultant connecté
(vérifier avec deux comptes différents)".

Crée un dossier marqueur dans Dakar (aucun dossier Dakar n'existait avant),
puis appelle GET /consultant/dossiers en tant que consultant Ross-Béthio et
en tant que consultant Dakar, et vérifie qu'aucun des deux ne voit les
dossiers de l'autre commune.
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


def main_test():
    commune_dakar = main.resoudre_commune_id("Dakar")
    commune_rb = main.resoudre_commune_id("Ross-Béthio")
    assert commune_dakar and commune_rb

    dossier_dakar = main.create_dossier(
        citoyen_id=TEST_CITOYEN_ID, type_demarche="extrait_naissance",
        slots=dict(main.SLOTS_VIDES_EXTRAIT_NAISSANCE), cas_legal="dans_les_delais",
        commune_id=commune_dakar, statut="recu",
    )
    assert dossier_dakar
    print(f"📁 Dossier marqueur créé pour Dakar : {dossier_dakar['id']}")

    # --- Consultant Ross-Béthio ---
    main.app.dependency_overrides[main.get_current_consultant] = lambda: {
        "id": "consultant-rb-test", "commune": "Ross-Béthio",
    }
    r_rb = client.get("/consultant/dossiers")
    assert r_rb.status_code == 200, r_rb.text
    dossiers_rb = r_rb.json()["dossiers"]
    ids_rb = {d["id"] for d in dossiers_rb}
    communes_rb = {d["commune_id"] for d in dossiers_rb}
    print(f"👤 Consultant Ross-Béthio voit {len(dossiers_rb)} dossier(s).")
    assert communes_rb == {commune_rb}, f"Le consultant Ross-Béthio voit d'autres communes : {communes_rb}"
    assert dossier_dakar["id"] not in ids_rb, "Le consultant Ross-Béthio voit le dossier marqueur de Dakar !"
    print("✅ Le consultant Ross-Béthio ne voit QUE des dossiers de Ross-Béthio (pas celui de Dakar).")

    # --- Consultant Dakar ---
    main.app.dependency_overrides[main.get_current_consultant] = lambda: {
        "id": "consultant-dakar-test", "commune": "Dakar",
    }
    r_dakar = client.get("/consultant/dossiers")
    assert r_dakar.status_code == 200, r_dakar.text
    dossiers_dakar = r_dakar.json()["dossiers"]
    ids_dakar = {d["id"] for d in dossiers_dakar}
    communes_dakar = {d["commune_id"] for d in dossiers_dakar}
    print(f"👤 Consultant Dakar voit {len(dossiers_dakar)} dossier(s).")
    assert communes_dakar == {commune_dakar}, f"Le consultant Dakar voit d'autres communes : {communes_dakar}"
    assert dossier_dakar["id"] in ids_dakar, "Le consultant Dakar ne voit PAS son propre dossier marqueur !"
    assert ids_rb.isdisjoint(ids_dakar), "Chevauchement entre les deux listes — isolation par commune cassée !"
    print("✅ Le consultant Dakar ne voit QUE son dossier marqueur (aucun dossier Ross-Béthio).")

    print("\n✅ Tâche F.2 : isolation stricte par commune confirmée avec deux comptes distincts.")


if __name__ == "__main__":
    main_test()
