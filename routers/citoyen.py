"""
Routes mobiles citoyen (accessibilité) :
  * correction dictée à la voix (aucun clavier) ;
  * lecture du document généré champ par champ, avec audio par ligne ;
  * catalogue audio de l'interface ;
  * commune la plus proche (position GPS) pour l'inscription sans lecture.
"""
from __future__ import annotations

import math
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile

from asr_client import transcribe_audio
from auth import get_current_citoyen
from document_generator import resoudre_template
from dossiers_repo import get_commune, get_dossier, get_or_create_formulaire_acte, list_document_formulaires
from services import catalogue_audio, corrections, db, libelles_document
from services.journal import obtenir_logger
from temps_reel import audio as audio_entrant

router = APIRouter(tags=["citoyen"])
log = obtenir_logger("routers.citoyen")

RAYON_TERRE_KM = 6371.0
DISTANCE_MAX_COMMUNE_KM = 60.0


async def _dossier_du_citoyen(dossier_id: str, user: dict) -> dict:
    dossier = await db.executer(get_dossier, dossier_id)
    if not dossier:
        raise HTTPException(status_code=404, detail="Dossier introuvable")
    if dossier["citoyen_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Ce dossier ne vous appartient pas")
    return dossier


# --------------------------------------------------------------- corrections

@router.post("/mes-dossiers/{dossier_id}/demander-corrections/audio")
async def demander_corrections_par_la_voix(
    dossier_id: str,
    audio: UploadFile = File(...),
    champ_concerne: Optional[str] = Form(None),
    user: dict = Depends(get_current_citoyen),
):
    """
    Le citoyen DIT ce qui ne va pas (aucun clavier). L'audio est transcrit puis
    enregistré comme remarque, exactement comme la version écrite.
    """
    dossier = await _dossier_du_citoyen(dossier_id, user)
    contenu = await audio.read()
    try:
        wav = await audio_entrant.preparer_pour_asr(contenu)
    except audio_entrant.ErreurAudio as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message_fr})

    resultat = await transcribe_audio(wav)
    texte = (resultat.get("transcription") or "").strip() if resultat.get("success") else ""
    if not texte:
        raise HTTPException(
            status_code=422,
            detail={"code": "transcription_vide", "message": "Je n'ai pas compris votre message. Redites-le, s'il vous plaît."},
        )

    try:
        issue = await corrections.enregistrer_demande(
            dossier, texte, citoyen_id=user["id"], champ_concerne=champ_concerne, source_audio=True
        )
    except corrections.CorrectionImpossible as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message})

    return {"dossier": issue["dossier"], "remarque": issue["remarque"], "texte_compris": texte, "bloque": issue["bloque"]}


# ------------------------------------------------- lecture du document généré

@router.get("/mes-dossiers/{dossier_id}/document/lecture")
async def lecture_du_document(dossier_id: str, user: dict = Depends(get_current_citoyen)):
    """
    Contenu du document en champs séparés, chacun avec sa phrase et son audio :
    le citoyen écoute ligne par ligne et signale LA ligne fausse, au lieu de
    devoir décrire un problème sur un PDF qu'il ne peut pas lire.
    """
    dossier = await _dossier_du_citoyen(dossier_id, user)
    if dossier["statut"] not in ("en_attente_validation_citoyen", "finalise", "corrections_demandees"):
        raise HTTPException(status_code=400, detail="Aucun document n'est encore disponible pour ce dossier.")

    def _valeurs():
        commune = get_commune(dossier.get("commune_id"))
        formulaires = list_document_formulaires(dossier_id)
        formulaire_acte = get_or_create_formulaire_acte(dossier_id)
        if formulaire_acte and not any(f["id"] == formulaire_acte["id"] for f in formulaires):
            formulaires.append(formulaire_acte)
        champs = {
            champ["nom"]: champ["valeur"]
            for formulaire in formulaires
            for champ in (formulaire.get("champs") or [])
            if champ.get("valeur") is not None
        }
        resolues, _ = resoudre_template(dossier, commune, champs, dossier.get("cas_legal") == "jugement_requis")
        return resolues

    valeurs = await db.executer(_valeurs)
    champs = [
        {
            "cle": cle,
            "libelle": libelles_document.libelle(cle),
            "valeur": valeurs.get(cle),
            "phrase_fr": libelles_document.phrase_lecture(cle, valeurs.get(cle)),
            "audio_url": f"/mes-dossiers/{dossier_id}/document/lecture/{cle}/audio",
        }
        for cle in libelles_document.ORDRE_LECTURE
        if cle in valeurs
    ]
    return {"champs": champs, "statut": dossier["statut"]}


@router.get("/mes-dossiers/{dossier_id}/document/lecture/{cle}/audio")
async def audio_d_un_champ(dossier_id: str, cle: str, user: dict = Depends(get_current_citoyen)):
    """Audio pulaar d'UNE ligne du document (« Prénom de l'enfant : Ibrahima »)."""
    donnees = await lecture_du_document(dossier_id, user)
    champ = next((c for c in donnees["champs"] if c["cle"] == cle), None)
    if champ is None:
        raise HTTPException(status_code=404, detail="Champ introuvable dans ce document")
    octets = await catalogue_audio.audio_pour_texte(catalogue_audio.cle_pour_texte(champ["phrase_fr"]), champ["phrase_fr"])
    return Response(content=octets, media_type="audio/wav")


# ------------------------------------------------ catalogue audio d'interface

@router.get("/audio/ui")
async def catalogue_interface():
    """Phrases d'interface disponibles en audio pulaar (public : aucune donnée personnelle)."""
    return {
        "cles": [
            {"cle": cle, "texte_fr": texte, "url": f"/audio/ui/{cle}", "pret": catalogue_audio.existe(cle)}
            for cle, texte in catalogue_audio.PHRASES.items()
        ]
    }


@router.get("/audio/ui/{cle}")
async def audio_interface(cle: str):
    octets = await catalogue_audio.audio_interface(cle)
    if octets is None:
        raise HTTPException(status_code=404, detail="Phrase d'interface inconnue")
    return Response(content=octets, media_type="audio/wav", headers={"Cache-Control": "public, max-age=86400"})


# ------------------------------------------------------- commune la plus proche

def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance orthodromique (formule de haversine)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * RAYON_TERRE_KM * math.asin(math.sqrt(a))


@router.get("/communes/proche")
async def commune_la_plus_proche(
    lat: float = Query(..., ge=-90, le=90), lng: float = Query(..., ge=-180, le=180), limite: int = Query(3, ge=1, le=10)
):
    """
    Communes les plus proches d'une position — évite de faire chercher son nom
    de commune dans une longue liste à l'inscription. Renvoie une liste vide
    tant qu'aucune commune n'a de coordonnées (migration 015).
    """
    def _communes():
        return db.client().table("communes").select("id, nom, latitude, longitude").execute().data or []

    try:
        communes = await db.executer(_communes)
    except Exception as exc:  # noqa: BLE001
        if db.est_erreur_schema(exc):
            raise db.migration_manquante("015", "La recherche de commune par position")
        log.error("Lecture des communes échouée (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Liste des communes momentanément indisponible.")

    candidates = [
        {"id": c["id"], "nom": c["nom"], "distance_km": round(distance_km(lat, lng, c["latitude"], c["longitude"]), 1)}
        for c in communes
        if c.get("latitude") is not None and c.get("longitude") is not None
    ]
    proches = sorted(candidates, key=lambda c: c["distance_km"])[:limite]
    return {"communes": [c for c in proches if c["distance_km"] <= DISTANCE_MAX_COMMUNE_KM]}
