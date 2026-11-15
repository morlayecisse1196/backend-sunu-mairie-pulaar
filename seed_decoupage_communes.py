"""
Renseigne le découpage administratif et les coordonnées des communes.

POURQUOI UN SCRIPT PLUTÔT QUE L'ÉCRAN D'ADMINISTRATION

L'écran `/admin/communes/{id}` fait très bien le travail et journalise au nom
de l'administrateur connecté. Ce script existe pour la saisie initiale, quand
personne n'a encore de session admin ouverte — et pour que les valeurs posées
soient relisibles dans un fichier plutôt que tapées une fois dans un
formulaire.

Il journalise quand même dans `journal_audit`, avec `acteur_id = NULL` et un
`details.source` qui dit explicitement que l'écriture vient d'un script : une
ligne d'audit qui se ferait passer pour une action d'écran serait pire que
pas de ligne du tout.

CE QUI EST SÛR ET CE QUI NE L'EST PAS

Le découpage (région, département, arrondissement) est **imprimé sur l'acte**.
Une erreur y est une mention fausse sur un document d'état civil : ces valeurs
doivent être justes.

Les coordonnées ne sont **jamais imprimées**. Elles servent uniquement à
`GET /communes/proche`, qui classe les communes par distance pour qu'un
citoyen qui ne lit pas confirme la sienne à l'oral. Une approximation de
quelques centaines de mètres n'a aucun effet visible ; les communes du projet
sont à des centaines de kilomètres les unes des autres. Chaque valeur porte
ci-dessous son niveau de certitude.

    venv\\Scripts\\python.exe seed_decoupage_communes.py --verifier
        Montre ce qui serait écrit, sans rien modifier.

    venv\\Scripts\\python.exe seed_decoupage_communes.py
        Applique. N'écrase JAMAIS une valeur déjà renseignée : seuls les
        champs vides sont remplis. Pour corriger une valeur existante, passer
        par l'écran d'administration.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()

from services import audit  # noqa: E402
from services.console import adoucir_sortie  # noqa: E402
from supabase_client import get_supabase_client  # noqa: E402

adoucir_sortie()

# Qui a demandé cette saisie. Inscrit dans l'audit — `acteur_id` reste NULL,
# ce n'est pas une action faite depuis un compte connecté.
AUTORISE_PAR = "morlaye.cisse@uadb.edu.sn"

#: nom -> (champs à poser, note de certitude)
VALEURS = {
    "Dakar": (
        {
            # Région et département de Dakar : découpage administratif
            # sénégalais standard. La région de Dakar compte quatre
            # départements — Dakar, Guédiawaye, Pikine, Rufisque.
            "region": "Dakar",
            "departement": "Dakar",
            # `arrondissement` est VOLONTAIREMENT absent. La Ville de Dakar
            # compte quatre arrondissements et dix-neuf communes
            # d'arrondissement : un extrait y est délivré par une commune
            # précise (Plateau, Médina, Fann-Point E…), pas par « Dakar ».
            # Le champ est facultatif dans le gabarit ; en poser un arbitraire
            # ferait sortir un acte avec une mention fausse.
            "latitude": 14.6937,
            "longitude": -17.4441,
        },
        "découpage sûr ; coordonnées = centre-ville (Plateau)",
    ),
    "Ross-Béthio": (
        {
            # Couple déjà présent en exemple commenté dans
            # migrations/015_communes_coordonnees.sql.
            "latitude": 16.2761,
            "longitude": -16.1372,
        },
        "découpage déjà renseigné et exact ; coordonnées reprises de la migration 015",
    ),
    "Dindéfélo": (
        {
            "latitude": 12.3833,
            "longitude": -12.3167,
        },
        "découpage déjà renseigné et exact ; coordonnées À RECOUPER (petit village du Kédougou)",
    ),
}


async def principal() -> int:
    analyseur = argparse.ArgumentParser(description="Saisie du découpage et des coordonnées des communes.")
    analyseur.add_argument("--verifier", action="store_true", help="montrer sans écrire")
    arguments = analyseur.parse_args()

    supabase = get_supabase_client()
    try:
        communes = supabase.table("communes").select("*").execute().data
    except Exception as exc:  # noqa: BLE001
        print(f"Base injoignable ({type(exc).__name__}: {exc}).")
        return 1

    par_nom = {c["nom"]: c for c in communes}
    inconnues = [nom for nom in VALEURS if nom not in par_nom]
    if inconnues:
        print(f"Communes absentes de la base, ignorées : {inconnues}")

    total_ecrites = 0
    for nom, (souhaitees, note) in VALEURS.items():
        commune = par_nom.get(nom)
        if not commune:
            continue

        # On ne remplit que le vide : une valeur déjà saisie a pu l'être par
        # quelqu'un qui savait mieux, et l'écraser depuis un script la perdrait
        # sans trace utile.
        a_ecrire = {
            cle: valeur for cle, valeur in souhaitees.items()
            if commune.get(cle) in (None, "")
        }
        deja = {cle: commune.get(cle) for cle in souhaitees if commune.get(cle) not in (None, "")}

        print(f"\n{nom}  — {note}")
        for cle, valeur in deja.items():
            print(f"  inchangé  {cle} = {valeur!r}")
        if not a_ecrire:
            print("  rien à écrire")
            continue
        for cle, valeur in a_ecrire.items():
            print(f"  À ÉCRIRE  {cle} = {valeur!r}")

        if arguments.verifier:
            continue

        try:
            supabase.table("communes").update(a_ecrire).eq("id", commune["id"]).execute()
        except Exception as exc:  # noqa: BLE001
            print(f"  échec de l'écriture ({type(exc).__name__}: {exc})")
            continue
        total_ecrites += len(a_ecrire)
        print("  écrit")

        await audit.journaliser(
            "commune_modifiee",
            acteur={"id": None, "email": AUTORISE_PAR, "role": None},
            cible_type="commune",
            cible_id=commune["id"],
            cible_libelle=nom,
            details={
                "source": "script seed_decoupage_communes.py",
                "autorise_par": AUTORISE_PAR,
                "champs": a_ecrire,
                "note": note,
            },
        )

    print()
    if arguments.verifier:
        print("Vérification seule — rien n'a été écrit.")
    else:
        print(f"{total_ecrites} champ(s) écrit(s), journalisés dans journal_audit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(principal()))
