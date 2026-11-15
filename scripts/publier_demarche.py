"""
Publier une démarche : figer son état actuel dans une nouvelle version (étape 2.4).

Une démarche se modifie en base (`demarche_champs`, `demarche_documents`,
`demarche_regles`, `demarche_cas`). Ces modifications ne touchent PERSONNE tant
qu'elles ne sont pas publiées : les dialogues en cours travaillent sur la
version sous laquelle ils ont commencé, et les nouveaux dialogues prennent la
dernière version publiée.

    python scripts/publier_demarche.py --voir              # ce qui changerait
    python scripts/publier_demarche.py --publier --par vous@mairie.sn

En attendant l'éditeur web (étape 4), c'est ce script qui joue le rôle du
bouton « Publier ».
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import demarche  # noqa: E402
from services.console import adoucir_sortie  # noqa: E402

# Les symboles « ✓ », « ✗ » et « → » ci-dessous lèvent UnicodeEncodeError sur une
# console Windows en cp1252 : le script meurt alors au milieu de sa sortie, parfois
# en plein message d'erreur. `adoucir_sortie()` remplace le symbole fautif par « ? »
# plutôt que de lever (voir services/console.py pour le choix de `errors="replace"`).
adoucir_sortie()


def _resume(instantane: demarche.Instantane) -> dict:
    return {
        "champs": [c.get("nom_champ") for c in instantane.champs],
        "documents": [d.get("type_document") for d in instantane.documents],
        "regles": [r.get("code") for r in instantane.regles],
        "cas": [(k.get("code"), k.get("condition") or "(par défaut)") for k in instantane.cas],
    }


def principal() -> int:
    analyseur = argparse.ArgumentParser(description="Publier une démarche.")
    analyseur.add_argument("--demarche", default=demarche.TYPE_DEMARCHE_PAR_DEFAUT)
    analyseur.add_argument("--voir", action="store_true", help="comparer sans rien écrire")
    analyseur.add_argument("--publier", action="store_true")
    analyseur.add_argument("--par", help="qui publie (e-mail de l'agent)")
    arguments = analyseur.parse_args()

    vivant = demarche.instantane(arguments.demarche)
    publiee = demarche.instantane(arguments.demarche, vivant.version)

    if not publiee.fige:
        print(f"⚠️  La version {vivant.version} n'a pas d'instantané publié.")
        print("   Appliquez la migration 019, ou publiez pour en créer un.")

    resume_vivant, resume_publie = _resume(vivant), _resume(publiee)
    print(f"Démarche : {arguments.demarche} — version publiée actuelle : {vivant.version}\n")
    for cle in resume_vivant:
        avant, apres = resume_publie[cle], resume_vivant[cle]
        marque = "  " if avant == apres else "→ "
        print(f"{marque}{cle}")
        print(f"     publié : {avant}")
        if avant != apres:
            print(f"     vivant : {apres}")

    if not arguments.publier:
        print("\n(Rien n'a été écrit. Ajoutez --publier pour figer une nouvelle version.)")
        return 0

    if resume_vivant == resume_publie:
        print("\nRien n'a changé : publication inutile.")
        return 0

    nouvelle = demarche.publier(arguments.demarche, par=arguments.par)
    print(f"\n✓ Version {nouvelle} publiée.")
    print("  Les dialogues DÉJÀ commencés gardent leur version : ils ne verront rien changer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
