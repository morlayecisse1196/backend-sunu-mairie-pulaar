"""
Test manuel — Sprint K, Tâche K.4 (POST /consultant/dossiers/{id}/ocr-cni).

Vraie base Supabase + vrai pipeline OCR (K.1/K.2). Image factice (pas une
vraie CNI, cf. limite déjà documentée dans test_ocr_cni_service_k2.py) : ce
test valide le VRAI ROND-TRIP de l'endpoint (400 si document manquant, 200 +
formulaires mis à jour avec les nouveaux champs K.3 sinon) — pas la précision
de détection, qui nécessite une vraie photo.
"""
import io
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import main  # noqa: E402
from dossiers_repo import create_dossier, upload_document
from test_bascule_administratif import TEST_CITOYEN_ID, TEST_COMMUNE

SLOTS_VIDES = {
    "age_enfant": {"valeur": None, "unite": None}, "commune_naissance": None, "nom_enfant": None,
    "date_naissance_enfant": None, "nom_declarant": "Modou Diallo", "nom_mere": None,
    "date_naissance_mere": None, "parents_maries": None,
}


def generer_image_bidon(texte: str) -> bytes:
    img = Image.new("RGB", (640, 400), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 630, 390], outline=(0, 0, 0), width=3)
    draw.text((30, 180), texte, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def main_test():
    client = TestClient(main.app)
    main.app.dependency_overrides[main.get_current_consultant] = lambda: {"id": TEST_CITOYEN_ID, "commune": TEST_COMMUNE}

    dossier = create_dossier(
        citoyen_id=TEST_CITOYEN_ID, type_demarche="extrait_naissance",
        slots=dict(SLOTS_VIDES), cas_legal="dans_les_delais",
        commune_id=main.resoudre_commune_id(TEST_COMMUNE), statut="en_traitement",
    )
    assert dossier, "création du dossier de test échouée"
    dossier_id = dossier["id"]
    print(f"Dossier de test : {dossier_id}\n")

    # --- 1. Sans aucun document CNI -> 400 explicite ---
    r = client.post(f"/consultant/dossiers/{dossier_id}/ocr-cni")
    print(f"Sans documents : {r.status_code} {r.json()}")
    assert r.status_code == 400
    assert "cni_declarant_recto" in r.json()["detail"] and "cni_declarant_verso" in r.json()["detail"]
    print("OK - 400 explicite listant les deux documents manquants.\n")

    # --- 2. Seulement le recto -> 400 (verso manquant) ---
    assert upload_document(dossier_id, "cni_declarant_recto", generer_image_bidon("RECTO"), "image/jpeg", "jpg")
    r = client.post(f"/consultant/dossiers/{dossier_id}/ocr-cni")
    print(f"Recto seul : {r.status_code} {r.json()}")
    assert r.status_code == 400
    assert "cni_declarant_verso" in r.json()["detail"] and "cni_declarant_recto" not in r.json()["detail"]
    print("OK - 400 précis : seul le verso manque désormais.\n")

    # --- 3. Les deux -> 200, formulaires mis à jour ---
    assert upload_document(dossier_id, "cni_declarant_verso", generer_image_bidon("VERSO"), "image/jpeg", "jpg")
    r = client.post(f"/consultant/dossiers/{dossier_id}/ocr-cni")
    print(f"Recto + verso : {r.status_code}")
    assert r.status_code == 200, r.text
    formulaires = r.json()["formulaires"]
    assert len(formulaires) == 2, f"attendu 2 formulaires (recto+verso), obtenu {len(formulaires)}"

    par_type = {f["type_document"]: f for f in formulaires}
    assert "cni_declarant_recto" in par_type and "cni_declarant_verso" in par_type

    noms_recto = {c["nom"] for c in par_type["cni_declarant_recto"]["champs"]}
    noms_verso = {c["nom"] for c in par_type["cni_declarant_verso"]["champs"]}
    print("Champs recto :", sorted(noms_recto))
    print("Champs verso :", sorted(noms_verso))
    assert noms_recto == {
        "nomDeclarant", "prenomsDeclarant", "nomFamilleDeclarant",
        "dateNaissanceDeclarant", "sexeDeclarant", "numeroCNI", "lieuNaissanceDeclarant",
    }, "le mapping K.3 (recto) n'est pas celui attendu"
    assert noms_verso == {
        "regionDeclarant", "departementDeclarant", "arrondissementDeclarant", "communeDeclarant",
        "numeroBureauVoteDeclarant", "ninDeclarant", "numeroElecteurDeclarant", "lieuVoteDeclarant",
    }, "le mapping K.3 (verso) n'est pas celui attendu"

    # nomDeclarant vient du DIALOGUE (slots), jamais écrasé par l'OCR quand
    # l'OCR n'a rien détecté (image factice) — vérifie fusionner_champs_ocr.
    nom_declarant_champ = next(c for c in par_type["cni_declarant_recto"]["champs"] if c["nom"] == "nomDeclarant")
    print("nomDeclarant :", nom_declarant_champ)
    assert nom_declarant_champ["valeur"] == "Modou Diallo"
    assert nom_declarant_champ["source"] == "dialogue"

    print("\nOK - endpoint K.4 valide : mapping K.3 correctement appliqué, valeur dialogue préservée (rien à écraser).")
    print("⚠️  Précision de détection réelle non testée ici (pas de vraie photo CNI disponible).")

    main.app.dependency_overrides.clear()


if __name__ == "__main__":
    main_test()
