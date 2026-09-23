"""
Test manuel ponctuel — vérifie la nouvelle détection d'intention de bascule
pilotée par le LLM (remplace la liste de mots-clés français, cf. discussion
suite au bug pulaar du 2026-08-20). Reproduit exactement l'appel fait par le
WS (main.py, bloc "Mode information : réponse structurée") sur 2-3 tours,
sans ouvrir de vraie connexion WS (pas de micro/ASR disponible ici).
"""
import asyncio
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import httpx
from dotenv import load_dotenv
load_dotenv()

import main  # noqa: E402


async def appeler_info(message: str, history: list, commune: str = "Ross-Béthio") -> dict:
    results = main.search_demarches(message, commune=commune)
    resume = main.get_resume_rag(results)
    generator_prompt = main.build_generator_prompt(message, resume, history=history)
    payload = {
        "model": main.MODEL_GENERATOR,
        "messages": [
            {"role": "system", "content": main.SYSTEM_PROMPT_GENERATOR},
            {"role": "user", "content": generator_prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "reponse_information", "strict": True, "schema": main.SCHEMA_REPONSE_INFORMATION},
        },
        "stream": False,
        "temperature": 0.3,
    }
    headers = {"Authorization": f"Bearer {main.OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        return await main.call_openrouter_structured(client, headers, payload)


async def scenario(nom: str, tours: list):
    print(f"\n{'='*70}\n{nom}\n{'='*70}")
    history = []
    dernier_tour_extrait_naissance = False
    for message in tours:
        history.append({"role": "user", "content": message})
        parsed = await appeler_info(message, history)
        bascule = dernier_tour_extrait_naissance and parsed["confirme_demarrage_demarche"]
        print(f"\nCitoyen : {message!r}")
        print(f"  reponse                    : {parsed['reponse']}")
        print(f"  propose_demarrer_demarche  : {parsed['propose_demarrer_demarche']}")
        print(f"  confirme_demarrage_demarche: {parsed['confirme_demarrage_demarche']}")
        print(f"  => BASCULE CE TOUR         : {bascule}")
        history.append({"role": "assistant", "content": parsed["reponse"]})
        dernier_tour_extrait_naissance = parsed["propose_demarrer_demarche"]
        if bascule:
            return True
    return False


async def main_test():
    # --- Scénario 1 : français propre (cas simple) ---
    ok1 = await scenario("Scénario 1 — français propre", [
        "Je voudrais un extrait de naissance pour mon fils",
        "oui, je veux bien",
    ])
    assert ok1, "La bascule n'a pas été détectée en français propre !"
    print("\n✅ Scénario 1 : bascule détectée en français.")

    # --- Scénario 2 : vraies transcriptions pulaar bruitées (tes tests réels) ---
    ok2 = await scenario("Scénario 2 — vraies transcriptions pulaar (test terrain)", [
        "Biɗo yiiɗi estére de naissance.",
        "Eyyi mbiɗo joogui.",
    ])
    assert ok2, "La bascule n'a pas été détectée sur les transcriptions pulaar réelles !"
    print("\n✅ Scénario 2 : bascule détectée sur de vraies transcriptions pulaar bruitées.")

    # --- Scénario 3 : une question sans rapport ne doit PAS basculer ---
    ok3 = await scenario("Scénario 3 — pas de proposition, ne doit PAS basculer", [
        "C'est quoi les horaires de la mairie ?",
        "d'accord merci",
    ])
    assert not ok3, "Bascule déclenchée à tort alors qu'aucune démarche n'avait été proposée !"
    print("\n✅ Scénario 3 : pas de bascule à tort (pas de proposition préalable).")

    print("\n✅ Détection d'intention pilotée par le LLM — OK sur les 3 scénarios.")


if __name__ == "__main__":
    asyncio.run(main_test())
