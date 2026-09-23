"""
Test manuel — Sprint D, Tâche D.1 (validation XSD).

Valide les deux exemples XML fournis (README-MISE-A-JOUR-APP/) contre
templates/extrait_naissance.xsd avec lxml. Ne teste PAS extrait_naissance_v1.xml
(le template) contre le XSD : ce n'est pas une instance, il ne peut et ne doit
pas passer une validation XSD tel quel (cf. commentaire en tête de ce fichier).
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from lxml import etree

XSD_PATH = "templates/extrait_naissance.xsd"
EXEMPLES = [
    "README-MISE-A-JOUR-APP/extrait_naissance_exemple_ordinaire.xml",
    "README-MISE-A-JOUR-APP/extrait_naissance_exemple_suppletif.xml",
]


def main():
    with open(XSD_PATH, "rb") as f:
        schema = etree.XMLSchema(etree.parse(f))

    tous_valides = True
    for chemin in EXEMPLES:
        with open(chemin, "rb") as f:
            doc = etree.parse(f)
        valide = schema.validate(doc)
        statut = "✅ VALIDE" if valide else "❌ INVALIDE"
        print(f"{statut} — {chemin}")
        if not valide:
            tous_valides = False
            for erreur in schema.error_log:
                print(f"    {erreur}")

    if tous_valides:
        print("\n✅ Tâche D.1 : les deux exemples passent la validation XSD sans erreur.")
    else:
        raise SystemExit("❌ Au moins un exemple a échoué la validation.")


if __name__ == "__main__":
    main()
