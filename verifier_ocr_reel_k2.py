"""
Script manuel — Sprint K, Tâche K.2 : validation de la DÉTECTION RÉELLE (pas
seulement la plomberie, cf. test_ocr_cni_service_k2.py) avec de vraies photos
de CNI, fournies par l'utilisateur dans model_OCR/image_cni-exmple/ (recto:
retro.jpeg, verso: verso.jpeg — jamais commitées, cf. .gitignore, PII réelle).

N'affirme jamais que l'extraction est "correcte" tout seul — imprime chaque
champ (valeur nettoyée, confiance, is_valid_format, needs_review) pour
comparaison manuelle avec les photos par l'utilisateur.
"""
import asyncio
import json
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

import ocr_cni_service

CHEMIN_RECTO = "model_OCR/image_cni-exmple/retro.jpeg"
CHEMIN_VERSO = "model_OCR/image_cni-exmple/verso.jpeg"


async def main_test():
    with open(CHEMIN_RECTO, "rb") as f:
        recto_bytes = f.read()
    with open(CHEMIN_VERSO, "rb") as f:
        verso_bytes = f.read()

    print(f"Recto : {len(recto_bytes)} octets, Verso : {len(verso_bytes)} octets\n")

    resultat = await ocr_cni_service.extraire_cni(recto_bytes, verso_bytes)

    print(json.dumps(resultat, indent=2, ensure_ascii=False))

    print("\n--- Résumé lisible ---")
    for classe, entree in resultat.items():
        valeur = entree["value_cleaned"]
        conf = entree["confidence_detection"]
        review = "⚠️ À VÉRIFIER" if entree["needs_review"] else "✅"
        valide = "valide" if entree["is_valid_format"] else "FORMAT INVALIDE"
        print(f"  {classe:8s} ({entree['source'] or '-':6s}) = {valeur!r:40s}  conf={conf}  {valide}  {review}")


if __name__ == "__main__":
    asyncio.run(main_test())
