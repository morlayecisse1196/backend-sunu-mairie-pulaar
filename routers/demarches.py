"""
Éditeur de démarche, côté web (étape 4.1).

Ajouter une question au dialogue demandait jusqu'ici d'écrire du SQL et de
redéployer. Une mairie qui découvre qu'il lui faut le nom du village, et pas
seulement la commune, attendait la prochaine livraison.

Ces endpoints ouvrent l'édition à l'administration — mais aucun n'écrit sans
passer par `services/editeur.verifier`, qui travaille sur la démarche telle
qu'elle SERAIT. Une démarche cassée ne se voit pas ici : elle se voit dans un
dialogue, devant un citoyen qui ne peut ni comprendre ni signaler.

BROUILLON ET PUBLICATION (étape 4.4)

Les modifications portent sur les tables vivantes, c'est-à-dire le BROUILLON.
Aucun citoyen ne l'entend : un dialogue démarre sur la dernière version
PUBLIÉE et la garde jusqu'au bout (étape 2.4). Une modification ne touche
donc personne avant `POST .../publier` — et `POST .../abandonner` y renonce.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import get_current_admin
from services import brouillon, demarche, editeur, simulateur
from services.journal import obtenir_logger

router = APIRouter(prefix="/admin/demarches", tags=["demarches"])
log = obtenir_logger("routers.demarches")

FAMILLES = tuple(editeur.CLES)


class ElementIn(BaseModel):
    """Les colonnes à écrire. Volontairement libre : le vérificateur tranche."""

    valeurs: dict[str, Any] = Field(default_factory=dict)


class OrdreIn(BaseModel):
    cles: list[str] = Field(min_length=1)


class ScenarioIn(BaseModel):
    """Ce que le citoyen répond, déjà extrait — cf. `services/simulateur`."""

    reponses: dict[str, Any] = Field(default_factory=dict)


def _refus(exc: editeur.EditionRefusee) -> HTTPException:
    """
    409 et non 400 : la demande est bien formée, c'est l'ÉTAT de la démarche
    qui la rend impossible. L'interface doit montrer les problèmes, pas
    accuser la saisie.
    """
    return HTTPException(
        status_code=409,
        detail={
            "message": "Cette modification casserait le dialogue.",
            "problemes": [p.en_dict() for p in exc.problemes],
        },
    )


def _indisponible(exc: demarche.LectureImpossible) -> HTTPException:
    """
    503 : une lecture ratée ne doit jamais passer pour « rien n'a changé »
    ni pour « tout a été supprimé ».
    """
    return HTTPException(status_code=503, detail=f"Base injoignable, réessayez : {exc}")


def _famille_connue(famille: str) -> str:
    if famille not in FAMILLES:
        raise HTTPException(status_code=404, detail=f"Famille inconnue : {famille}")
    return famille


@router.get("")
async def lister(admin: dict = Depends(get_current_admin)):
    """Les démarches que le dialogue sait mener."""
    return {
        "demarches": [
            {
                "type_demarche": d.type_demarche,
                "libelle": d.libelle,
                "traitable": d.traitable,
                "version": d.version,
                "mots_cles": list(d.mots_cles),
            }
            for d in demarche.demarches_traitables()
        ]
    }


@router.get("/{type_demarche}")
async def detail(type_demarche: str, admin: dict = Depends(get_current_admin)):
    """
    Tout ce qui décrit la démarche, plus son état de santé.

    `sequence` mêle champs et pièces dans l'ordre réel : le citoyen ne
    rencontre pas deux tables, il rencontre une suite. Éditer la séquence sans
    la voir telle qu'elle se déroule, c'est éditer à l'aveugle.
    """
    vivant = demarche.instantane(type_demarche)
    return {
        "type_demarche": type_demarche,
        "definition": {
            "libelle": vivant.definition.libelle,
            "traitable": vivant.definition.traitable,
            "champ_age": vivant.definition.champ_age,
            "mots_cles": list(vivant.definition.mots_cles),
            "version": vivant.version,
            "en_base": vivant.definition.en_base,
        },
        "sequence": editeur.sequence(type_demarche),
        "champs": vivant.champs,
        "documents": vivant.documents,
        "cas": vivant.cas,
        "regles": vivant.regles,
        "gabarits": list(demarche.gabarits_demarche(type_demarche).values()),
        "problemes": [p.en_dict() for p in editeur.verifier(type_demarche)],
        "brouillon": _etat_du_brouillon(type_demarche),
    }


def _etat_du_brouillon(type_demarche: str) -> dict | None:
    """`None` quand la base n'a pas répondu : l'écran le dit, sans inventer."""
    try:
        return brouillon.etat(type_demarche).en_dict()
    except demarche.LectureImpossible as exc:
        log.warning("État du brouillon de %r illisible : %s", type_demarche, exc)
        return None


@router.get("/{type_demarche}/brouillon")
async def etat_du_brouillon(type_demarche: str, admin: dict = Depends(get_current_admin)):
    """Ce qui attend d'être publié : ce que les citoyens n'entendent pas encore."""
    try:
        return brouillon.etat(type_demarche).en_dict()
    except demarche.LectureImpossible as exc:
        raise _indisponible(exc) from exc


@router.post("/{type_demarche}/abandonner")
async def abandonner_le_brouillon(type_demarche: str, admin: dict = Depends(get_current_admin)):
    """
    Remet la démarche dans l'état de la version publiée.

    Irréversible : les modifications non publiées sont perdues. L'interface
    demande confirmation ; ici, on refuse seulement ce qui viderait la
    démarche.
    """
    par = admin.get("email") or admin.get("id")
    try:
        remis = brouillon.abandonner(type_demarche, par=par)
    except brouillon.AbandonImpossible as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except demarche.LectureImpossible as exc:
        raise _indisponible(exc) from exc
    return {"remis": remis}


@router.get("/{type_demarche}/verification")
async def verification(type_demarche: str, admin: dict = Depends(get_current_admin)):
    """L'état de santé seul — pour rafraîchir sans tout recharger."""
    problemes = editeur.verifier(type_demarche)
    return {
        "problemes": [p.en_dict() for p in problemes],
        "bloquants": sum(1 for p in problemes if p.gravite == editeur.BLOQUANT),
    }


@router.put("/{type_demarche}/{famille}/{cle}")
async def enregistrer_element(
    type_demarche: str, famille: str, cle: str, corps: ElementIn,
    admin: dict = Depends(get_current_admin),
):
    """Crée ou modifie un champ, une pièce, un cas, une règle, un gabarit."""
    try:
        avertissements = editeur.enregistrer(
            _famille_connue(famille), cle, corps.valeurs, type_demarche=type_demarche)
    except editeur.EditionRefusee as exc:
        raise _refus(exc) from exc
    log.info("Démarche %r : %s %r modifié par %s.",
             type_demarche, famille, cle, admin.get("email") or admin.get("id"))
    return {"enregistre": True, "avertissements": [p.en_dict() for p in avertissements]}


@router.delete("/{type_demarche}/{famille}/{cle}")
async def supprimer_element(
    type_demarche: str, famille: str, cle: str,
    admin: dict = Depends(get_current_admin),
):
    """
    Retire un élément — si rien d'autre n'en dépend.

    C'est la modification la plus risquée de l'écran : supprimer un champ cité
    par une condition ou par le récapitulatif ne casse rien de visible ici.
    """
    try:
        avertissements = editeur.supprimer(
            _famille_connue(famille), cle, type_demarche=type_demarche)
    except editeur.EditionRefusee as exc:
        raise _refus(exc) from exc
    log.warning("Démarche %r : %s %r SUPPRIMÉ par %s.",
                type_demarche, famille, cle, admin.get("email") or admin.get("id"))
    return {"supprime": True, "avertissements": [p.en_dict() for p in avertissements]}


@router.post("/{type_demarche}/{famille}/ordre")
async def reordonner_famille(
    type_demarche: str, famille: str, corps: OrdreIn,
    admin: dict = Depends(get_current_admin),
):
    """Renumérote une famille. La liste doit être COMPLÈTE (cf. editeur.reordonner)."""
    try:
        editeur.reordonner(_famille_connue(famille), corps.cles, type_demarche=type_demarche)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"reordonne": True}


@router.post("/{type_demarche}/publier")
async def publier(type_demarche: str, admin: dict = Depends(get_current_admin)):
    """
    Fige la démarche dans une nouvelle version (étape 2.4).

    Refusé tant qu'un problème bloquant subsiste : publier une démarche cassée
    la graverait dans une version, et les dialogues qui démarreront dessus
    n'auront aucun moyen d'en sortir.

    Refusé aussi quand rien n'a changé : une version identique à la
    précédente brouille l'historique (« qu'a changé la v7 ? — rien »).
    """
    try:
        if not brouillon.etat(type_demarche).a_publier:
            raise HTTPException(status_code=409, detail={
                "message": "Rien à publier : le brouillon est identique à la version en service.",
                "problemes": [],
            })
    except demarche.LectureImpossible as exc:
        raise _indisponible(exc) from exc
    problemes = editeur.verifier(type_demarche)
    bloquants = [p for p in problemes if p.gravite == editeur.BLOQUANT]
    if bloquants:
        raise HTTPException(status_code=409, detail={
            "message": "Publication refusée : la démarche a des problèmes bloquants.",
            "problemes": [p.en_dict() for p in bloquants],
        })
    try:
        version = demarche.publier(type_demarche, par=admin.get("email") or admin.get("id"))
    except demarche.LectureImpossible as exc:
        raise _indisponible(exc) from exc
    return {"version": version}


@router.get("/{type_demarche}/scenario")
async def scenario_de_depart(type_demarche: str, admin: dict = Depends(get_current_admin)):
    """
    Un scénario plausible, prêt à jouer.

    Ouvrir le simulateur sur un formulaire vide obligerait à inventer treize
    réponses avant de voir quoi que ce soit. Les dates respectent les règles
    croisées de la démarche — un scénario de départ qui se fait refuser dès la
    deuxième question fait croire qu'on a cassé quelque chose.
    """
    return {"reponses": simulateur.scenario_type(type_demarche)}


@router.post("/{type_demarche}/simuler")
async def simuler(
    type_demarche: str, corps: ScenarioIn,
    version: Optional[int] = Query(None),
    admin: dict = Depends(get_current_admin),
):
    """
    Déroule la démarche avec ce scénario, sans téléphone et sans modèle.

    Le rapport dit jusqu'où le dialogue va, quel cas légal en sort, et — c'est
    le critère de vérification de l'étape 3 — quelles phrases repasseraient
    encore par le traducteur.

    Ce qui n'est PAS simulé : l'extraction. Dans un vrai dialogue, le citoyen
    parle et un modèle en tire la valeur. Ici la valeur est donnée. Le
    simulateur répond à « ma démarche se déroule-t-elle correctement ? », pas
    à « le modèle comprend-il mes concitoyens ? ».
    """
    rapport = simulateur.jouer(corps.reponses, type_demarche, version)
    return rapport.en_dict()
