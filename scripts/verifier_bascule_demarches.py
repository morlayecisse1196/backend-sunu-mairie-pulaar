"""
Quelles démarches du catalogue déclenchent le dialogue guidé ? (étape 2.3)

À VÉRIFIER APRÈS LA MIGRATION 018. La bascule en mode administratif se faisait
sur le mot « naissance » trouvé n'importe où dans le nom de la démarche. Elle se
fait maintenant sur les mots-clés déclarés dans `demarche_definitions`.

C'est plus juste — « certificat de naissance » ne bascule plus à tort vers
l'extrait de naissance — mais cela dépend des noms RÉELS de votre table
`demarches`. Si aucun ne contient un mot-clé déclaré, plus aucune bascule
n'aurait lieu. Ce script le dit avant que ça n'arrive à un citoyen.

    python scripts/verifier_bascule_demarches.py

Corriger, le cas échéant, ne demande aucun code :

    update demarche_definitions
    set mots_cles = mots_cles || array['le nom réel']
    where type_demarche = 'extrait_naissance';
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from demarches_repo import list_demarches  # noqa: E402
from services import demarche  # noqa: E402


def principal() -> int:
    definitions = demarche.demarches_traitables()
    print("Démarches que le dialogue guidé sait mener :")
    for d in definitions:
        origine = "base" if d.en_base else "REPLI (migration 018 non appliquée ?)"
        print(f"  - {d.type_demarche} [{origine}] mots-clés : {list(d.mots_cles) or '(aucun)'}")

    try:
        catalogue = list_demarches()
    except Exception as exc:  # noqa: BLE001
        print(f"\n✗ Catalogue `demarches` illisible ({exc}).")
        return 2

    reconnues, ignorees = [], []
    for ligne in catalogue:
        nom = ligne.get("nom_demarche") or ligne.get("nom") or ""
        trouvee = demarche.reconnaitre_demarche(nom)
        (reconnues if trouvee else ignorees).append((nom, trouvee))

    print(f"\n{len(reconnues)} démarche(s) du catalogue déclenchent le dialogue guidé :")
    for nom, trouvee in sorted(reconnues):
        print(f"  ✓ {nom}  ->  {trouvee.type_demarche}")

    print(f"\n{len(ignorees)} démarche(s) restent en mode information :")
    for nom, _ in sorted(ignorees):
        print(f"    {nom}")

    if not reconnues:
        print("\n⚠️  AUCUNE démarche reconnue : le dialogue guidé ne se déclencherait jamais.")
        print("    Ajoutez le nom réel aux `mots_cles` de demarche_definitions.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
