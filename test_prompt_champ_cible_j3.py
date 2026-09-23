"""
Test manuel — Sprint J, Tâche J.3 (prompt LLM ciblé par champ, prompts.py).

Critère de validation explicite (SUNU_MAIRIE_PROMPTS.md, Tâche J.3) : un appel
réel isolé sur le champ `date_naissance_mere`, avec une réponse qui parle
clairement d'autre chose (la date de naissance du DÉCLARANT), doit retourner
`reponse_valide=false` — pas une valeur absorbée à tort.

Appel réseau réel vers OpenRouter (google/gemini-2.5-flash) — pas de mock,
comme les autres tests de sortie structurée du projet (cf. test_bascule_administratif.py).
"""
import asyncio
import json
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import httpx
from dotenv import load_dotenv
load_dotenv()

from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL
from prompts import SYSTEM_PROMPT_CHAMP_CIBLE, build_schema_champ_cible, build_prompt_champ_cible

MODEL_GENERATOR = "google/gemini-2.5-flash"

CHAMP_DATE_NAISSANCE_MERE = {
    "nom_champ": "date_naissance_mere",
    "type_valeur": "date",
    "question": "Quelle est sa date de naissance, à elle ?",
}

HEADERS = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
}


async def appeler_champ_cible(champ: dict, message: str, derniere_raison_invalide: str = None) -> dict:
    prompt = build_prompt_champ_cible(champ, message, derniere_raison_invalide)
    schema = build_schema_champ_cible(champ["type_valeur"])
    payload = {
        "model": MODEL_GENERATOR,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_CHAMP_CIBLE},
            {"role": "user", "content": prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "champ_cible", "strict": True, "schema": schema},
        },
        "stream": False,
        "temperature": 0.3,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{OPENROUTER_BASE_URL}/chat/completions", headers=HEADERS, json=payload)
        response.raise_for_status()
        data = response.json()
        return json.loads(data["choices"][0]["message"]["content"])


async def main_test():
    # --- Cas 1 (le critère explicite) : réponse hors sujet, parle du déclarant
    # (une autre personne) alors qu'on demande la date de naissance de la MÈRE.
    resultat = await appeler_champ_cible(
        CHAMP_DATE_NAISSANCE_MERE,
        "Moi je suis né le 3 janvier 1990, c'est ma date de naissance à moi le déclarant.",
    )
    print("Cas 1 (hors sujet - date du déclarant) :", resultat)
    assert resultat["reponse_valide"] is False, (
        f"Le LLM a absorbé à tort la date du déclarant comme réponse sur la mère ! {resultat}"
    )
    assert resultat["valeur"] is None, f"valeur aurait dû rester null : {resultat}"
    assert resultat["reponse"], "une reformulation était attendue"
    print("OK - reponse_valide=false, valeur=null, comme attendu.\n")

    # --- Cas 2 (contrôle positif) : réponse qui répond clairement à LA bonne question.
    resultat2 = await appeler_champ_cible(
        CHAMP_DATE_NAISSANCE_MERE,
        "Elle est née le 12 mars 1998.",
    )
    print("Cas 2 (réponse correcte sur la mère) :", resultat2)
    assert resultat2["reponse_valide"] is True, f"Une réponse claire sur la mère aurait dû être acceptée : {resultat2}"
    assert resultat2["valeur"], f"une valeur de date était attendue : {resultat2}"
    print("OK - reponse_valide=true, valeur extraite.\n")

    # --- Cas 3 : reformulation après échec — vérifie que la raison précédente
    # est bien prise en compte (pas juste la même phrase répétée).
    resultat3 = await appeler_champ_cible(
        CHAMP_DATE_NAISSANCE_MERE,
        "Je ne sais plus trop.",
        derniere_raison_invalide="Cette date doit être antérieure à celle de date_naissance_enfant.",
    )
    print("Cas 3 (reformulation avec raison d'échec) :", resultat3)
    assert resultat3["reponse_valide"] is False
    assert resultat3["reponse"] and resultat3["reponse"] != CHAMP_DATE_NAISSANCE_MERE["question"], (
        "la reformulation ne doit pas être la question d'origine répétée mot pour mot"
    )
    print("OK - reformulation produite, différente de la question d'origine.\n")

    print("Tâche J.3 validée : le prompt ciblé par champ isole correctement le champ demandé (appel réel OpenRouter).")


if __name__ == "__main__":
    asyncio.run(main_test())
