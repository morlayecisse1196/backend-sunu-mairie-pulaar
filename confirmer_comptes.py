r"""
Confirme des comptes restés bloqués en attente d'un courriel qui n'arrivera pas.

POURQUOI LA CONFIRMATION BLOQUE

Supabase Auth refuse `signInWithPassword` tant que `email_confirmed_at` est
vide : la réponse est « Email not confirmed ». Le compte existe, le mot de
passe est bon, et la connexion est refusée quand même. Tant qu'aucun serveur
d'envoi n'est configuré sur le projet, le lien de confirmation n'arrive jamais
— le compte est donc créé et inutilisable, définitivement.

Réglage lu sur le projet le 2026-11-14 : `mailer_autoconfirm = false`,
c'est-à-dire confirmation EXIGÉE.

CE QUE CE SCRIPT FAIT, ET CE QU'IL NE FAIT PAS

Il pose `email_confirm` sur des comptes DÉJÀ créés : ils deviennent utilisables
immédiatement. Il ne change aucun mot de passe, ne crée ni ne supprime aucun
compte, et ne touche pas au rôle.

Il ne règle PAS le cas des inscriptions à venir : cela se décide dans le
tableau de bord Supabase (Authentication > Sign In / Providers > Email >
« Confirm email »), et aucune clé présente dans `.env` ne permet de le faire
depuis le code — il y faudrait un jeton d'accès personnel, que ce projet n'a
pas, et c'est tant mieux : un réglage de sécurité se change à la main, par
quelqu'un qui sait ce qu'il fait.

Utilisation, depuis `backend-agent/` :

    venv\Scripts\python.exe confirmer_comptes.py --lister
        Les comptes en attente de confirmation. Ne modifie rien.

    venv\Scripts\python.exe confirmer_comptes.py quelquun@exemple.sn
        Confirme ce compte.

    venv\Scripts\python.exe confirmer_comptes.py --tous
        Confirme TOUS les comptes en attente. Demande une confirmation.

CE QU'ON ACCEPTE EN FAISANT ÇA

Sans vérification de l'adresse, n'importe qui peut s'inscrire avec l'adresse
d'un autre. Ici, ce n'est pas la faille qu'on croit : l'identité du demandeur
n'est JAMAIS établie par sa boîte mail, mais par le consultant, qui compare les
pièces (CNI, certificat) aux réponses du dialogue avant d'établir l'acte.
L'adresse ne sert qu'à se reconnecter. Pour un service public ouvert au grand
public, il faudra néanmoins un envoi de courriels avant la mise en production.

⚠️ Clé `service_role` et projet Supabase réel.
"""
from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

load_dotenv()

from services.console import adoucir_sortie  # noqa: E402
from supabase_client import get_supabase_client  # noqa: E402

adoucir_sortie()


def _comptes(supabase):
    try:
        return list(supabase.auth.admin.list_users())
    except Exception as exc:  # noqa: BLE001
        print(f"Impossible de lister les comptes ({type(exc).__name__}: {exc}).")
        print("Vérifiez que SUPABASE_KEY est bien la clé service_role.")
        return None


def _en_attente(comptes: list) -> list:
    return [u for u in comptes if not getattr(u, "email_confirmed_at", None)]


def _confirmer(supabase, compte) -> bool:
    try:
        supabase.auth.admin.update_user_by_id(compte.id, {"email_confirm": True})
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  {compte.email} : échec ({type(exc).__name__}: {exc})")
        return False


def principal() -> int:
    analyseur = argparse.ArgumentParser(description="Confirme des comptes Supabase déjà créés.")
    analyseur.add_argument("adresse", nargs="?", help="adresse du compte à confirmer")
    analyseur.add_argument("--lister", action="store_true", help="lister les comptes en attente, sans rien changer")
    analyseur.add_argument("--tous", action="store_true", help="confirmer tous les comptes en attente")
    options = analyseur.parse_args()

    if not (options.adresse or options.lister or options.tous):
        analyseur.print_help()
        return 2

    supabase = get_supabase_client()
    comptes = _comptes(supabase)
    if comptes is None:
        return 1

    attente = _en_attente(comptes)

    if options.lister:
        print(f"{len(comptes)} compte(s) au total, {len(attente)} en attente de confirmation.")
        for compte in attente:
            print(f"  {compte.email}  (créé le {compte.created_at})")
        if not attente:
            print("Aucun compte bloqué : tous sont confirmés.")
        return 0

    if options.adresse:
        recherchee = options.adresse.strip().lower()
        compte = next((u for u in comptes if (u.email or "").lower() == recherchee), None)
        if compte is None:
            print(f"Aucun compte pour {recherchee}.")
            return 1
        if getattr(compte, "email_confirmed_at", None):
            print(f"{compte.email} est déjà confirmé — rien à faire.")
            return 0
        if not _confirmer(supabase, compte):
            return 1
        print(f"{compte.email} est confirmé : la connexion par mot de passe fonctionne désormais.")
        return 0

    # --tous
    if not attente:
        print("Aucun compte en attente : rien à faire.")
        return 0
    print(f"{len(attente)} compte(s) seront confirmés :")
    for compte in attente:
        print(f"  {compte.email}")
    reponse = input("Confirmer ces comptes ? [o/N] ").strip().lower()
    if reponse not in ("o", "oui"):
        print("Annulé — rien n'a été modifié.")
        return 0

    faits = sum(1 for compte in attente if _confirmer(supabase, compte))
    print(f"{faits}/{len(attente)} compte(s) confirmé(s).")
    return 0 if faits == len(attente) else 1


if __name__ == "__main__":
    raise SystemExit(principal())
