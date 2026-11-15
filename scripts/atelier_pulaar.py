"""
Atelier pulaar en ligne de commande (étape 3.1).

Depuis l'étape 4.2, l'atelier existe dans le web : `/admin/atelier`, avec
l'écoute avant validation — ce qu'un fichier ne peut pas offrir. Ce script
reste utile pour une relecture hors ligne, ou pour faire relire quelqu'un qui
n'a pas de compte.

    python scripts/atelier_pulaar.py --liste
        Ce qui reste à relire, et ce qui est déjà fait.

    python scripts/atelier_pulaar.py --modele phrases.tsv
        Écrit un fichier à remplir : une ligne par phrase, quatre colonnes
        séparées par des tabulations (identifiant, français, pulaar, contexte).
        Ouvrez-le dans un tableur, remplissez la troisième colonne.

    python scripts/atelier_pulaar.py --modele a_relire.tsv --a-relire
        Même chose, mais seulement les phrases PAS ENCORE relues. À préférer
        pour une séance de relecture : rapporter le fichier complet avec
        --valider marquerait relues des phrases que personne n'a revues.

    python scripts/atelier_pulaar.py --importer phrases.tsv
        Relit le fichier et enregistre les traductions remplies. Une ligne
        laissée vide n'écrase rien. RIEN n'est marqué comme validé tant que
        vous n'ajoutez pas --valider.

    python scripts/atelier_pulaar.py --importer phrases.tsv --valider --par vous@mairie.sn
        Même chose, et marque validées les phrases remplies : elles cessent
        alors de passer par le modèle. `--par` inscrit qui a relu.

L'identifiant de la première colonne ne doit jamais être modifié : c'est lui
qui dit où remettre la traduction.

LA LOGIQUE N'EST PAS ICI

Elle est dans `services/atelier.py`, testée. Un script ne se teste pas : c'est
là qu'un gabarit était resté invisible à la relecture pendant deux étapes sans
que rien ne le signale.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import atelier, demarche  # noqa: E402
from services.console import adoucir_sortie  # noqa: E402

adoucir_sortie()

SEPARATEUR = "\t"


def _lister(phrases: list, etat: dict) -> int:
    faites = [p for p in phrases if p.valide and p.pulaar.strip()]
    restantes = [p for p in phrases if not (p.valide and p.pulaar.strip())]

    print(f"{len(faites)} phrase(s) relue(s) sur {len(phrases)}.")
    print(f"{etat['audios_prets']} audio(s) déjà généré(s).\n")
    if restantes:
        print("À relire :")
        for phrase in restantes:
            marque = "traduction déposée, non relue" if phrase.pulaar.strip() else "rien"
            print(f"  [{marque}] {phrase.identifiant}")
            print(f"      {phrase.francais}")
            print(f"      ({phrase.contexte})")
    if faites:
        print("\nDéjà relues :")
        for phrase in faites:
            son = "♪" if phrase.audio_pret else " "
            print(f"  ✓{son} {phrase.identifiant} — {phrase.pulaar[:60]}")
    return 0


def _ecrire_modele(phrases: list, chemin: str) -> int:
    with open(chemin, "w", encoding="utf-8", newline="") as fichier:
        redacteur = csv.writer(fichier, delimiter=SEPARATEUR, quoting=csv.QUOTE_MINIMAL)
        redacteur.writerow(["identifiant", "francais", "pulaar", "contexte"])
        for phrase in phrases:
            redacteur.writerow([phrase.identifiant, phrase.francais, phrase.pulaar, phrase.contexte])
    print(f"✓ {len(phrases)} phrase(s) écrites dans {chemin}")
    print("  Remplissez la colonne « pulaar », puis :")
    print(f"    python scripts/atelier_pulaar.py --importer {chemin}")
    return 0


def _lire_tsv(chemin: str) -> tuple[dict[str, str], list[str]]:
    """
    Les traductions du fichier, et les lignes MAL FORMÉES.

    Le nombre de colonnes est vérifié ligne par ligne. Sans cela, une
    tabulation perdue dans un tableur décale tout : le contexte glisse dans la
    colonne du pulaar, et `csv.DictReader` l'accepte sans broncher. C'est
    arrivé — trois questions du dialogue se sont retrouvées en base avec
    « Question du champ « commune_naissance » » pour traduction, prêtes à être
    lues à voix haute par une synthèse pulaar.
    """
    with open(chemin, encoding="utf-8", newline="") as fichier:
        lignes = list(csv.reader(fichier, delimiter=SEPARATEUR))
    if not lignes:
        return {}, []

    entete = lignes[0]
    attendu = len(entete)
    traductions: dict[str, str] = {}
    malformees: list[str] = []
    for numero, ligne in enumerate(lignes[1:], start=2):
        if len(ligne) != attendu:
            malformees.append(
                f"ligne {numero} : {len(ligne)} colonne(s) au lieu de {attendu}"
                + (f" — {ligne[0]}" if ligne else "")
            )
            continue
        cellules = dict(zip(entete, ligne))
        if (cellules.get("pulaar") or "").strip():
            traductions[cellules["identifiant"]] = cellules["pulaar"]
    return traductions, malformees


def _importer(chemin: str, valider: bool, par: str | None, type_demarche: str) -> int:
    traductions, malformees = _lire_tsv(chemin)
    if malformees:
        # On n'importe RIEN : une colonne décalée range du français dans la
        # colonne du pulaar, et personne ne s'en aperçoit avant le dialogue.
        print(f"✗ {len(malformees)} ligne(s) mal formée(s) — rien n'a été importé :")
        for souci in malformees[:10]:
            print(f"    {souci}")
        print("  Une tabulation a été perdue. Vérifiez que chaque ligne a bien")
        print(f"  {'4'} colonnes séparées par des tabulations.")
        return 2

    try:
        resultat = atelier.enregistrer(
            traductions, valider=valider, par=par, type_demarche=type_demarche
        )
    except ValueError as exc:
        print(f"✗ {exc}")
        print("  La première colonne a-t-elle été modifiée dans le tableur ?")
        return 2

    print(f"✓ {resultat['phrases']} traduction(s) enregistrée(s) sur {resultat['lignes']} ligne(s).")
    if valider:
        print("  Marquées validées : ces phrases ne passent plus par le modèle.")
        print("  Générez leurs audios pour supprimer aussi l'attente de la synthèse :")
        print("    python scripts/pregenerer_audio.py")
    else:
        print("  NON validées : elles ne sont pas encore dites. Relancez avec --valider")
        print("  quand vous les avez ÉCOUTÉES — l'atelier web (/admin/atelier) le fait pour vous.")
    return 0


def principal() -> int:
    analyseur = argparse.ArgumentParser(description="Atelier pulaar.")
    analyseur.add_argument("--demarche", default=demarche.TYPE_DEMARCHE_PAR_DEFAUT)
    analyseur.add_argument("--liste", action="store_true")
    analyseur.add_argument("--modele", metavar="FICHIER")
    analyseur.add_argument("--a-relire", action="store_true",
                           help="avec --modele : n'écrire que les phrases pas encore relues")
    analyseur.add_argument("--importer", metavar="FICHIER")
    analyseur.add_argument("--valider", action="store_true",
                           help="marquer validées les phrases importées")
    analyseur.add_argument("--par", metavar="QUI", help="qui a relu — inscrit dans l'historique")
    arguments = analyseur.parse_args()

    phrases = atelier.collecter(arguments.demarche)
    if not phrases:
        # Ne JAMAIS énoncer une cause qu'on n'a pas vérifiée : une base
        # injoignable et des migrations manquantes se ressemblent d'ici, et
        # envoyer chercher du côté des migrations quand c'est le réseau qui a
        # coupé coûte une soirée.
        echec = demarche.derniere_erreur_lecture()
        if echec:
            # Message volontairement en ASCII : c'est celui qui explique une
            # panne, il ne doit pas en provoquer une autre sur une console
            # Windows en cp1252.
            print("ECHEC : base de donnees injoignable. Ce n'est PAS un probleme de migration.")
            print(f"  {echec}")
            print("  Verifiez la connexion internet, puis relancez la meme commande.")
        else:
            print("✗ Base joignable, mais aucune phrase définie.")
            print("  Les migrations 018 et 020 sont-elles appliquées ?")
        return 2

    if arguments.modele:
        # Sans ce filtre, le modèle contenait les 64 phrases, déjà relues
        # comprises. Or `--importer --valider` marque validée toute ligne
        # REMPLIE : rapporter le fichier entier après n'avoir revu que les
        # nouvelles revalidait les anciennes sans que personne ne les ait
        # relues, et l'historique d'atelier enregistrait cette relecture
        # comme si elle avait eu lieu.
        a_ecrire = [p for p in phrases if not p.valide] if arguments.a_relire else phrases
        if arguments.a_relire and not a_ecrire:
            print("Rien à relire : toutes les phrases sont déjà validées.")
            return 0
        return _ecrire_modele(a_ecrire, arguments.modele)
    if arguments.importer:
        return _importer(arguments.importer, arguments.valider, arguments.par, arguments.demarche)
    return _lister(phrases, atelier.avancement(arguments.demarche))


if __name__ == "__main__":
    raise SystemExit(principal())
