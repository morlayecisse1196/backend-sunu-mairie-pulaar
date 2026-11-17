"""
Les vraies phrases de l'agent, traduites par le modèle entraîné.

Les mots isolés sont un exercice difficile pour un modèle affiné sur des
phrases : le score de 4 % sur le glossaire pourrait le desservir injustement.
On reprend donc les questions RÉELLEMENT posées par l'agent, telles qu'elles
sont en base — et pour chacune, on dispose déjà du pulaar relu par un
locuteur. C'est la meilleure vérité de terrain du projet.

Deux mesures sans jugement linguistique :
  * des mots français restent-ils dans la sortie pulaar ?
  * le nombre de phrases est-il conservé (le traducteur ajoute-t-il) ?
"""
from __future__ import annotations

import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/opt/sunu/backend")
from dotenv import load_dotenv

load_dotenv("/opt/sunu/backend/.env")

import torch  # noqa: E402
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer  # noqa: E402

from supabase_client import get_supabase_client  # noqa: E402

MODELE = "/opt/sunu/modeles/francais-pulaar-bf16"

# Mots français qui ne doivent PAS survivre dans une sortie pulaar.
FRANCAIS = re.compile(
    r"\b(le|la|les|un|une|des|du|de|votre|vous|votre|est|quel|quelle|quand|où|"
    r"enfant|naissance|commune|mairie|démarche|document|photo|nom|père|mère|"
    r"date|bonjour|merci|certificat|extrait|acte|pièce|identité|famille)\b",
    re.IGNORECASE,
)


def phrases(texte: str) -> int:
    return len([p for p in re.split(r"[.!?]+", texte) if p.strip()])


def main() -> None:
    client = get_supabase_client()
    lignes = (
        client.table("demarche_champs")
        .select("question, question_pulaar, pulaar_valide, ordre")
        .eq("type_demarche", "extrait_naissance")
        .order("ordre")
        .execute()
        .data
    )
    relues = [l for l in lignes if l.get("pulaar_valide") and l.get("question")]

    tokeniseur = AutoTokenizer.from_pretrained(MODELE)
    modele = AutoModelForSeq2SeqLM.from_pretrained(MODELE, dtype=torch.bfloat16)
    modele.eval()
    tokeniseur.src_lang = "fra_Latn"
    cible = tokeniseur.convert_tokens_to_ids("fuv_Latn")

    fuites = 0
    ajouts = 0
    debut = time.monotonic()
    for ligne in relues:
        question = ligne["question"]
        entrees = tokeniseur(question, return_tensors="pt")
        with torch.inference_mode():
            sortie = modele.generate(**entrees, forced_bos_token_id=cible,
                                     max_new_tokens=80, num_beams=4)
        rendu = tokeniseur.batch_decode(sortie, skip_special_tokens=True)[0].strip()

        mots_fr = sorted({m.group(0).lower() for m in FRANCAIS.finditer(rendu)})
        if mots_fr:
            fuites += 1
        if phrases(rendu) > phrases(question):
            ajouts += 1

        print(f"\nFR     « {question} »")
        print(f"NLLB   « {rendu} »")
        print(f"RELU   « {ligne['question_pulaar']} »")
        if mots_fr:
            print(f"  ⚠  mots français restés : {', '.join(mots_fr)}")

    total = len(relues)
    print(f"\n{'=' * 76}")
    print(f"  {total} questions réelles, {time.monotonic() - debut:.0f}s")
    print(f"  sorties contenant encore du français : {fuites}/{total}  ({100 * fuites / total:.0f} %)")
    print(f"  sorties ayant ajouté une phrase      : {ajouts}/{total}")


main()
