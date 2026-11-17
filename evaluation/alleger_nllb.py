"""
Allège le modèle sans le changer : fp32 -> bfloat16.

POURQUOI PAS LA DÉDUPLICATION

Mesuré sur les poids réels : les quatre matrices d'embeddings diffèrent sur
100 % de leurs lignes, avec des écarts maximaux de 1,6e-2, 1,7e-2 et 1,2e-1.
Le fine-tuning les a bien mises à jour séparément. Les relier ne rendrait donc
PAS le même modèle — surtout `lm_head`, la projection de sortie, qui est la
plus éloignée. La déduplication que le README appelait de ses vœux n'est pas
applicable ici.

POURQUOI LE BFLOAT16 SUFFIT

bfloat16 garde 8 bits de mantisse, soit une précision relative d'environ
0,4 %. Sur des poids de l'ordre de 0,03, l'erreur d'arrondi est de l'ordre de
1e-4 — cent fois plus petite que les écarts entre matrices qu'on veut
préserver. Le modèle garde donc ses quatre matrices distinctes, et pèse deux
fois moins : 5,6 Go -> 2,8 Go, ce qui le rend chargeable ici.

La conversion se fait tenseur par tenseur, en libérant chaque fp32 aussitôt
converti : la machine n'a pas la mémoire pour tenir les deux versions.
"""
from __future__ import annotations

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

import torch  # noqa: E402
from safetensors import safe_open  # noqa: E402
from safetensors.torch import save_file  # noqa: E402

SOURCE = "/opt/sunu/modeles/francais-pulaar"
CIBLE = "/opt/sunu/modeles/francais-pulaar-bf16"


def main() -> None:
    os.makedirs(CIBLE, exist_ok=True)
    chemin_entree = os.path.join(SOURCE, "model.safetensors")

    poids: dict[str, torch.Tensor] = {}
    octets_avant = 0
    with safe_open(chemin_entree, framework="pt", device="cpu") as fichier:
        metadonnees = fichier.metadata() or {}
        noms = list(fichier.keys())
        for index, nom in enumerate(noms, 1):
            tenseur = fichier.get_tensor(nom)
            octets_avant += tenseur.numel() * tenseur.element_size()
            poids[nom] = tenseur.to(torch.bfloat16) if tenseur.is_floating_point() else tenseur
            del tenseur
            if index % 100 == 0 or index == len(noms):
                print(f"  {index}/{len(noms)} tenseurs convertis")

    octets_apres = sum(t.numel() * t.element_size() for t in poids.values())
    save_file(poids, os.path.join(CIBLE, "model.safetensors"), metadata=metadonnees or None)
    del poids

    # Le reste du modèle : tokeniseur et configurations, recopiés tels quels.
    for nom in os.listdir(SOURCE):
        if nom == "model.safetensors" or nom.startswith("."):
            continue
        chemin = os.path.join(SOURCE, nom)
        if os.path.isfile(chemin):
            with open(chemin, "rb") as source, open(os.path.join(CIBLE, nom), "wb") as cible:
                cible.write(source.read())

    # La config doit annoncer le nouveau type, sinon `transformers` recharge en
    # fp32 et l'allègement ne sert à rien.
    chemin_config = os.path.join(CIBLE, "config.json")
    with open(chemin_config, encoding="utf-8") as fichier:
        config = json.load(fichier)
    config["torch_dtype"] = "bfloat16"
    with open(chemin_config, "w", encoding="utf-8") as fichier:
        json.dump(config, fichier, indent=2, ensure_ascii=False)

    print(f"\n  avant : {octets_avant / 1e9:5.2f} Go")
    print(f"  après : {octets_apres / 1e9:5.2f} Go")
    print(f"  sur disque : {os.path.getsize(os.path.join(CIBLE, 'model.safetensors')) / 1e9:5.2f} Go")


main()
