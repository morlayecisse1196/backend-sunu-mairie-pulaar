"""
Test manuel — Sprint E, Tâche E.1 (prompt système de l'agent assistant).

Le critère de validation ("aucune règle omise ou reformulée") est vérifié
littéralement ici, pas juste à l'œil : extrait le bloc de code fenced sous
Flux_Consultant_Generation_Document_SUNU-MAIRIE.md §4 et le compare
caractère pour caractère à SYSTEM_PROMPT_ASSISTANT_CONSULTANT.

Teste aussi build_assistant_consultant_prompt() sur un dossier réel (Tâche
C.2, même format de sortie).
"""
import re
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from prompts import SYSTEM_PROMPT_ASSISTANT_CONSULTANT, build_assistant_consultant_prompt

SOURCE_MD = "README-MISE-A-JOUR-APP/Flux_Consultant_Generation_Document_SUNU-MAIRIE.md"


def extraire_bloc_source() -> str:
    with open(SOURCE_MD, "r", encoding="utf-8") as f:
        contenu = f.read()
    # Section "## 4. ..." jusqu'à la prochaine section "## "
    section = re.search(r"## 4\. Rôle de l'agent LLM assistant.*?\n(.*?)\n## 5\.", contenu, re.DOTALL).group(1)
    bloc = re.search(r"```\n(.*?)\n```", section, re.DOTALL).group(1)
    return bloc.strip()


def main_test():
    source = extraire_bloc_source()
    copie = SYSTEM_PROMPT_ASSISTANT_CONSULTANT.strip()

    print("=== Comparaison littérale source §4 vs SYSTEM_PROMPT_ASSISTANT_CONSULTANT ===")
    if source == copie:
        print("✅ IDENTIQUE caractère pour caractère — aucune règle omise ou reformulée.")
    else:
        print("❌ DIFFÉRENCE DÉTECTÉE :")
        import difflib
        for ligne in difflib.unified_diff(source.splitlines(), copie.splitlines(), "source_§4", "prompts.py", lineterm=""):
            print(ligne)
        raise AssertionError("Le prompt copié diverge du texte source §4 — voir diff ci-dessus.")

    # Sanity check supplémentaire : les 6 points numérotés + la phrase finale
    # doivent tous être présents (redondant avec la comparaison exacte
    # ci-dessus, mais rend l'intention du test explicite).
    for fragment in [
        "1. Résumer le dossier en 3-4 phrases claires.",
        "jamais unilatéralement",
        "6. Ne modifie jamais un champ du dossier directement",
        'Ne génère aucune conclusion du type "ce dossier est valide"',
    ]:
        assert fragment in copie, f"Fragment attendu absent : {fragment!r}"
    print("✅ Les 6 règles + la contrainte finale sont toutes présentes.")

    # --- build_assistant_consultant_prompt sur un dossier réel -----------------
    print("\n=== build_assistant_consultant_prompt() ===")
    dossier_exemple = {
        "dossier": {
            "id": "abc-123", "numero_suivi": "SM-2026-000452", "type_demarche": "extrait_naissance",
            "cas_legal": "dans_les_delais", "statut": "en_traitement",
            "slots": {"nom_enfant": "Ibrahima Diallo", "commune_naissance": "Tambacounda"},
        },
        "documents": [],
        "document_formulaires": [
            {
                "type_document": "certificat_naissance", "statut": "rempli",
                "champs": [
                    {"nom": "prenomEnfant", "valeur": "Ibrahima", "source": "manuel", "confiance": None, "verifie_par_consultant": False},
                    {"nom": "sexe", "valeur": None, "source": "manuel", "confiance": None, "verifie_par_consultant": False},
                ],
            }
        ],
    }
    texte = build_assistant_consultant_prompt(dossier_exemple)
    print(texte)
    assert "SM-2026-000452" in texte
    assert "dans_les_delais" in texte
    assert "Ibrahima Diallo" in texte
    assert "prenomEnfant" in texte and "absente (pas d'OCR en V1)" in texte
    print("\n✅ Sérialisation correcte (dossier + slots + formulaires).")

    print("\n✅ Tâche E.1 : prompt assistant consultant OK")


if __name__ == "__main__":
    main_test()
