"""
Pré-génère l'audio pulaar des phrases d'interface (services/catalogue_audio.py).

Pourquoi : la première écoute d'une phrase déclenche une traduction + une
synthèse (plusieurs dizaines de secondes, service pouvant démarrer à froid).
Un citoyen qui ne sait pas lire attendrait ce délai devant un écran muet. On
génère donc tout AVANT la mise en production ; ensuite tout est servi depuis
`audio_cache/ui/`.

Utilisation, depuis la racine du backend :

    python scripts/generer_catalogue_audio.py            # ce qui manque seulement
    python scripts/generer_catalogue_audio.py --forcer   # tout regénérer
    python scripts/generer_catalogue_audio.py --cles accueil aide

Ce script appelle de VRAIS services distants (OpenRouter, TTS) : il consomme du
quota et n'a rien à faire en CI.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import catalogue_audio, llm  # noqa: E402
from services.console import adoucir_sortie  # noqa: E402

# La console Windows écrit en cp1252 : les « ✓ », « ✗ » et « → » des messages
# ci-dessous y lèvent UnicodeEncodeError. Le script mourait donc APRÈS avoir
# généré et écrit la première phrase, en essayant d'annoncer sa réussite — si
# bien qu'il n'a jamais pu produire le catalogue sur cette plateforme, et que
# `audio_cache/ui/` est resté vide. Il faut appeler ceci AVANT le premier print.
adoucir_sortie()


async def generer(cles: list[str], forcer: bool) -> int:
    echecs = 0
    for numero, cle in enumerate(cles, start=1):
        if not forcer and catalogue_audio.existe(cle):
            print(f"[{numero}/{len(cles)}] {cle} : déjà en cache")
            continue
        if forcer:
            try:
                os.remove(catalogue_audio.chemin_fichier(cle))
            except FileNotFoundError:
                pass
        print(f"[{numero}/{len(cles)}] {cle} : génération…", flush=True)
        try:
            audio = await catalogue_audio.audio_interface(cle)
        except Exception as exc:  # noqa: BLE001 — un échec ne doit pas arrêter les suivants
            echecs += 1
            print(f"    ✗ échec ({type(exc).__name__}: {exc})")
            continue
        if not audio:
            echecs += 1
            print("    ✗ aucun audio produit")
            continue
        print(f"    ✓ {len(audio)} octets → {catalogue_audio.chemin_fichier(cle)}")
    return echecs


async def principal() -> int:
    analyseur = argparse.ArgumentParser(description="Pré-génération du catalogue audio d'interface.")
    analyseur.add_argument("--forcer", action="store_true", help="regénérer même si le fichier existe")
    analyseur.add_argument("--cles", nargs="*", help="clés à générer (toutes par défaut)")
    arguments = analyseur.parse_args()

    cles = arguments.cles or sorted(catalogue_audio.PHRASES)
    inconnues = [cle for cle in cles if cle not in catalogue_audio.PHRASES]
    if inconnues:
        print(f"Clés inconnues : {inconnues}\nClés disponibles : {sorted(catalogue_audio.PHRASES)}")
        return 2

    try:
        echecs = await generer(cles, arguments.forcer)
    finally:
        await llm.fermer()

    print()
    print(f"Terminé : {len(cles) - echecs}/{len(cles)} phrase(s) disponibles dans {catalogue_audio.DOSSIER_CACHE}")
    return 1 if echecs else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(principal()))
