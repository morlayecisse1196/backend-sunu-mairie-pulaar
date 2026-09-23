"""
Script manuel — Sprint K, Tâche K.6 : valide que l'assistant LLM consultant
(POST /consultant/dossiers/{id}/analyser, Tâche E.2) signale bien réellement
les champs CNI à faible confiance OCR (< 0.8), maintenant que de VRAIES
données OCR existent (Tâche K.4/K.5) — sans aucune modification de prompt ni
de schéma (SYSTEM_PROMPT_ASSISTANT_CONSULTANT / SCHEMA_ANALYSE_ASSISTANT
inchangés, seul le commentaire obsolète et le calcul d'ocr_disponible ont
été corrigés).

Réutilise le dossier créé par verifier_endpoint_ocr_reel_k5.py (déjà passé
par le vrai pipeline OCR sur les vraies photos de l'utilisateur) plutôt que
d'en recréer un et de relancer l'OCR (plusieurs minutes) : ce dossier a déjà,
en base, des champs réels avec confiance < 0.8 (prenomsDeclarant=0.68,
lieuNaissanceDeclarant=0.77, regionDeclarant=0.5).
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient

import main  # noqa: E402
from test_bascule_administratif import TEST_CITOYEN_ID, TEST_COMMUNE

DOSSIER_ID = sys.argv[1] if len(sys.argv) > 1 else None
assert DOSSIER_ID, "Usage : python verifier_assistant_ocr_reel_k6.py <dossier_id>"


def main_test():
    client = TestClient(main.app)
    main.app.dependency_overrides[main.get_current_consultant] = lambda: {"id": TEST_CITOYEN_ID, "commune": TEST_COMMUNE}

    # Champs réellement < 0.8 dans ce dossier (confirmé par verifier_endpoint_ocr_reel_k5.py).
    champs_faible_confiance = {"prenomsDeclarant", "lieuNaissanceDeclarant", "regionDeclarant"}

    r = client.post(f"/consultant/dossiers/{DOSSIER_ID}/analyser")
    print(f"Statut : {r.status_code}")
    assert r.status_code == 200, r.text
    analyse = r.json()

    print("\nocr_disponible :", analyse["ocr_disponible"])
    assert analyse["ocr_disponible"] is True, "ce dossier a des champs source='ocr' — ocr_disponible devrait être true"
    print("OK - ocr_disponible reflète maintenant le vrai état du dossier (bug du drapeau figé à false corrigé).")

    print("\nresume :", analyse["resume"])
    print("\nchamps_a_verifier :", analyse["champs_a_verifier"])
    print("\nincoherences :")
    for i in analyse["incoherences"]:
        print(" -", i)

    champs_signales = set(analyse["champs_a_verifier"]) | {
        i["champ"] for i in analyse["incoherences"] if i.get("champ")
    }
    intersection = champs_faible_confiance & champs_signales
    print(f"\nChamps à faible confiance réellement signalés par le LLM : {intersection or 'AUCUN'}")
    assert intersection, (
        f"aucun des champs à faible confiance réelle {champs_faible_confiance} n'apparaît dans "
        f"champs_a_verifier ni incoherences ({champs_signales}) — le point 3 du prompt système "
        f"(Identifier les champs à faible confiance OCR < 0.8) ne fonctionne pas réellement"
    )

    print("\nOK - Tâche K.6 validée : le signal confiance OCR fonctionne réellement avec de vraies données,"
          " sans modification de prompt/schéma.")

    main.app.dependency_overrides.clear()


if __name__ == "__main__":
    main_test()
