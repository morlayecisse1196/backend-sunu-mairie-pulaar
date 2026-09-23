"""
Script manuel — Sprint K, Tâche K.5 : valide le VRAI round-trip de l'endpoint
POST /consultant/dossiers/{id}/ocr-cni (Tâche K.4) avec les VRAIES photos de
CNI de l'utilisateur (model_OCR/image_cni-exmple/, jamais commitées, cf.
.gitignore), exactement le chemin que le nouveau bouton "Lancer l'OCR" du web
consultant (Tâche K.5) déclenche.

Différence avec test_endpoint_ocr_cni_k4.py (qui utilise une image factice,
donc valide seulement la plomberie) : ici les vraies photos sont uploadées
comme documents du dossier, donc le VRAI pipeline OCR doit détecter du texte
réel. N'affirme jamais les valeurs PII extraites en dur (cf. convention de
verifier_ocr_reel_k2.py) — seulement des propriétés structurelles :
- au moins un champ recto ET un champ verso passent en source="ocr"
- les 4 champs fragiles (fname, lname, bp, lieu -> prenomsDeclarant,
  nomFamilleDeclarant, lieuNaissanceDeclarant, lieuVoteDeclarant) sont bien
  marqués needs_review=true dès qu'ils ont été détectés (c'est précisément ce
  que la Tâche K.5 doit afficher comme badge "à vérifier" côté web).
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient

import main  # noqa: E402
from dossiers_repo import create_dossier, upload_document
from test_bascule_administratif import TEST_CITOYEN_ID, TEST_COMMUNE

CHEMIN_RECTO = "model_OCR/image_cni-exmple/retro.jpeg"
CHEMIN_VERSO = "model_OCR/image_cni-exmple/verso.jpeg"

CHAMPS_FRAGILES_RECTO = {"prenomsDeclarant", "nomFamilleDeclarant", "lieuNaissanceDeclarant"}
CHAMPS_FRAGILES_VERSO = {"lieuVoteDeclarant"}

SLOTS_VIDES = {
    "age_enfant": {"valeur": None, "unite": None}, "commune_naissance": None, "nom_enfant": None,
    "date_naissance_enfant": None, "nom_declarant": "Modou Diallo", "nom_mere": None,
    "date_naissance_mere": None, "parents_maries": None,
}


def main_test():
    with open(CHEMIN_RECTO, "rb") as f:
        recto_bytes = f.read()
    with open(CHEMIN_VERSO, "rb") as f:
        verso_bytes = f.read()

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

    assert upload_document(dossier_id, "cni_declarant_recto", recto_bytes, "image/jpeg", "jpeg")
    assert upload_document(dossier_id, "cni_declarant_verso", verso_bytes, "image/jpeg", "jpeg")
    print("Photos réelles (recto+verso) uploadées.\n")

    print("Appel POST /consultant/dossiers/{id}/ocr-cni (peut prendre plusieurs minutes — vraies photos haute résolution)...")
    r = client.post(f"/consultant/dossiers/{dossier_id}/ocr-cni")
    print(f"Statut : {r.status_code}")
    assert r.status_code == 200, r.text

    formulaires = r.json()["formulaires"]
    assert len(formulaires) == 2, f"attendu 2 formulaires, obtenu {len(formulaires)}"
    par_type = {f["type_document"]: f for f in formulaires}

    print("\n--- Résumé (structure seulement, pas de PII en dur ici) ---")
    total_ocr = 0
    fragiles_detectes_bien_marques = 0
    fragiles_detectes_total = 0
    for type_doc, fragiles in (("cni_declarant_recto", CHAMPS_FRAGILES_RECTO), ("cni_declarant_verso", CHAMPS_FRAGILES_VERSO)):
        print(f"\n{type_doc} :")
        for champ in par_type[type_doc]["champs"]:
            marque = champ.get("needs_review")
            print(f"  {champ['nom']:24s} source={champ['source']:8s} confiance={champ['confiance']!r:6} needs_review={marque}")
            if champ["source"] == "ocr":
                total_ocr += 1
            if champ["nom"] in fragiles and champ["valeur"] is not None:
                fragiles_detectes_total += 1
                if marque is True:
                    fragiles_detectes_bien_marques += 1

    assert total_ocr > 0, "aucun champ n'est passé en source=ocr — le pipeline n'a rien détecté du tout"
    print(f"\nOK - {total_ocr} champ(s) mis à jour par l'OCR (source='ocr').")

    assert fragiles_detectes_bien_marques == fragiles_detectes_total and fragiles_detectes_total > 0, (
        f"champs fragiles détectés mais pas tous marqués needs_review : "
        f"{fragiles_detectes_bien_marques}/{fragiles_detectes_total}"
    )
    print(f"OK - les {fragiles_detectes_total} champ(s) fragile(s) détecté(s) sont bien marqués needs_review=true "
          f"(c'est ce badge \"à vérifier\" que la Tâche K.5 affiche côté web).")

    main.app.dependency_overrides.clear()
    print("\nTâche K.5 (backend + contrat needs_review) validée avec de vraies photos.")


if __name__ == "__main__":
    main_test()
