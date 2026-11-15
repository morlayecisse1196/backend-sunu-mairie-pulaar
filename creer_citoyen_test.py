"""
Crée (ou réinitialise) le compte CITOYEN de test utilisé par
`test_ws_v2_integration.py`, série B.

Pourquoi un compte dédié, et pas le compte personnel du développeur :

- Le test parle vraiment à l'agent. Il crée une conversation, écrit une session
  de dialogue, parfois un dossier. Tout cela atterrit dans l'historique du
  compte utilisé — on ne veut pas ça dans un compte qui porte de vrais
  dossiers, ni dans un compte admin.
- Réinitialiser le mot de passe d'un compte personnel peut couper l'accès à
  autre chose (le dashboard, l'espace admin). Un compte de test ne coûte rien
  et ne casse rien.
- Convention déjà en place dans ce dépôt : les comptes de test vivent sur le
  domaine `@sunu-mairie.local`, qui n'est pas routable — aucun courriel ne peut
  partir vers un vrai destinataire par erreur
  (cf. `reset_mot_de_passe_consultants_test.py`).

Le mot de passe est tiré avec `secrets` (jamais `random` : c'est un secret
d'authentification) et **écrit directement dans `.env`**, pas affiché. Un mot
de passe affiché reste dans l'historique du terminal, dans les captures
d'écran et dans les journaux de session ; celui-ci ne sort jamais du fichier
`.env`, qui est couvert par `.gitignore`.

Utilisation, depuis `backend-agent/` :

    venv\\Scripts\\python.exe creer_citoyen_test.py

Rejouable sans risque : si le compte existe déjà, son mot de passe est
réinitialisé au lieu d'être recréé (l'identifiant du compte, donc ses
dossiers, est conservé).

⚠️ Ce script utilise la clé `service_role` et écrit dans le projet Supabase
réel. Il ne touche QUE le compte `citoyen.test@sunu-mairie.local`.
"""
from __future__ import annotations

import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from services.console import adoucir_sortie  # noqa: E402
from supabase_client import get_supabase_client  # noqa: E402

adoucir_sortie()

# Domaine non routable : un courriel envoyé à cette adresse ne peut atteindre
# personne. C'est voulu pour un compte de test.
EMAIL = "citoyen.test@sunu-mairie.local"

# Une commune réelle de la base plutôt que "National" : c'est ce qui permet au
# test d'exercer le filtrage par commune de la recherche sémantique, qui est
# justement le chemin que "National" court-circuite.
COMMUNE = "Dakar"

CHEMIN_ENV = Path(__file__).with_name(".env")


def ecrire_dans_env(email: str, mot_de_passe: str) -> None:
    """
    Pose TEST_CITOYEN_EMAIL / TEST_CITOYEN_MOT_DE_PASSE dans `.env`, en
    remplaçant les lignes existantes plutôt qu'en les empilant — sinon
    `python-dotenv` garderait la première valeur et on déboguerait longtemps un
    mot de passe « qui ne marche pas » alors qu'il est juste plus bas.
    """
    lignes = CHEMIN_ENV.read_text(encoding="utf-8").splitlines() if CHEMIN_ENV.exists() else []
    valeurs = {"TEST_CITOYEN_EMAIL": email, "TEST_CITOYEN_MOT_DE_PASSE": mot_de_passe}
    restantes = dict(valeurs)

    for i, ligne in enumerate(lignes):
        for cle in valeurs:
            if ligne.startswith(f"{cle}="):
                lignes[i] = f"{cle}={valeurs[cle]}"
                restantes.pop(cle, None)

    for cle, valeur in restantes.items():
        lignes.append(f"{cle}={valeur}")

    CHEMIN_ENV.write_text("\n".join(lignes) + "\n", encoding="utf-8")


def principal() -> int:
    supabase = get_supabase_client()

    try:
        comptes = {u.email: u.id for u in supabase.auth.admin.list_users()}
    except Exception as exc:  # noqa: BLE001
        print(f"Impossible de lister les comptes ({type(exc).__name__}: {exc}).")
        print("Vérifiez que SUPABASE_KEY est bien la clé service_role.")
        return 1

    mot_de_passe = secrets.token_urlsafe(12)
    user_id = comptes.get(EMAIL)

    if user_id:
        print(f"Compte existant : {EMAIL} — réinitialisation du mot de passe.")
        try:
            supabase.auth.admin.update_user_by_id(user_id, {"password": mot_de_passe})
        except Exception as exc:  # noqa: BLE001
            print(f"Réinitialisation échouée ({type(exc).__name__}: {exc}).")
            return 1
    else:
        print(f"Création du compte : {EMAIL}")
        try:
            reponse = supabase.auth.admin.create_user({
                "email": EMAIL,
                "password": mot_de_passe,
                # Confirmé d'office : aucun courriel ne peut arriver sur un
                # domaine non routable, et sans confirmation la connexion par
                # mot de passe est refusée.
                "email_confirm": True,
            })
        except Exception as exc:  # noqa: BLE001
            print(f"Création échouée ({type(exc).__name__}: {exc}).")
            return 1
        user_id = reponse.user.id

    # Profil citoyen. `get_user_profile` retombe déjà sur
    # {commune: National, role: citoyen} en cas d'absence, donc ce n'est pas
    # vital — mais sans ligne `profiles`, le test ne passerait jamais par le
    # filtrage par commune, qui est une partie du comportement à vérifier.
    try:
        supabase.table("profiles").upsert(
            {"id": user_id, "commune": COMMUNE, "role": "citoyen"}
        ).execute()
        print(f"Profil : role=citoyen, commune={COMMUNE}")
    except Exception as exc:  # noqa: BLE001
        print(f"Profil non écrit ({type(exc).__name__}) — le test fonctionnera "
              f"quand même, en commune 'National'.")

    ecrire_dans_env(EMAIL, mot_de_passe)

    print()
    print(f"Identifiant du compte : {user_id}")
    print("Mot de passe écrit dans .env (TEST_CITOYEN_MOT_DE_PASSE) — pas affiché ici,")
    print("pour qu'il ne reste pas dans l'historique du terminal.")
    print()
    print("Vous pouvez lancer :  venv\\Scripts\\python.exe test_ws_v2_integration.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
