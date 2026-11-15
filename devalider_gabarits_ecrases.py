"""
Répare les gabarits écrasés par le défaut de filtre de l'atelier.

CE QUI S'EST PASSÉ

`services/atelier.enregistrer` mettait à jour une ligne par sa seule clé :

    client.table(table).update(donnees).eq(colonne_cle, valeur_cle)

Or « recapitulatif » est la clé du gabarit dans les TROIS démarches. Relire
celui de l'extrait de naissance écrasait donc aussi celui du mariage et celui
du décès, et les marquait `pulaar_valide = True` — sans rien journaliser.

Le correctif (filtre `type_demarche`) est en place. Reste à réparer les deux
lignes abîmées : elles portent le texte pulaar de la naissance, avec ses trous
`{nom_enfant}`, `{nom_mere}`… qui n'existent pas dans ces démarches.

CE QUE FAIT CE SCRIPT

1. Journalise le texte fautif dans `atelier_historique` (`pulaar_avant`), pour
   qu'il ne disparaisse pas sans trace — l'écrasement, lui, n'avait rien laissé.
2. Vide la colonne `pulaar` et repasse `pulaar_valide` à `false`.

POURQUOI VIDER PLUTÔT QUE LAISSER

Laisser le texte de la naissance dans le gabarit du mariage tromperait le
prochain relecteur : il croirait corriger une ébauche de sa démarche alors
qu'il corrigerait un texte qui parle d'un enfant et de sa mère. Et rien n'est
perdu : ce texte existe toujours, à sa place, dans le gabarit de la naissance.

AUCUN CITOYEN N'A RIEN ENTENDU DE FAUX

`gabarits.rendre` refuse un gabarit dont les trous ne correspondent à aucun
champ : le pulaar restait `None` et le français repartait au traducteur. Le
garde-fou a tenu. Ce qui était faux, c'est l'ÉTAT affiché — « relu » pour une
traduction que personne n'avait lue.

    venv\\Scripts\\python.exe devalider_gabarits_ecrases.py --verifier
    venv\\Scripts\\python.exe devalider_gabarits_ecrases.py
"""
from __future__ import annotations

import argparse
import time

from dotenv import load_dotenv

load_dotenv()

from services import gabarits  # noqa: E402
from services.console import adoucir_sortie  # noqa: E402
from supabase_client import get_supabase_client  # noqa: E402

adoucir_sortie()

PAR = "correction automatique (defaut de filtre de l'atelier, corrige le 2026-11-05)"

#: Les trous qui trahissent le texte de l'extrait de naissance dans une autre
#: démarche. On ne touche QUE les lignes qui en portent : une ligne dont le
#: pulaar est propre à sa démarche a été relue pour de bon, on la laisse.
TROUS_NAISSANCE = {"nom_enfant", "date_naissance_enfant", "commune_naissance",
                   "nom_mere", "date_naissance_mere"}


def principal() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--verifier", action="store_true", help="montrer sans écrire")
    arguments = analyseur.parse_args()

    for essai in range(4):
        try:
            supabase = get_supabase_client()
            lignes = supabase.table("demarche_gabarits").select("*").execute().data
            break
        except Exception as exc:  # noqa: BLE001
            print(f"  tentative {essai + 1} : {type(exc).__name__}")
            time.sleep(5)
    else:
        print("Base injoignable.")
        return 1

    a_reparer = []
    for ligne in lignes:
        pulaar = ligne.get("pulaar") or ""
        intrus = sorted(set(gabarits.trous(pulaar)) & TROUS_NAISSANCE)
        if ligne.get("type_demarche") == "extrait_naissance" or not intrus:
            continue
        a_reparer.append((ligne, intrus))

    if not a_reparer:
        print("Aucun gabarit abîmé : rien à faire.")
        return 0

    for ligne, intrus in a_reparer:
        print(f"\n{ligne['type_demarche']} / {ligne['cle']}")
        print(f"  pulaar_valide actuel : {ligne.get('pulaar_valide')}")
        print(f"  trous étrangers      : {intrus}")
        print(f"  texte à retirer      : {(ligne.get('pulaar') or '')[:90]}…")
        if arguments.verifier:
            continue

        # Journaliser D'ABORD : si l'écriture suivante échoue, on a au moins
        # gardé le texte. L'inverse perdrait ce que l'écrasement avait déjà
        # laissé disparaître une première fois.
        try:
            supabase.table("atelier_historique").insert({
                "identifiant": f"gabarit:{ligne['cle']}",
                "type_demarche": ligne["type_demarche"],
                "pulaar_avant": ligne.get("pulaar") or None,
                "pulaar_apres": "",
                "valide": False,
                "par": PAR,
            }).execute()
        except Exception as exc:  # noqa: BLE001
            print(f"  historique non écrit ({type(exc).__name__}) — on continue quand même")

        try:
            supabase.table("demarche_gabarits").update(
                {"pulaar": None, "pulaar_valide": False}
            ).eq("cle", ligne["cle"]).eq("type_demarche", ligne["type_demarche"]).execute()
        except Exception as exc:  # noqa: BLE001
            print(f"  ÉCHEC de la remise à zéro ({type(exc).__name__}: {exc})")
            continue
        print("  dévalidé et vidé")

    print()
    if arguments.verifier:
        print(f"{len(a_reparer)} gabarit(s) à réparer — rien n'a été écrit.")
    else:
        print(f"{len(a_reparer)} gabarit(s) réparé(s). Ils repartiront au traducteur, "
              f"comme avant, jusqu'à leur vraie relecture.")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
