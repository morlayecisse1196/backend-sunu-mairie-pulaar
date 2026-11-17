"""
Les quatre matrices d'embeddings divergent-elles VRAIMENT ?

POURQUOI LA QUESTION DÉCIDE DE TOUT

Le modèle pèse 5,6 Go au lieu de 2,4 parce qu'il stocke quatre fois la matrice
d'embeddings (262 M paramètres chacune) :

    model.shared.weight
    model.encoder.embed_tokens.weight
    model.decoder.embed_tokens.weight
    lm_head.weight

Si elles sont IDENTIQUES, on peut n'en garder qu'une et relier les poids : le
modèle est strictement le même, en deux fois moins lourd. C'est la
déduplication.

Si elles DIVERGENT — ce que le README affirme —, les relier CHANGERAIT le
modèle : le fine-tuning les aurait mises à jour séparément, faute de liaison.
Il faudrait alors les garder toutes et se contenter du bfloat16.

On ne peut pas trancher sans mesurer. `safetensors` permet de lire tenseur par
tenseur, et même tranche par tranche : on compare donc sans jamais charger les
quatre matrices à la fois — la machine n'a pas la mémoire pour.
"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

import torch  # noqa: E402
from safetensors import safe_open  # noqa: E402

CHEMIN = "/opt/sunu/modeles/francais-pulaar/model.safetensors"
MATRICES = [
    "model.shared.weight",
    "model.encoder.embed_tokens.weight",
    "model.decoder.embed_tokens.weight",
    "lm_head.weight",
]
LIGNES_PAR_TRANCHE = 8192


def main() -> None:
    with safe_open(CHEMIN, framework="pt", device="cpu") as f:
        presentes = [n for n in MATRICES if n in f.keys()]
        print(f"Tenseurs du fichier : {len(f.keys())}")
        for nom in MATRICES:
            if nom in f.keys():
                tranche = f.get_slice(nom)
                print(f"  {nom:<40} {tranche.get_shape()}  {tranche.get_dtype()}")
            else:
                print(f"  {nom:<40} ABSENT")

        if len(presentes) < 2:
            print("\nUne seule matrice : rien à dédupliquer.")
            return

        reference = presentes[0]
        forme = f.get_slice(reference).get_shape()
        lignes = forme[0]
        print(f"\nComparaison à « {reference} », par tranches de {LIGNES_PAR_TRANCHE} lignes :")

        for autre in presentes[1:]:
            ecart_max = 0.0
            lignes_differentes = 0
            identique = True
            for debut in range(0, lignes, LIGNES_PAR_TRANCHE):
                fin = min(debut + LIGNES_PAR_TRANCHE, lignes)
                a = f.get_slice(reference)[debut:fin].float()
                b = f.get_slice(autre)[debut:fin].float()
                diff = (a - b).abs()
                ecart_max = max(ecart_max, float(diff.max()))
                lignes_differentes += int((diff.amax(dim=1) > 0).sum())
                if not torch.equal(a, b):
                    identique = False
                del a, b, diff
            part = 100.0 * lignes_differentes / lignes
            verdict = "IDENTIQUE" if identique else f"DIFFÈRE sur {lignes_differentes}/{lignes} lignes ({part:.1f} %)"
            print(f"  {autre:<40} {verdict}   écart max {ecart_max:.3e}")


main()
