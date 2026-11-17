"""
Le glossaire validé comme vérité de terrain.

82 termes relus et attestés dans le corpus du projet : c'est la seule référence
pulaar dont on dispose qui ne soit pas l'avis d'un modèle. On demande à chaque
traducteur de rendre ces termes, et on compare.

Ce que la mesure vaut, et ne vaut pas : elle dit si un traducteur retombe sur
le mot que le projet a retenu. Un mot différent n'est pas forcément faux — le
pulaar a des synonymes — mais pour un service d'état civil, employer d'un tour
à l'autre un autre mot que celui du glossaire est en soi un défaut : le
citoyen doit reconnaître « deftere wulngo » quand il l'entend.

On mesure aussi, objectivement, deux choses qui ne demandent aucun jugement :
le mot rendu est-il resté en français, et la sortie est-elle vide.
"""
from __future__ import annotations

import sys
import time
import unicodedata

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/opt/sunu/backend")
from dotenv import load_dotenv

load_dotenv("/opt/sunu/backend/.env")

import torch  # noqa: E402
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer  # noqa: E402

from services.pulaar import TERMES, VALIDE  # noqa: E402

MODELE = "/opt/sunu/modeles/francais-pulaar-bf16"


def sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte.lower())
                   if unicodedata.category(c) != "Mn")


def main() -> None:
    tokeniseur = AutoTokenizer.from_pretrained(MODELE)
    modele = AutoModelForSeq2SeqLM.from_pretrained(MODELE, dtype=torch.bfloat16)
    modele.eval()
    tokeniseur.src_lang = "fra_Latn"
    cible = tokeniseur.convert_tokens_to_ids("fuv_Latn")

    termes = [t for t in TERMES if t.statut == VALIDE and t.pulaar.lower() != t.francais.lower()]
    exact = 0
    reste_francais = 0
    vides = 0
    ecarts = []
    debut = time.monotonic()

    for terme in termes:
        entrees = tokeniseur(terme.francais, return_tensors="pt")
        with torch.inference_mode():
            sortie = modele.generate(**entrees, forced_bos_token_id=cible,
                                     max_new_tokens=40, num_beams=4)
        rendu = tokeniseur.batch_decode(sortie, skip_special_tokens=True)[0].strip(" .?!")

        if not rendu:
            vides += 1
        elif sans_accents(rendu) == sans_accents(terme.pulaar):
            exact += 1
        else:
            # Le mot français recopié tel quel : défaut objectif, pas un
            # désaccord de synonyme.
            if sans_accents(terme.francais) in sans_accents(rendu):
                reste_francais += 1
            ecarts.append((terme.francais, terme.pulaar, rendu))

    duree = time.monotonic() - debut
    total = len(termes)
    print(f"{total} termes du glossaire validé, {duree:.0f}s ({duree / total:.2f}s par terme)\n")
    print(f"  rendus à l'identique du glossaire : {exact:>3}/{total}  ({100 * exact / total:.0f} %)")
    print(f"  mot français laissé tel quel      : {reste_francais:>3}/{total}  ({100 * reste_francais / total:.0f} %)")
    print(f"  sortie vide                       : {vides:>3}/{total}")
    print(f"\n  écarts (30 premiers) — français | glossaire | rendu par le modèle :")
    for francais, attendu, rendu in ecarts[:30]:
        print(f"    {francais:<26} {attendu:<24} {rendu}")


main()
