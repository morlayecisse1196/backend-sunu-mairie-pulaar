"""
Test manuel — Sprint C, Tâche C.3 (endpoints formulaire : lecture/écriture).

  1. Crée un dossier (slots partiellement remplis) + un document uploadé.
  2. GET .../formulaires -> le formulaire est créé à la volée, pré-rempli
     source="dialogue" pour les champs mappés et connus, "manuel" (valeur
     null) pour le reste.
  3. PATCH un champ (correction de valeur) -> source passe à "manuel".
  4. PATCH le même champ avec verifie=true seul -> verifie_par_consultant
     passe à true SANS repasser la source (déjà "manuel" ici, mais vérifie
     bien que verifie n'écrase pas la valeur).
  5. Relit le dossier (GET formulaires à nouveau) -> la modification persiste.
"""
import asyncio
from dotenv import load_dotenv

load_dotenv()

from fastapi.testclient import TestClient
import main  # noqa: E402
from test_bascule_administratif import TEST_CITOYEN_ID, TEST_COMMUNE
from test_upload_document import FAUX_JPEG

client = TestClient(main.app)
main.app.dependency_overrides[main.get_current_consultant] = lambda: {"id": "consultant-test", "commune": "Ross-Béthio"}


async def main_test():
    commune_id = main.resoudre_commune_id("Ross-Béthio")
    slots = dict(main.SLOTS_VIDES_EXTRAIT_NAISSANCE)
    slots["commune_naissance"] = "Ross-Béthio"
    slots["date_naissance_enfant"] = "2026-08-09"
    slots["nom_enfant"] = "Ibrahima Diallo"  # pas de correspondance 1:1 fiable -> reste vide en formulaire

    dossier = main.create_dossier(
        citoyen_id=TEST_CITOYEN_ID, type_demarche="extrait_naissance",
        slots=slots, cas_legal="dans_les_delais", commune_id=commune_id, statut="recu",
    )
    assert dossier
    document = main.upload_document(dossier["id"], "certificat_naissance", FAUX_JPEG, "image/jpeg", "jpg")
    assert document
    print(f"📁 Dossier {dossier['id']}, document {document['id']}")

    # --- GET formulaires (création à la volée) -------------------------------
    r = client.get(f"/consultant/dossiers/{dossier['id']}/formulaires")
    assert r.status_code == 200, r.text
    formulaires = r.json()["formulaires"]
    assert len(formulaires) == 1
    formulaire = formulaires[0]
    print("\n=== Formulaire créé à la volée ===")
    for champ in formulaire["champs"]:
        print(f"  {champ['nom']:20s} valeur={champ['valeur']!r:30s} source={champ['source']}")

    champs_par_nom = {c["nom"]: c for c in formulaire["champs"]}
    assert champs_par_nom["dateNaissance"]["valeur"] == "2026-08-09"
    assert champs_par_nom["dateNaissance"]["source"] == "dialogue"
    assert champs_par_nom["lieuNaissance"]["valeur"] == "Ross-Béthio"
    assert champs_par_nom["lieuNaissance"]["source"] == "dialogue"
    # prenomEnfant n'a pas de correspondance 1:1 fiable depuis nom_enfant -> vide, manuel
    assert champs_par_nom["prenomEnfant"]["valeur"] is None
    assert champs_par_nom["prenomEnfant"]["source"] == "manuel"
    print("✅ Pré-remplissage correct : source='dialogue' seulement pour les correspondances fiables.")

    # --- PATCH : correction du champ prenomEnfant (vide -> valeur manuelle) --
    r_patch = client.patch(
        f"/consultant/dossiers/{dossier['id']}/formulaires/{formulaire['id']}",
        json={"nom": "prenomEnfant", "valeur": "Ibrahima"},
    )
    assert r_patch.status_code == 200, r_patch.text
    print("\n=== Après PATCH prenomEnfant='Ibrahima' ===")
    print(r_patch.json())
    champ_maj = next(c for c in r_patch.json()["champs"] if c["nom"] == "prenomEnfant")
    assert champ_maj["valeur"] == "Ibrahima"
    assert champ_maj["source"] == "manuel"

    # --- PATCH : correction d'un champ qui était déjà source=dialogue --------
    r_patch2 = client.patch(
        f"/consultant/dossiers/{dossier['id']}/formulaires/{formulaire['id']}",
        json={"nom": "dateNaissance", "valeur": "2026-08-10"},
    )
    assert r_patch2.status_code == 200, r_patch2.text
    champ_date = next(c for c in r_patch2.json()["champs"] if c["nom"] == "dateNaissance")
    assert champ_date["valeur"] == "2026-08-10" and champ_date["source"] == "manuel"
    print("✅ Correction d'un champ initialement 'dialogue' -> valeur ET source='manuel' mises à jour.")

    # --- PATCH : bouton "Champ vérifié" seul (pas de changement de valeur) ---
    r_patch3 = client.patch(
        f"/consultant/dossiers/{dossier['id']}/formulaires/{formulaire['id']}",
        json={"nom": "lieuNaissance", "verifie": True},
    )
    assert r_patch3.status_code == 200, r_patch3.text
    champ_lieu = next(c for c in r_patch3.json()["champs"] if c["nom"] == "lieuNaissance")
    assert champ_lieu["verifie_par_consultant"] is True
    assert champ_lieu["valeur"] == "Ross-Béthio" and champ_lieu["source"] == "dialogue", (
        "Le bouton 'vérifié' seul n'aurait jamais dû toucher valeur/source !"
    )
    print("✅ 'Champ vérifié' seul : verifie_par_consultant=true, valeur/source dialogue intactes.")

    # --- Relecture : les modifications persistent -----------------------------
    r_relu = client.get(f"/consultant/dossiers/{dossier['id']}/formulaires")
    champs_relus = {c["nom"]: c for c in r_relu.json()["formulaires"][0]["champs"]}
    assert champs_relus["prenomEnfant"]["valeur"] == "Ibrahima" and champs_relus["prenomEnfant"]["source"] == "manuel"
    assert champs_relus["dateNaissance"]["valeur"] == "2026-08-10" and champs_relus["dateNaissance"]["source"] == "manuel"
    assert champs_relus["lieuNaissance"]["verifie_par_consultant"] is True
    print("\n✅ Relecture après modification : tout persiste avec la bonne source (critère de validation).")

    # --- Erreurs attendues -----------------------------------------------------
    r_400 = client.patch(
        f"/consultant/dossiers/{dossier['id']}/formulaires/{formulaire['id']}", json={"nom": "lieuNaissance"}
    )
    assert r_400.status_code == 400
    r_404_champ = client.patch(
        f"/consultant/dossiers/{dossier['id']}/formulaires/{formulaire['id']}",
        json={"nom": "champ_inexistant", "valeur": "x"},
    )
    assert r_404_champ.status_code == 404
    print("✅ Erreurs (ni valeur ni verifie -> 400 ; champ inexistant -> 404) correctement gérées.")

    print("\n✅ Tâche C.3 : endpoints formulaire OK")


if __name__ == "__main__":
    asyncio.run(main_test())
