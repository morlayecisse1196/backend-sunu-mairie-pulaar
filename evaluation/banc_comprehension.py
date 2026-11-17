"""
Banc d'essai du pulaar : ce que l'agent COMPREND, et ce qu'il DIT.

DEUX DIRECTIONS, DEUX MÉCANIQUES DIFFÉRENTES

Il n'existe AUCUN traducteur pulaar -> français dans ce projet. Le pulaar du
citoyen est lu DIRECTEMENT par le modèle de dialogue, à l'intérieur de prompts
rédigés en français. La compréhension n'est donc pas une traduction : c'est la
connaissance du pulaar qu'a le modèle généraliste, épaulée depuis peu par le
glossaire validé.

Dans l'autre sens, un vrai traducteur existe (SYSTEM_PROMPT_FORMATTER), du
français VERS le pulaar.

CE QU'ON MESURE

A. Compréhension : des réponses en pulaar, une par type de champ, et la valeur
   que l'extracteur en tire. Verdict net — la bonne valeur, ou pas.

B. Fidélité du traducteur : la même phrase traduite plusieurs fois (stabilité),
   puis retraduite vers le français par un appel séparé (aller-retour). Un
   aller-retour qui revient déformé est un indice, pas une preuve : l'erreur
   peut venir de l'un ou l'autre sens. C'est la seule mesure de sens possible
   sans être locuteur.
"""
from __future__ import annotations

import asyncio
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/opt/sunu/backend")
from dotenv import load_dotenv

load_dotenv("/opt/sunu/backend/.env")

from prompts import (  # noqa: E402
    SYSTEM_PROMPT_CHAMP_CIBLE,
    SYSTEM_PROMPT_FORMATTER,
    build_formatter_prompt,
    build_prompt_champ_cible,
    build_schema_champ_cible,
)
from services import llm  # noqa: E402

# --- A. Compréhension -------------------------------------------------------

CHAMPS = {
    "age": {"nom_champ": "age_enfant", "type_valeur": "age", "ordre": 10,
            "question": "Quel âge a votre enfant ?", "relances": [], "regle_validation": None},
    "booleen": {"nom_champ": "declarant_est_pere", "type_valeur": "booleen", "ordre": 20,
                "question": "Êtes-vous le père de l'enfant ?", "relances": [], "regle_validation": None},
    "sexe": {"nom_champ": "sexe_enfant", "type_valeur": "enum", "ordre": 30,
             "question": "Est-ce un garçon ou une fille ?", "relances": [],
             "regle_validation": "masculin|feminin"},
    "nom": {"nom_champ": "nom_enfant", "type_valeur": "texte", "ordre": 40,
            "question": "Quel est le nom complet de l'enfant ?", "relances": [], "regle_validation": None},
    "commune": {"nom_champ": "commune_naissance", "type_valeur": "texte", "ordre": 50,
                "question": "Dans quelle commune est né l'enfant ?", "relances": [], "regle_validation": None},
    "date": {"nom_champ": "date_naissance_enfant", "type_valeur": "date", "ordre": 60,
             "question": "Quelle est sa date de naissance ?", "relances": [], "regle_validation": None},
}

# (champ, message pulaar, valeur attendue, provenance du pulaar)
CAS = [
    ("age", "balɗe jeeɗiɗi", "7 jours", "pulaar_nombres.age_pulaar"),
    ("age", "lebbi ɗiɗi", "2 mois", "pulaar_nombres.age_pulaar"),
    ("age", "duuɓi tati", "3 ans", "glossaire + pulaar_nombres"),
    ("booleen", "eey", True, "pulaar_nombres.OUI"),
    ("booleen", "alaa", False, "pulaar_nombres.NON"),
    ("sexe", "gorko", "masculin", "question relue sexe_enfant"),
    ("sexe", "debbo", "feminin", "question relue sexe_enfant"),
    ("nom", "Ibrahima Diallo", "Ibrahima Diallo", "nom propre"),
    ("commune", "Ross-Béthio", "Ross-Béthio", "nom propre"),
    ("date", "ñalnde jeeɗiɗi, lewru Sattumbar, hitaande ujunaaje ɗiɗi e noogas e jeegom",
     "2026-09-07", "pulaar_nombres.date_pulaar"),
]


async def comprendre(cle_champ: str, message: str):
    champ = CHAMPS[cle_champ]
    schema = build_schema_champ_cible(champ["type_valeur"], champ.get("regle_validation"))
    return await llm.completer_structure(
        [
            {"role": "system", "content": SYSTEM_PROMPT_CHAMP_CIBLE},
            {"role": "user", "content": build_prompt_champ_cible(champ, message)},
        ],
        schema,
        nom_schema="champ_cible",
        temperature=0.3,
    )


def correspond(attendu, obtenu) -> bool:
    if isinstance(attendu, bool) or obtenu is None:
        return obtenu == attendu
    texte = str(obtenu).lower()
    if isinstance(attendu, str) and re.fullmatch(r"\d+ \w+", attendu):
        nombre, unite = attendu.split()
        return nombre in texte and unite[:3] in texte
    return str(attendu).lower() in texte or texte in str(attendu).lower()


async def partie_a():
    print("=" * 84)
    print("A. COMPRÉHENSION DU PULAAR — ce que l'extracteur tire du message")
    print("=" * 84)
    reussis = 0
    for cle_champ, message, attendu, source in CAS:
        analyse = await comprendre(cle_champ, message)
        obtenu = analyse.get("valeur")
        valide = analyse.get("reponse_valide")
        ok = bool(valide) and correspond(attendu, obtenu)
        reussis += ok
        print(f"  {'OK   ' if ok else 'ÉCHEC'} [{cle_champ:<8}] « {message[:44]:<44} »")
        print(f"         attendu {attendu!r:<22} obtenu {obtenu!r}   ({source})")
    print(f"\n  -> {reussis}/{len(CAS)} comprises")
    return reussis, len(CAS)


# --- B. Fidélité du traducteur ---------------------------------------------

A_TRADUIRE = [
    "C'est noté. Dans quelle commune votre enfant est-il né ?",
    "Votre demande est envoyée à la mairie. Gardez bien votre numéro de suivi.",
    "Je vous ai bien entendu.",
]

SYSTEM_RETOUR = (
    "Tu traduis du pulaar vers le français. Rends UNIQUEMENT la traduction, "
    "fidèle et littérale, sans commentaire, sans rien ajouter ni retirer."
)


async def traduire(texte_fr: str) -> str:
    return await llm.completer_texte(
        [
            {"role": "system", "content": SYSTEM_PROMPT_FORMATTER},
            {"role": "user", "content": build_formatter_prompt("", texte_fr, premier_tour=False)},
        ],
        temperature=0.3,
    )


async def retraduire(texte_pulaar: str) -> str:
    return await llm.completer_texte(
        [{"role": "system", "content": SYSTEM_RETOUR}, {"role": "user", "content": texte_pulaar}],
        temperature=0.0,
    )


def phrases(texte: str) -> int:
    return len([p for p in re.split(r"[.!?\n]+", texte) if p.strip()])


async def partie_b():
    print("\n" + "=" * 84)
    print("B. FIDÉLITÉ DU TRADUCTEUR FRANÇAIS -> PULAAR")
    print("=" * 84)
    for texte_fr in A_TRADUIRE:
        versions = [await traduire(texte_fr) for _ in range(3)]
        distinctes = len({v.strip() for v in versions})
        retour = await retraduire(versions[0])
        print(f"\n  FRANÇAIS   « {texte_fr} »   ({phrases(texte_fr)} phrase(s))")
        for i, v in enumerate(versions, 1):
            print(f"  pulaar {i}   « {v.strip()} »   ({phrases(v)} phrase(s))")
        print(f"  stabilité  {distinctes} version(s) différente(s) sur 3")
        print(f"  RETOUR FR  « {retour.strip()} »")


async def principal():
    await partie_a()
    await partie_b()


asyncio.run(principal())
