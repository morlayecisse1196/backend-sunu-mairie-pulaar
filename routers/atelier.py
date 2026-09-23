"""
Atelier pulaar : relire, corriger, écouter, valider depuis le web (étape 4.2).

La relecture passait par un fichier TSV exporté puis réimporté à la main.
Trois choses la rendaient pénible et risquée : il fallait un accès au serveur,
on ne pouvait pas ENTENDRE la phrase avant de la valider — alors que c'est de
l'oral — et une colonne d'identifiants modifiée par mégarde dans un tableur
envoyait les traductions au mauvais endroit.

Ces endpoints donnent la même chose depuis le navigateur, et surtout
l'écoute : cocher « relu » sans avoir entendu la phrase, pour du pulaar, ne
veut pas dire grand-chose.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from auth import get_current_admin
from services import atelier, catalogue_audio, demarche, phrases
from services.journal import obtenir_logger
from tts_client import NARRATION_TIMEOUT_SECONDS, TTSError, synthesize_remote

router = APIRouter(prefix="/admin/atelier", tags=["atelier"])
log = obtenir_logger("routers.atelier")

LONGUEUR_MAX_PULAAR = 2000


class TraductionIn(BaseModel):
    pulaar: str = Field(min_length=1, max_length=LONGUEUR_MAX_PULAAR)
    #: `false` enregistre sans affirmer que la phrase a été relue — ce qui est
    #: le cas le plus fréquent : on dépose, on écoute, puis on valide.
    valider: bool = False


class EcouteIn(BaseModel):
    pulaar: str = Field(min_length=1, max_length=LONGUEUR_MAX_PULAAR)


@router.get("/phrases")
async def lister_phrases(
    demarche_: str = Query(demarche.TYPE_DEMARCHE_PAR_DEFAUT, alias="demarche"),
    admin: dict = Depends(get_current_admin),
):
    """Tout ce que l'agent dit au citoyen, dans l'ordre du dialogue."""
    liste = atelier.collecter(demarche_)
    return {
        "demarche": demarche_,
        "avancement": atelier.avancement(demarche_),
        "phrases": [p.en_dict() for p in liste],
    }


@router.put("/phrases/{identifiant:path}")
async def enregistrer_phrase(
    identifiant: str,
    corps: TraductionIn,
    demarche_: str = Query(demarche.TYPE_DEMARCHE_PAR_DEFAUT, alias="demarche"),
    admin: dict = Depends(get_current_admin),
):
    """
    Range une traduction, et note qui l'a relue.

    L'identifiant vient de la liste et n'est jamais saisi à la main : un
    identifiant inconnu est donc le signe d'une démarche modifiée entre-temps,
    pas d'une faute de frappe. On refuse plutôt que d'écrire à côté.
    """
    try:
        resultat = atelier.enregistrer(
            {identifiant: corps.pulaar},
            valider=corps.valider,
            par=admin.get("email") or admin.get("id") or "admin",
            type_demarche=demarche_,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if resultat["phrases"] == 0:
        raise HTTPException(status_code=422, detail="Traduction vide : rien à enregistrer.")
    return {"enregistre": True, **resultat}


@router.post("/ecouter")
async def ecouter(corps: EcouteIn, admin: dict = Depends(get_current_admin)):
    """
    Synthétise un texte pulaar pour que le relecteur l'ENTENDE avant de valider.

    C'est le cœur de l'atelier : ces phrases sont dites, pas lues. Une
    traduction juste à l'écrit peut être imprononçable, ou accentuée au mauvais
    endroit par le synthétiseur — on ne le voit pas, on l'entend.

    Le résultat est rangé dans le cache par empreinte du texte (étape 3.4) :
    écouter une phrase qu'on finit par valider telle quelle, c'est aussi la
    pré-générer, sans aucun appel supplémentaire.
    """
    texte = corps.pulaar.strip()
    deja = await catalogue_audio.audio_phrase(texte)
    if deja is not None:
        return Response(content=deja, media_type="audio/wav",
                        headers={"X-Audio-Source": "pre-genere"})
    try:
        audio = await synthesize_remote(texte, timeout=NARRATION_TIMEOUT_SECONDS)
    except TTSError as exc:
        # 503 et non 500 : le service vocal est temporairement indisponible,
        # l'interface doit proposer de réessayer, pas afficher un bug.
        raise HTTPException(status_code=503, detail=f"Service vocal indisponible : {exc}") from exc
    await catalogue_audio.enregistrer_phrase(texte, audio)
    return Response(content=audio, media_type="audio/wav",
                    headers={"X-Audio-Source": "synthetise"})


@router.get("/historique")
async def lire_historique(
    identifiant: Optional[str] = Query(None),
    demarche_: str = Query(demarche.TYPE_DEMARCHE_PAR_DEFAUT, alias="demarche"),
    admin: dict = Depends(get_current_admin),
):
    """Qui a relu quoi, quand, et ce que la phrase disait avant."""
    return {"historique": atelier.historique(identifiant, demarche_)}


@router.get("/signalements")
async def lire_signalements(admin: dict = Depends(get_current_admin)):
    """
    Ce qui a dû être traduit à la volée depuis le démarrage du serveur
    (étape 3.5).

    C'est la liste du travail restant, vue depuis les vrais dialogues et non
    depuis la base : une phrase qui revient souvent ici mérite d'être relue
    avant une phrase rare, même si les deux sont également « non relues ».
    """
    compteurs = phrases.signalements()
    return {
        "signalements": [
            {"origine": origine, "fois": fois}
            for origine, fois in sorted(compteurs.items(), key=lambda c: -c[1])
        ],
        "total": sum(compteurs.values()),
    }
