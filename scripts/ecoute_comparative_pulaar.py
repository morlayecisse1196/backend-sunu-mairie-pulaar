"""
Écoute comparative « avant / après » de la préparation du texte de synthèse.

Produit, pour chaque phrase type, DEUX fichiers audio :

    avant_1.wav   la phrase telle qu'elle partait au synthétiseur jusqu'ici
    apres_1.wav   la même, préparée par `services.pulaar.texte_pour_synthese`

Le jugement appartient à l'oreille : si « après » n'est pas meilleur, la piste
est mauvaise et on ne va pas plus loin dans cette direction (règle du plan
maître, étape 1).

Utilisation, depuis la racine du backend :

    python scripts/ecoute_comparative_pulaar.py
    python scripts/ecoute_comparative_pulaar.py --dossier audio/comparatif

Ce script appelle le VRAI service de synthèse distant : il consomme du quota et
n'a rien à faire en CI.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.pulaar import texte_pour_synthese  # noqa: E402
from tts_client import TTSError  # noqa: E402
import tts_client  # noqa: E402
from services.console import adoucir_sortie  # noqa: E402

# Les symboles « ✓ », « ✗ » et « → » ci-dessous lèvent UnicodeEncodeError sur une
# console Windows en cp1252 : le script meurt alors au milieu de sa sortie, parfois
# en plein message d'erreur. `adoucir_sortie()` remplace le symbole fautif par « ? »
# plutôt que de lever (voir services/console.py pour le choix de `errors="replace"`).
adoucir_sortie()

DOSSIER_PAR_DEFAUT = os.path.join("audio", "comparatif_pulaar")

#: Phrases types : chacune contient au moins un terme administratif ou un
#: nombre, les deux seules parties que la préparation modifie. Les cinq
#: premières sont celles de la première écoute (2026-09-19, jugées
#: concluantes) — gardées telles quelles pour rester comparables ; les
#: suivantes couvrent les termes ajoutés depuis le corpus de traduction.
PHRASES = (
    "Salam. So aɗa yiɗi ekstere jibinannde, yah to mairie.",
    "Aɗa soklii pièce d'identité maa e 200 francs.",
    "Addu certificat de naissance e livret de famille.",
    "Dossier maa arii to état civil commune maa.",
    "So neɗɗo maayii, addu certificat médical.",
    "Ngam certificat de résidence, addu photocopie e timbre.",
    "Certificat d'indigence no weeri, kono addu carte d'identité maa.",
    "So aɗa yiɗi permis de construire, addu plan maison maa.",
    # Les chiffres : c'est le défaut le plus lourd, puisqu'aucun des dix
    # caractères n'est réellement prononcé par le modèle. Une date, un
    # montant, un numéro de suivi — les trois formes que le citoyen doit
    # confirmer à l'oreille.
    "Jibinaaɗo 2026-09-07 e Dakar.",
    "Numéro de suivi maa ko SM-2026-000452.",
    "Aɗa soklii 1 500 francs CFA ngam dossier maa.",
)


async def _synthetiser_brut(texte: str) -> bytes:
    """Synthèse SANS aucune préparation du texte — l'état « avant »."""
    # `synthesize_remote` prépare désormais le texte ; pour l'« avant » on
    # neutralise donc la fonction le temps de l'appel.
    preparation = tts_client.texte_pour_synthese
    tts_client.texte_pour_synthese = lambda t: t
    try:
        return await tts_client.synthesize_remote(texte)
    finally:
        tts_client.texte_pour_synthese = preparation


async def principal() -> int:
    analyseur = argparse.ArgumentParser(description="Écoute comparative avant / après.")
    analyseur.add_argument("--dossier", default=DOSSIER_PAR_DEFAUT)
    arguments = analyseur.parse_args()
    os.makedirs(arguments.dossier, exist_ok=True)

    echecs = 0
    for numero, phrase in enumerate(PHRASES, start=1):
        apres_texte = texte_pour_synthese(phrase)
        print(f"\n[{numero}/{len(PHRASES)}]")
        print(f"  avant : {phrase}")
        print(f"  après : {apres_texte}")
        if apres_texte == phrase:
            print("  (identique : ni terme du glossaire ni chiffre dans cette phrase)")

        for etiquette, texte, synthese in (
            ("avant", phrase, _synthetiser_brut),
            ("apres", phrase, lambda t: tts_client.synthesize_remote(t)),
        ):
            chemin = os.path.join(arguments.dossier, f"{etiquette}_{numero}.wav")
            try:
                audio = await synthese(texte)
            except TTSError as exc:
                echecs += 1
                print(f"  ✗ {etiquette} : {exc}")
                continue
            with open(chemin, "wb") as fichier:
                fichier.write(audio)
            print(f"  ✓ {etiquette} → {chemin} ({len(audio)} octets)")

    print(f"\nÉcoutez les paires dans {arguments.dossier}.")
    return 1 if echecs else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(principal()))
