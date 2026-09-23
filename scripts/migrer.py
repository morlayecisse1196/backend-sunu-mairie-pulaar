"""
Migrations : savoir lesquelles sont faites, appliquer celles qui manquent.

POURQUOI

« Est-ce que la migration 019 est passée ? » n'avait aucune réponse fiable :
il fallait aller regarder si telle colonne existait, table par table. On finit
par appliquer deux fois, ou pas du tout, et le jour où ça casse c'est en
production. Ce script tient un REGISTRE : une ligne par fichier appliqué, avec
l'empreinte de son contenu.

    set DATABASE_URL=postgresql://...        (Windows, cmd)
    $env:DATABASE_URL = "postgresql://..."   (Windows, PowerShell)
    export DATABASE_URL="postgresql://..."   (Linux, macOS)

    python scripts/migrer.py --etat
        Ce qui est appliqué, ce qui manque. Ne touche à rien.

    python scripts/migrer.py
        Applique les manquantes, dans l'ordre, chacune dans sa transaction.
        Une migration qui échoue est annulée entièrement et arrête le script :
        la base reste dans un état connu.

    python scripts/migrer.py --marquer-appliquees 017 018
        Inscrit au registre des migrations déjà passées à la main, SANS les
        rejouer. À faire une seule fois, au moment d'adopter ce script.

LE MOT DE PASSE NE PASSE PAS EN ARGUMENT

Il est lu dans l'environnement, jamais sur la ligne de commande : un argument
reste dans l'historique du shell et dans la liste des processus. Il n'est
écrit dans aucun fichier, et le script ne l'affiche jamais.

UNE MIGRATION APPLIQUÉE NE SE MODIFIE PLUS

Si le contenu d'un fichier déjà appliqué a changé, le script refuse d'aller
plus loin. C'est ainsi que deux bases censées être identiques divergent sans
que personne ne le voie : le fichier dit une chose, la base en contient une
autre. Une correction se fait dans une NOUVELLE migration.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from urllib.parse import urlsplit

_RACINE_ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RACINE_)
from services.console import adoucir_sortie  # noqa: E402

adoucir_sortie()

_RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOSSIER = os.path.join(_RACINE, "migrations")

REGISTRE = """
create table if not exists public.migrations_appliquees (
    fichier      text primary key,
    empreinte    text not null,
    appliquee_le timestamptz not null default now()
);
comment on table public.migrations_appliquees is
    'Registre des migrations jouées. `empreinte` = sha256 du fichier au moment ou il a ete '
    'applique : un fichier modifie apres coup fait diverger la base du depot, en silence.';
"""


def _url() -> str:
    url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL")
    if not url:
        print("DATABASE_URL absent de l'environnement.", file=sys.stderr)
        print("Voir l'en-tête de ce fichier pour la poser selon votre shell.", file=sys.stderr)
        raise SystemExit(2)
    # Supabase n'accepte que des connexions chiffrées.
    if "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def _sans_secret(url: str) -> str:
    """L'adresse, sans le mot de passe — pour pouvoir l'afficher."""
    morceaux = urlsplit(url)
    return f"{morceaux.scheme}://{(morceaux.hostname or '?')}:{morceaux.port or 5432}"


def _fichiers() -> list[tuple[str, str, str]]:
    """(nom, contenu, empreinte) de chaque migration, dans l'ordre des numéros."""
    resultat = []
    for nom in sorted(f for f in os.listdir(DOSSIER) if f.endswith(".sql")):
        with open(os.path.join(DOSSIER, nom), encoding="utf-8") as fichier:
            contenu = fichier.read()
        resultat.append((nom, contenu, hashlib.sha256(contenu.encode("utf-8")).hexdigest()))
    return resultat


def _appliquees(connexion) -> dict[str, str]:
    with connexion.cursor() as curseur:
        curseur.execute(REGISTRE)
        curseur.execute("select fichier, empreinte from public.migrations_appliquees")
        return {ligne[0]: ligne[1] for ligne in curseur.fetchall()}


def _verifier_non_modifiees(fichiers, deja: dict[str, str]) -> list[str]:
    return [nom for nom, _contenu, empreinte in fichiers
            if nom in deja and deja[nom] != empreinte]


def _etat(fichiers, deja: dict[str, str]) -> None:
    for nom, _contenu, empreinte in fichiers:
        if nom not in deja:
            marque = "MANQUANTE"
        elif deja[nom] != empreinte:
            marque = "MODIFIÉE APRÈS COUP"
        else:
            marque = "appliquée"
        print(f"  {marque:<20} {nom}")
    manquantes = [n for n, _c, _e in fichiers if n not in deja]
    print(f"\n{len(manquantes)} migration(s) à appliquer.")


def _appliquer(connexion, fichiers, deja: dict[str, str]) -> int:
    manquantes = [(n, c, e) for n, c, e in fichiers if n not in deja]
    if not manquantes:
        print("Rien à faire : tout est appliqué.")
        return 0
    for nom, contenu, empreinte in manquantes:
        print(f"  {nom} …", end=" ", flush=True)
        try:
            # Tout ou rien : une migration à moitié passée est le pire état
            # possible, parce que la relancer échoue sur ce qui a réussi.
            with connexion.transaction(), connexion.cursor() as curseur:
                curseur.execute(contenu)
                curseur.execute(
                    "insert into public.migrations_appliquees (fichier, empreinte) values (%s, %s)",
                    (nom, empreinte),
                )
        except Exception as exc:  # noqa: BLE001 — on rend l'erreur lisible et on s'arrête
            print("ÉCHEC")
            print(f"\n{nom} a été entièrement annulée. La base n'a pas bougé.\n{exc}", file=sys.stderr)
            return 1
        print("fait")
    print(f"\n{len(manquantes)} migration(s) appliquée(s).")
    return 0


def _marquer(connexion, fichiers, numeros: list[str]) -> int:
    par_numero = {nom[:3]: (nom, empreinte) for nom, _c, empreinte in fichiers}
    inconnus = [n for n in numeros if n not in par_numero]
    if inconnus:
        print(f"Numéro(s) inconnu(s) : {', '.join(inconnus)}", file=sys.stderr)
        return 2
    with connexion.transaction(), connexion.cursor() as curseur:
        curseur.execute(REGISTRE)
        for numero in numeros:
            nom, empreinte = par_numero[numero]
            curseur.execute(
                "insert into public.migrations_appliquees (fichier, empreinte) values (%s, %s) "
                "on conflict (fichier) do update set empreinte = excluded.empreinte",
                (nom, empreinte),
            )
            print(f"  {nom} inscrite au registre (non rejouée)")
    return 0


def main() -> int:
    analyseur = argparse.ArgumentParser(description="Applique les migrations manquantes.")
    analyseur.add_argument("--etat", action="store_true", help="lister sans rien appliquer")
    analyseur.add_argument("--marquer-appliquees", nargs="+", metavar="NUM", default=None,
                           help="inscrire au registre des migrations déjà passées à la main")
    options = analyseur.parse_args()

    try:
        import psycopg
    except ImportError:
        print("Le paquet `psycopg` est nécessaire : pip install psycopg[binary]", file=sys.stderr)
        return 2

    url = _url()
    fichiers = _fichiers()
    print(f"Base : {_sans_secret(url)}\n")

    with psycopg.connect(url) as connexion:
        deja = _appliquees(connexion)

        if options.marquer_appliquees:
            return _marquer(connexion, fichiers, options.marquer_appliquees)

        modifiees = _verifier_non_modifiees(fichiers, deja)
        if modifiees:
            print("Ces migrations ont été MODIFIÉES après avoir été appliquées :", file=sys.stderr)
            for nom in modifiees:
                print(f"  {nom}", file=sys.stderr)
            print("\nLa base ne contient plus ce que disent ces fichiers. Corrigez dans une "
                  "NOUVELLE migration plutôt que de récrire celles-ci.", file=sys.stderr)
            return 1

        if options.etat:
            _etat(fichiers, deja)
            return 0
        return _appliquer(connexion, fichiers, deja)


if __name__ == "__main__":
    raise SystemExit(main())
