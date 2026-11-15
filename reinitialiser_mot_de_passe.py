"""
Réinitialise le mot de passe d'un compte, par son adresse.

POURQUOI CE SCRIPT

`create_consultant()` (admin_repo.py) tire le mot de passe avec `secrets` et ne
le stocke JAMAIS en clair : il est affiché une seule fois, à la création. Passé
ce message, il est irrécupérable. `reset_mot_de_passe_consultants_test.py`
réglait le cas, mais pour deux adresses de consultant **écrites en dur** — le
compte admin de test, lui, n'avait aucun moyen de reprise.

Le seul autre script qui touchait au compte admin, `test_creer_admin_web.py`,
le SUPPRIME puis le recrée. Ce n'est pas la même chose : supprimer le compte
Auth emporte sa ligne `profiles`, donc son rôle et sa commune, et casse toute
ligne qui le référence (notes internes, journal d'audit, historique
d'atelier). Réinitialiser conserve l'identifiant du compte, et donc tout ce qui
y est rattaché.

Utilisation, depuis `backend-agent/` :

    venv\\Scripts\\python.exe reinitialiser_mot_de_passe.py admin.test.g1@sunu-mairie.local

    venv\\Scripts\\python.exe reinitialiser_mot_de_passe.py --lister
        Les comptes existants et leur rôle, sans rien changer.

Le nouveau mot de passe est affiché — il faut bien le saisir dans le
navigateur. Il n'apparaît que dans VOTRE terminal : à utiliser puis à changer
depuis l'application (l'écran de profil propose « changer le mot de passe »).

⚠️ Clé `service_role` et projet Supabase réel. Le script ne touche qu'aux
comptes dont vous donnez l'adresse, et ne supprime jamais rien.
"""
from __future__ import annotations

import argparse
import secrets
import sys

from dotenv import load_dotenv

load_dotenv()

from services.console import adoucir_sortie  # noqa: E402
from supabase_client import get_supabase_client  # noqa: E402

adoucir_sortie()


def lister(supabase) -> int:
    comptes = {u.email: u.id for u in supabase.auth.admin.list_users()}
    profils = {p["id"]: p for p in supabase.table("profiles").select("id,role,commune").execute().data}
    print(f"{'adresse':<46} {'role':<12} commune")
    for email, identifiant in sorted(comptes.items(), key=lambda kv: kv[0]):
        profil = profils.get(identifiant, {})
        print(f"{email:<46} {profil.get('role', '(sans profil)'):<12} {profil.get('commune', '')}")
    return 0


def reinitialiser(supabase, email: str) -> int:
    comptes = {u.email: u.id for u in supabase.auth.admin.list_users()}
    identifiant = comptes.get(email)
    if not identifiant:
        print(f"Aucun compte avec l'adresse {email!r}.")
        print("Utilisez --lister pour voir les adresses existantes.")
        return 1

    nouveau = secrets.token_urlsafe(12)
    try:
        supabase.auth.admin.update_user_by_id(identifiant, {"password": nouveau})
    except Exception as exc:  # noqa: BLE001
        print(f"Réinitialisation échouée ({type(exc).__name__}: {exc}).")
        return 1

    profil = supabase.table("profiles").select("role,commune").eq("id", identifiant).execute().data
    role = profil[0].get("role") if profil else "(sans profil)"

    print(f"Compte    : {email}  (role {role})")
    print(f"MOT DE PASSE : {nouveau}")
    print()
    print("À saisir dans le navigateur, puis à changer depuis l'écran de profil.")
    return 0


def principal() -> int:
    analyseur = argparse.ArgumentParser(description="Réinitialise un mot de passe de compte.")
    analyseur.add_argument("email", nargs="?", help="adresse du compte à réinitialiser")
    analyseur.add_argument("--lister", action="store_true", help="lister les comptes, sans rien changer")
    arguments = analyseur.parse_args()

    try:
        supabase = get_supabase_client()
    except Exception as exc:  # noqa: BLE001
        print(f"Client Supabase indisponible ({type(exc).__name__}: {exc}).")
        return 1

    if arguments.lister:
        return lister(supabase)
    if not arguments.email:
        analyseur.print_help()
        return 2
    return reinitialiser(supabase, arguments.email)


if __name__ == "__main__":
    raise SystemExit(principal())
