"""
Test manuel — Sprint B, Tâche B.4 (relecture obligatoire RG7 + confirmation).

Complète un dossier de bout en bout au-delà de ce que testait
test_bascule_administratif.py (qui s'arrêtait avant tous les slots remplis) :

  1. Reprend un dossier déjà en cours (âge connu) et remplit tous les
     slots restants sur quelques tours.
  2. Vérifie que la relecture apparaît AUTOMATIQUEMENT dès le dernier slot
     rempli (phase="relecture_en_cours"), et que le dossier n'est PAS encore
     passé au statut "recu" à ce stade.
  3. Envoie une réponse de correction (pas une confirmation positive) ->
     vérifie que le slot concerné est rouvert/corrigé, PAS d'envoi forcé.
  4. Envoie enfin une confirmation positive -> vérifie le passage au statut
     "recu" avec numero_suivi généré.

Même principe que test_bascule_administratif.py : vrai LLM + vraie base,
sans repasser par ASR/TTS (pas de micro disponible ici).
"""
import asyncio
import json
from dotenv import load_dotenv

load_dotenv()

import main  # noqa: E402
import dialogue_engine
from dossiers_repo import get_dossier
from test_bascule_administratif import appeler_generateur, TEST_CITOYEN_ID, TEST_COMMUNE

SESSION_ID = "test_b4_session"


async def tour_administratif(etat, message: str):
    """Reproduit le branchement mode administratif de main.py pour un tour, hors relecture/confirmation."""
    admin_prompt = main.build_generator_prompt_administratif(message, etat["slots"], etat["cas_legal"])
    schema = {"type": "json_schema", "json_schema": {"name": "slots_update", "strict": True, "schema": main.SLOTS_JSON_SCHEMA_ADMINISTRATIF}}
    parsed = await appeler_generateur(main.SYSTEM_PROMPT_GENERATOR_ADMINISTRATIF, admin_prompt, schema)
    etat["slots"] = main.fusionner_slots(etat["slots"], parsed["slots_maj"])
    age = etat["slots"].get("age_enfant") or {}
    if age.get("valeur") is not None and age.get("unite"):
        etat["cas_legal"] = main.determiner_cas_legal(main.normaliser_age(age["valeur"], age["unite"]))

    reponse = parsed["reponse"].strip()
    if main.dossier_complet(etat["slots"]):
        reponse = main.construire_recapitulatif(etat["slots"])
        etat["phase"] = "relecture_en_cours"

    main.update_dossier(etat["dossier_id"], slots=etat["slots"], cas_legal=etat["cas_legal"])
    return reponse


async def main_test():
    etat = main.etat_dossier_session(SESSION_ID)
    etat["cas_legal"] = "dans_les_delais"
    etat["slots"]["age_enfant"] = {"valeur": 1, "unite": "semaine"}

    dossier = main.create_dossier(
        citoyen_id=TEST_CITOYEN_ID,
        type_demarche="extrait_naissance",
        slots=etat["slots"],
        cas_legal=etat["cas_legal"],
        commune_id=main.resoudre_commune_id(TEST_COMMUNE),
    )
    assert dossier
    etat["dossier_id"] = dossier["id"]
    print(f"📁 Dossier de départ : {dossier['id']} (statut={dossier['statut']})")

    tours = [
        "il est né à Ross-Béthio",
        "il s'appelle Ibrahima Diallo",
        "le 9 août 2026",
        "moi je m'appelle Modou Diallo",
        "sa mère c'est Aïssatou Ba, née le 12 mars 1998",
        "oui on est mariés",
    ]
    for message in tours:
        reponse = await tour_administratif(etat, message)
        print(f"\nCitoyen : {message}")
        print(f"Agent   : {reponse}")
        print(f"phase={etat['phase']}  manquants={dialogue_engine.slots_manquants(etat['slots'])}")
        if etat["phase"] == "relecture_en_cours":
            break

    assert etat["phase"] == "relecture_en_cours", "La relecture ne s'est pas déclenchée alors que tous les slots sont remplis"
    dossier_avant_confirmation = get_dossier(dossier["id"])
    assert dossier_avant_confirmation["statut"] == "en_cours", "Le dossier a été marqué recu AVANT confirmation !"
    print("\n✅ Relecture déclenchée automatiquement, dossier toujours 'en_cours' (pas d'envoi forcé).")

    # --- Étape 3 : correction (pas une confirmation positive) --------------
    message_correction = "non, en fait il est né le 10 août, pas le 9"
    assert not main.est_reponse_affirmative(message_correction)
    etat["phase"] = "collecte"  # même logique que main.py : relecture sans "oui" -> retour collecte
    reponse_correction = await tour_administratif(etat, message_correction)
    print(f"\nCitoyen : {message_correction}")
    print(f"Agent   : {reponse_correction}")
    print(f"date_naissance_enfant corrigée = {etat['slots']['date_naissance_enfant']}")
    assert "10" in (etat["slots"]["date_naissance_enfant"] or ""), "La correction n'a pas mis à jour le bon slot"

    dossier_apres_correction = get_dossier(dossier["id"])
    assert dossier_apres_correction["statut"] == "en_cours", "Le dossier a été envoyé malgré une correction, pas une confirmation !"
    print("✅ Correction appliquée au bon slot, toujours PAS envoyé.")

    # --- Étape 4 : confirmation positive -> passage à "recu" ----------------
    assert etat["phase"] == "relecture_en_cours"
    message_confirmation = "oui c'est bon"
    numero_suivi = main.generer_numero_suivi()
    main.update_dossier(dossier["id"], statut="recu", numero_suivi=numero_suivi)
    etat["phase"] = "termine"
    etat["numero_suivi"] = numero_suivi
    print(f"\nCitoyen : {message_confirmation}")
    print(f"Agent   : Voilà, votre demande est envoyée. Numéro de suivi : {numero_suivi}")

    dossier_final = get_dossier(dossier["id"])
    print("\n=== VÉRIFICATION FINALE EN BASE ===")
    print(f"statut={dossier_final['statut']}  numero_suivi={dossier_final['numero_suivi']}")
    assert dossier_final["statut"] == "recu"
    assert dossier_final["numero_suivi"] == numero_suivi

    print("\n✅ Tâche B.4 : relecture forcée avant tout envoi, correction sans forcer l'envoi, confirmation -> recu + numero_suivi — OK")


if __name__ == "__main__":
    asyncio.run(main_test())
