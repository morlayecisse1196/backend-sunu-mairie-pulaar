"""
Test manuel — Sprint K, Tâche K.1 (correction du bug de regex doublement
échappées dans model_OCR/cni_extraction_package/cni_pipeline.py).

Critère de validation manuelle explicite (SUNU_MAIRIE_PROMPTS.md, Tâche K.1) :
clean_field/validate_field avec de vraies valeurs — pas besoin du modèle YOLO
ni d'EasyOCR ici, ces deux fonctions sont du code déterministe pur.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, "model_OCR/cni_extraction_package")
from cni_pipeline import clean_field, validate_field  # noqa: E402


def main_test():
    # --- id / bureau / numero / nin : les chiffres doivent SURVIVRE au nettoyage ---
    nettoye = clean_field("id", "123 456 789 0123")
    print(f"clean_field('id', '123 456 789 0123') = {nettoye!r}")
    assert nettoye == "123 456 789 0123", f"les chiffres ont été perdus au nettoyage : {nettoye!r}"
    assert any(c.isdigit() for c in nettoye), "aucun chiffre n'a survécu — bug non corrigé"

    nettoye_bruit = clean_field("nin", "N°: 1 2 3 4 5 6 7 8 9 0 1 2")
    print(f"clean_field('nin', 'N°: 1 2 3...') = {nettoye_bruit!r}")
    assert nettoye_bruit.replace(" ", "").isdigit(), f"du bruit non numérique a survécu : {nettoye_bruit!r}"

    # --- dob : une vraie date doit être reconnue comme valide ---
    valide, _, _ = validate_field("dob", "12/03/1998"), None, None
    print(f"validate_field('dob', '12/03/1998') = {validate_field('dob', '12/03/1998')}")
    assert validate_field("dob", "12/03/1998") is True, "une date correcte est rejetée — bug non corrigé"
    assert validate_field("dob", "date illisible") is False

    # --- sex : extraction propre d'un M/F au milieu de bruit ---
    sexe = clean_field("sex", "SEXE M")
    print(f"clean_field('sex', 'SEXE M') = {sexe!r}")
    assert sexe == "M", f"l'extraction du sexe a échoué : {sexe!r}"

    # --- dp (date) : nettoyage extrait bien la date au milieu de texte parasite ---
    date_nettoyee = clean_field("dp", "Délivré le 05/07/2020 à Dakar")
    print(f"clean_field('dp', 'Délivré le 05/07/2020 à Dakar') = {date_nettoyee!r}")
    assert date_nettoyee == "05/07/2020", f"la date n'a pas été extraite correctement : {date_nettoyee!r}"

    # --- validate_field sur un champ textuel qui contient (à tort) une date -> invalide ---
    assert validate_field("region", "12/03/1998") is False

    print("\nTâche K.1 validée : les regex fonctionnent réellement sur de vraies valeurs.")


if __name__ == "__main__":
    main_test()
