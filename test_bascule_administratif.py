"""
Test manuel — Sprint B, Tâche B.3 (bascule information -> administratif).

Exerce directement la logique ajoutée dans main.py (routing, détection de
bascule, création/mise à jour du dossier) avec le vrai LLM et la vraie base,
en sautant l'aller-retour ASR/TTS (déjà validé séparément en production) —
pas un vrai micro/audio disponible dans cet environnement pour rejouer
test_audio_ws_complet.py tel quel en multi-tours.

Simule 3 tours :
  1. Mode information : question sur l'extrait de naissance.
  2. "oui" -> bascule + création du Dossier (statut en_cours).
  3. Réponse donnant l'âge -> extraction du slot + calcul du cas_legal,
     persisté en base.
"""
import asyncio
import json
from dotenv import load_dotenv

load_dotenv()

import main  # noqa: E402 (charge les modèles RAG au passage, c'est attendu)
from dossiers_repo import get_dossier

TEST_CITOYEN_ID = "eeeabbec-a424-4acf-95cf-bb7611b1f275"  # profil réel existant (voir profiles)
TEST_COMMUNE = "Dakar"
SESSION_ID = "test_b3_session"


async def appeler_generateur(system_prompt: str, user_content: str, response_format: dict = None):
    """
    Retourne le dict déjà parsé si `response_format` est fourni (sortie
    structurée, via call_openrouter_structured — avec son retry sur JSON
    invalide, cf. main.py), sinon le texte brut de la réponse.
    """
    headers = {
        "Authorization": f"Bearer {main.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": main.MODEL_GENERATOR,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
        "temperature": 0.3,
    }
    async with main.httpx.AsyncClient(timeout=30.0) as client:
        if response_format:
            payload["response_format"] = response_format
            return await main.call_openrouter_structured(client, headers, payload)
        data = await main.call_openrouter(client, headers, payload)
        return data["choices"][0]["message"]["content"]


async def main_test():
    etat = main.etat_dossier_session(SESSION_ID)

    # --- Tour 1 : mode information ------------------------------------------------
    message1 = "comment avoir un extrait de naissance pour mon fils"
    results = main.search_demarches(message1, commune=TEST_COMMUNE)
    resume = main.get_resume_rag(results)
    etat["dernier_tour_extrait_naissance"] = bool(
        results and main.est_demarche_extrait_naissance(results[0].get("nom_demarche", ""))
    )
    prompt1 = main.build_generator_prompt(message1, resume, history=[])
    reponse1 = (await appeler_generateur(main.SYSTEM_PROMPT_GENERATOR, prompt1)).strip()
    print("=== TOUR 1 (information) ===")
    print("Citoyen :", message1)
    print("Agent   :", reponse1)
    print("dernier_tour_extrait_naissance =", etat["dernier_tour_extrait_naissance"])
    assert etat["dernier_tour_extrait_naissance"], "RAG n'a pas matché l'extrait de naissance — précondition du test invalide"

    # --- Tour 2 : "oui" -> bascule -------------------------------------------------
    message2 = "oui je veux bien commencer"
    assert etat["mode"] == "information" and main.detecter_acceptation_bascule(message2)
    etat["mode"] = "administratif"
    commune_id_initial = main.resoudre_commune_id(TEST_COMMUNE)
    dossier = main.create_dossier(
        citoyen_id=TEST_CITOYEN_ID,
        type_demarche="extrait_naissance",
        slots=etat["slots"],
        cas_legal=etat["cas_legal"],
        commune_id=commune_id_initial,
    )
    assert dossier, "Échec de création du dossier (voir logs ⚠️ ci-dessus)"
    etat["dossier_id"] = dossier["id"]
    print("\n=== TOUR 2 (bascule) ===")
    print("Citoyen :", message2)
    print(f"📁 Dossier créé : id={dossier['id']} statut={dossier['statut']} cas_legal={dossier['cas_legal']}")
    assert dossier["statut"] == "en_cours"

    admin_prompt2 = main.build_generator_prompt_administratif(message2, etat["slots"], etat["cas_legal"])
    schema = {"type": "json_schema", "json_schema": {"name": "slots_update", "strict": True, "schema": main.SLOTS_JSON_SCHEMA_ADMINISTRATIF}}
    parsed2 = await appeler_generateur(main.SYSTEM_PROMPT_GENERATOR_ADMINISTRATIF, admin_prompt2, schema)
    print("Agent   :", parsed2["reponse"])
    print("slot_suivant_attendu =", parsed2["slot_suivant_attendu"])
    etat["slots"] = main.fusionner_slots(etat["slots"], parsed2["slots_maj"])
    main.update_dossier(dossier["id"], slots=etat["slots"])

    # --- Tour 3 : donne l'âge -------------------------------------------------------
    message3 = "il est né il y a une semaine"
    admin_prompt3 = main.build_generator_prompt_administratif(message3, etat["slots"], etat["cas_legal"])
    parsed3 = await appeler_generateur(main.SYSTEM_PROMPT_GENERATOR_ADMINISTRATIF, admin_prompt3, schema)
    print("\n=== TOUR 3 (âge donné) ===")
    print("Citoyen :", message3)
    print("Agent   :", parsed3["reponse"])
    print("slot_suivant_attendu =", parsed3["slot_suivant_attendu"])
    etat["slots"] = main.fusionner_slots(etat["slots"], parsed3["slots_maj"])

    age = etat["slots"]["age_enfant"]
    age_jours = main.normaliser_age(age["valeur"], age["unite"])
    etat["cas_legal"] = main.determiner_cas_legal(age_jours)
    main.update_dossier(dossier["id"], slots=etat["slots"], cas_legal=etat["cas_legal"])

    # --- Vérification en base --------------------------------------------------------
    dossier_relu = get_dossier(dossier["id"])
    print("\n=== VÉRIFICATION EN BASE ===")
    print(f"id={dossier_relu['id']}")
    print(f"statut={dossier_relu['statut']}")
    print(f"cas_legal={dossier_relu['cas_legal']}")
    print(f"slots={json.dumps(dossier_relu['slots'], ensure_ascii=False)}")

    assert dossier_relu["cas_legal"] == "dans_les_delais", f"cas_legal incohérent : {dossier_relu['cas_legal']}"
    assert dossier_relu["slots"]["age_enfant"]["valeur"] is not None, "age_enfant pas persisté"
    # slot_suivant_attendu ne redemande jamais l'âge une fois connu (RG "une seule question à la fois")
    assert parsed3["slot_suivant_attendu"] != "age_enfant", "le slot déjà rempli (âge) a été reposé !"

    print("\n✅ Tâche B.3 : bascule + création dossier + cas_legal cohérent + pas de re-question — OK")


if __name__ == "__main__":
    asyncio.run(main_test())
