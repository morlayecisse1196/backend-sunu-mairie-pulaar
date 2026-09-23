"""
Pré-génération des audios des phrases relues (étape 3.4).

POURQUOI

L'étape 3.3 a supprimé l'appel au traducteur pour une phrase déjà relue.
Restait la synthèse. Le Space vocal met plusieurs dizaines de secondes à
repartir après une inactivité : le premier citoyen de la matinée pose sa
question et n'entend rien, devant un écran qu'il ne sait pas lire. Une phrase
écrite en base depuis des mois n'a pourtant aucune raison d'être resynthétisée.

Ce script parcourt toutes les phrases dont le pulaar est RELU, synthétise
celles qui n'ont pas encore leur audio, et les range sur le disque
(`audio_cache/phrases/`). À lancer après chaque séance de relecture.

    python scripts/pregenerer_audio.py --verifier
        Ce qui manque, sans rien synthétiser. À lancer d'abord : dit combien
        d'appels au Space vocal la génération va coûter.

    python scripts/pregenerer_audio.py
        Synthétise ce qui manque. Interrompre et relancer est sans danger :
        ce qui est déjà fait n'est pas refait.

    python scripts/pregenerer_audio.py --nettoyer
        Supprime les audios qui ne correspondent plus à aucune phrase — ceux
        laissés derrière par une correction de texte.

CE QUI N'EST PAS PRÉ-GÉNÉRÉ

  * Une phrase dont le pulaar n'est PAS relu : elle ne sera pas dite en pulaar
    de toute façon (le français repart au traducteur), et sa traduction
    automatique va changer.
  * Les gabarits à trous : leur texte final dépend du dossier du citoyen.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

_RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RACINE)

from services import atelier, catalogue_audio, demarche  # noqa: E402
from services.console import adoucir_sortie  # noqa: E402

adoucir_sortie()
from supabase_client import get_supabase_client  # noqa: E402
from tts_client import NARRATION_TIMEOUT_SECONDS, TTSError, synthesize_remote  # noqa: E402

def _a_generer(type_demarche: str) -> tuple[list, int]:
    """Les phrases relues, et le nombre de phrases écartées faute de relecture."""
    retenues: list = []
    en_attente = 0
    for phrase in atelier.collecter(type_demarche):
        if phrase.cible.table == "demarche_gabarits":
            continue  # texte à trous : impossible à pré-générer
        if not phrase.pulaar.strip():
            continue
        if not phrase.valide:
            en_attente += 1
            continue
        retenues.append(phrase)
    return retenues, en_attente


def _noter_la_cle(phrase, cle: str) -> None:
    """
    Inscrit la clé dans la colonne d'audio, quand la table en a une.

    C'est un INDICATEUR pour l'atelier de relecture, pas la source de ce qui
    est servi : le dialogue retrouve le fichier par l'empreinte du texte.
    """
    cible = phrase.cible
    if cible.index is not None:
        return  # relance ou rappel : pas de colonne, l'empreinte suffit
    colonne_audio = atelier.COLONNE_AUDIO.get(cible.table)
    if colonne_audio is None:
        return
    try:
        get_supabase_client().table(cible.table).update({colonne_audio: cle}).eq(
            cible.colonne_cle, cible.valeur_cle
        ).execute()
    except Exception as exc:  # noqa: BLE001 — l'audio est écrit, c'est l'essentiel
        print(f"   (clé non inscrite en base pour {phrase.identifiant} : {exc})")


async def _generer(lignes: list, *, verifier: bool) -> int:
    manquantes = [p for p in lignes if not catalogue_audio.phrase_deja_generee(p.pulaar)]
    print(f"{len(lignes)} phrase(s) relue(s), {len(manquantes)} sans audio.")
    if verifier:
        for phrase in manquantes:
            print(f"  à synthétiser  {phrase.identifiant:<48} {phrase.pulaar[:60]}")
        return 0

    echecs = 0
    for rang, ligne in enumerate(manquantes, start=1):
        print(f"[{rang}/{len(manquantes)}] {ligne.identifiant}")
        try:
            audio = await synthesize_remote(ligne.pulaar, timeout=NARRATION_TIMEOUT_SECONDS)
        except TTSError as exc:
            # On continue : une phrase manquante coûte une synthèse à la volée,
            # pas un dialogue interrompu. Relancer le script la rattrapera.
            print(f"   échec : {exc}")
            echecs += 1
            continue
        cle = await catalogue_audio.enregistrer_phrase(ligne.pulaar, audio)
        if cle is None:
            print("   échec : audio non écrit sur le disque")
            echecs += 1
            continue
        _noter_la_cle(ligne, cle)
    return echecs


def _nettoyer(lignes: list) -> None:
    """Supprime les audios qui ne disent plus aucune phrase actuelle."""
    dossier = catalogue_audio.DOSSIER_PHRASES
    if not os.path.isdir(dossier):
        print("Aucun audio pré-généré.")
        return
    vivantes = {catalogue_audio.cle_phrase(p.pulaar) + ".wav" for p in lignes}
    orphelins = [f for f in os.listdir(dossier) if f.endswith(".wav") and f not in vivantes]
    for fichier in orphelins:
        os.remove(os.path.join(dossier, fichier))
    print(f"{len(orphelins)} audio(s) périmé(s) supprimé(s).")


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--demarche", default=demarche.TYPE_DEMARCHE_PAR_DEFAUT)
    analyseur.add_argument("--verifier", action="store_true",
                           help="lister ce qui manque, sans rien synthétiser")
    analyseur.add_argument("--nettoyer", action="store_true",
                           help="supprimer les audios qui ne correspondent plus à aucune phrase")
    options = analyseur.parse_args()

    lignes, en_attente = _a_generer(options.demarche)
    if en_attente:
        print(f"{en_attente} phrase(s) traduite(s) mais PAS ENCORE RELUE(S) : ignorées.")

    if options.nettoyer:
        _nettoyer(lignes)
        return 0

    echecs = asyncio.run(_generer(lignes, verifier=options.verifier))
    if echecs:
        print(f"\n{echecs} phrase(s) non synthétisée(s) — relancez le script.")
        return 1
    if not options.verifier:
        print("\nTerminé. Ces phrases ne repasseront plus ni par le traducteur ni par la synthèse.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
