"""
Fiche de validation du glossaire pulaar (étape 1.2 du plan maître).

Imprime le glossaire sous forme de tableau à relire. Les traductions n'ont pas
été écrites par un locuteur natif : tant qu'une entrée est marquée « à valider »,
elle est utilisée par l'agent mais reste une hypothèse.

    python scripts/glossaire_pulaar.py                 # tableau lisible
    python scripts/glossaire_pulaar.py --markdown      # à coller dans un document
    python scripts/glossaire_pulaar.py --a-valider     # seulement ce qui reste

Corriger une entrée = modifier `services/pulaar.py` (champ `pulaar` pour le mot
dit, `prononciation` pour l'orthographe envoyée au synthétiseur) et passer son
`statut` à `VALIDE`.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.pulaar import A_VALIDER, CORPUS, TERMES  # noqa: E402


def principal() -> int:
    analyseur = argparse.ArgumentParser(description="Fiche de validation du glossaire pulaar.")
    analyseur.add_argument("--markdown", action="store_true")
    analyseur.add_argument("--a-valider", action="store_true", help="masquer les entrées déjà validées")
    analyseur.add_argument("--corpus", action="store_true", help="seulement les entrées tirées du corpus")
    arguments = analyseur.parse_args()

    termes = [
        t
        for t in TERMES
        if (not arguments.a_valider or t.statut == A_VALIDER)
        and (not arguments.corpus or t.source == CORPUS)
    ]
    lignes = [
        (
            t.francais,
            t.pulaar,
            t.prononciation or "—",
            "à valider" if t.statut == A_VALIDER else "validé",
            f"corpus ({t.occurrences})" if t.source == CORPUS else "proposition",
            t.note or "",
        )
        for t in termes
    ]
    entetes = ("Français", "Pulaar proposé", "Orthographe synthèse", "Statut", "Source", "Note")

    if arguments.markdown:
        print("| " + " | ".join(entetes) + " |")
        print("|" + "---|" * len(entetes))
        for ligne in lignes:
            print("| " + " | ".join(ligne) + " |")
    else:
        largeurs = [max(len(str(v)) for v in (entetes[i], *(l[i] for l in lignes))) for i in range(len(entetes))]
        trace = lambda vals: print("  ".join(str(v).ljust(largeurs[i]) for i, v in enumerate(vals)).rstrip())  # noqa: E731
        trace(entetes)
        trace(["-" * largeur for largeur in largeurs])
        for ligne in lignes:
            trace(ligne)

    restant = sum(1 for t in TERMES if t.statut == A_VALIDER)
    print(f"\n{restant} entrée(s) sur {len(TERMES)} restent à valider.")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
