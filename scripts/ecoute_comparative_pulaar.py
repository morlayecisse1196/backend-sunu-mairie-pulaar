"""
Écoute comparative « avant / après » de l'orthographe de synthèse (étape 1.4).

Produit, pour chaque phrase type, DEUX fichiers audio :

    avant_1.wav   la phrase telle qu'elle partait au synthétiseur jusqu'ici
    apres_1.wav   la même, réécrite par `services.pulaar.orthographe_tts`

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

from services.pulaar import orthographe_tts  # noqa: E402
from tts_client import TTSError  # noqa: E402
import tts_client  # noqa: E402

DOSSIER_PAR_DEFAUT = os.path.join("audio", "comparatif_pulaar")

#: Phrases types : chacune contient au moins un terme administratif, seule
#: partie que l'orthographe de synthèse modifie. Les cinq premières sont celles
#: de la première écoute (2026-09-19, jugées concluantes) — gardées telles
#: quelles pour rester comparables ; les suivantes couvrent les termes ajoutés
#: depuis le corpus de traduction.
PHRASES = (
    "Salam. So aɗa yiɗi ekstere jibinannde, yah to mairie.",
    "Aɗa soklii pièce d'identité maa e 200 francs.",
    "Addu certificat de naissance e livret de famille.",
    "Dossier maa arii to état civil commune maa.",
    "So neɗɗo maayii, addu certificat médical.",
    "Ngam certificat de résidence, addu photocopie e timbre.",
    "Certificat d'indigence no weeri, kono addu carte d'identité maa.",
    "So aɗa yiɗi permis de construire, addu plan maison maa.",
)


async def _synthetiser_brut(texte: str) -> bytes:
    """Synthèse SANS l'orthographe adaptée — l'état « avant »."""
    # `synthesize_remote` applique désormais la réécriture ; pour l'« avant » on
    # neutralise donc la fonction le temps de l'appel.
    reecriture = tts_client.orthographe_tts
    tts_client.orthographe_tts = lambda t: t
    try:
        return await tts_client.synthesize_remote(texte)
    finally:
        tts_client.orthographe_tts = reecriture


async def principal() -> int:
    analyseur = argparse.ArgumentParser(description="Écoute comparative avant / après.")
    analyseur.add_argument("--dossier", default=DOSSIER_PAR_DEFAUT)
    arguments = analyseur.parse_args()
    os.makedirs(arguments.dossier, exist_ok=True)

    echecs = 0
    for numero, phrase in enumerate(PHRASES, start=1):
        apres_texte = orthographe_tts(phrase)
        print(f"\n[{numero}/{len(PHRASES)}]")
        print(f"  avant : {phrase}")
        print(f"  après : {apres_texte}")
        if apres_texte == phrase:
            print("  (identique : aucun terme du glossaire dans cette phrase)")

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
