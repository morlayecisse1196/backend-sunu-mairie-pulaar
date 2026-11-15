r"""
« Je me suis inscrit et je ne reçois pas le courriel de confirmation. »

Ce script LIT l'état d'un compte dans Supabase Auth et ne modifie rien. Il
répond à la seule question qui compte : le compte existe-t-il déjà, et est-il
déjà confirmé ?

POURQUOI L'INSCRIPTION NE DIT PAS LA VÉRITÉ TOUTE SEULE

Supabase refuse de révéler si une adresse est déjà enregistrée — c'est une
protection contre l'énumération des comptes. Un `signUp` sur une adresse
existante ne renvoie donc AUCUNE erreur : il renvoie un utilisateur
d'apparence normale, sans session, et n'envoie aucun courriel. Vu du
navigateur, c'est exactement la même réponse qu'une vraie inscription en
attente de confirmation. Le seul signal est `identities: []`, que la page
d'inscription teste désormais.

Utilisation, depuis `backend-agent/` :

    venv\Scripts\python.exe diagnostiquer_compte.py mon.adresse@exemple.sn

⚠️ Utilise la clé `service_role` : à lancer sur votre machine, jamais depuis
un navigateur. Il n'écrit rien, ni dans Supabase, ni dans `.env`.
"""
from __future__ import annotations

import sys

from dotenv import load_dotenv

load_dotenv()

from services.console import adoucir_sortie  # noqa: E402
from supabase_client import get_supabase_client  # noqa: E402

adoucir_sortie()


def principal() -> int:
    if len(sys.argv) != 2:
        print("Usage : python diagnostiquer_compte.py <adresse e-mail>")
        return 2
    recherchee = sys.argv[1].strip().lower()

    supabase = get_supabase_client()
    try:
        comptes = supabase.auth.admin.list_users()
    except Exception as exc:  # noqa: BLE001
        print(f"Impossible de lister les comptes ({type(exc).__name__}: {exc}).")
        print("Vérifiez que SUPABASE_KEY est bien la clé service_role.")
        return 1

    compte = next((u for u in comptes if (u.email or "").lower() == recherchee), None)

    if compte is None:
        print(f"Aucun compte pour {recherchee}.")
        print()
        print("L'inscription n'a donc pas abouti. Si la page affichait pourtant")
        print("« votre compte est créé », c'est que les inscriptions sont refusées")
        print("côté Supabase (Authentication > Sign In / Providers > Email).")
        return 0

    confirme = getattr(compte, "email_confirmed_at", None)
    print(f"Compte trouvé pour {recherchee}")
    print(f"  identifiant   : {compte.id}")
    print(f"  créé le       : {compte.created_at}")
    print(f"  confirmé      : {confirme or 'NON'}")
    print(f"  dernière conn.: {getattr(compte, 'last_sign_in_at', None) or 'jamais'}")

    # Le rôle vient de `profiles`, pas de Auth : c'est lui qui décide de
    # l'espace d'arrivée après connexion.
    try:
        profil = supabase.table("profiles").select("role, commune").eq("id", compte.id).limit(1).execute().data
        if profil:
            print(f"  profil        : role={profil[0].get('role')}, commune={profil[0].get('commune')}")
        else:
            print("  profil        : aucune ligne `profiles` (role=citoyen et commune=National par défaut)")
    except Exception as exc:  # noqa: BLE001
        print(f"  profil        : lecture impossible ({type(exc).__name__})")

    print()
    if confirme:
        print("Ce compte est DÉJÀ confirmé : aucun courriel ne sera envoyé, et c'est normal.")
        print("Vous ne pouvez pas le recréer — connectez-vous avec, ou passez par")
        print("« Mot de passe oublié » si vous ne l'avez plus.")
    else:
        print("Ce compte attend une confirmation jamais reçue. Deux causes possibles :")
        print("  * aucun serveur d'envoi n'est configuré sur le projet Supabase ;")
        print("  * la confirmation par e-mail est active alors qu'elle n'est pas")
        print("    nécessaire pour vos essais.")
        print()
        print("Pour tester tout de suite, le plus simple est de désactiver la")
        print("confirmation : Supabase > Authentication > Sign In / Providers >")
        print("Email > « Confirm email ». Les comptes créés ensuite sont utilisables")
        print("immédiatement.")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
