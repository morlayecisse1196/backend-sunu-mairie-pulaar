"""
Contrôle qualité des photos de pièces justificatives, à l'upload.

Pourquoi : un citoyen qui ne lit pas ne peut pas juger lui-même si sa photo de
CNI est lisible. Une photo floue ou sombre n'était découverte que par le
consultant, des jours plus tard — et le citoyen devait tout recommencer. On
refuse maintenant tout de suite, avec une consigne simple, dite à voix haute.

Mesures (OpenCV, déjà présent pour l'OCR) :
  * taille — plus petit côté en pixels ;
  * luminosité — moyenne des niveaux de gris ;
  * netteté — variance du laplacien (faible ⇒ image floue).
Seuils volontairement PRUDENTS (ne refuser que l'inexploitable), ajustables par
variables d'environnement à partir des photos réelles du terrain.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

COTE_MIN_PIXELS = int(os.getenv("PHOTO_COTE_MIN", "480"))
LUMINOSITE_MIN = float(os.getenv("PHOTO_LUMINOSITE_MIN", "45"))
LUMINOSITE_MAX = float(os.getenv("PHOTO_LUMINOSITE_MAX", "240"))
NETTETE_MIN = float(os.getenv("PHOTO_NETTETE_MIN", "35"))
COTE_ANALYSE = 1280  # l'analyse se fait sur une copie réduite : mesures comparables quelle que soit la résolution

MESSAGES = {
    "photo_illisible": "Je n'arrive pas à ouvrir cette photo. Reprenez-la, s'il vous plaît.",
    "photo_trop_petite": "La photo est trop petite. Rapprochez le téléphone du document et reprenez la photo.",
    "photo_sombre": "La photo est trop sombre. Mettez-vous près d'une fenêtre ou allumez la lumière, puis reprenez la photo.",
    "photo_surexposee": "La photo est trop claire, on ne voit pas l'écriture. Évitez le soleil direct ou le flash, puis reprenez la photo.",
    "photo_floue": "La photo est floue. Posez le document bien à plat, tenez le téléphone sans bouger, puis reprenez la photo.",
}


@dataclass
class Verdict:
    acceptable: bool
    code: Optional[str] = None
    message_fr: Optional[str] = None
    mesures: dict = field(default_factory=dict)


def _refus(code: str, mesures: dict) -> Verdict:
    return Verdict(False, code, MESSAGES[code], mesures)


def evaluer(octets: bytes) -> Verdict:
    image = cv2.imdecode(np.frombuffer(octets, dtype=np.uint8), cv2.IMREAD_GRAYSCALE) if octets else None
    if image is None:
        return _refus("photo_illisible", {})

    hauteur, largeur = image.shape[:2]
    mesures: dict = {"largeur": int(largeur), "hauteur": int(hauteur)}
    if min(hauteur, largeur) < COTE_MIN_PIXELS:
        return _refus("photo_trop_petite", mesures)

    echelle = COTE_ANALYSE / max(hauteur, largeur)
    if echelle < 1:
        image = cv2.resize(image, (int(largeur * echelle), int(hauteur * echelle)), interpolation=cv2.INTER_AREA)

    luminosite = float(image.mean())
    nettete = float(cv2.Laplacian(image, cv2.CV_64F).var())
    mesures.update(luminosite=round(luminosite, 1), nettete=round(nettete, 1))

    if luminosite < LUMINOSITE_MIN:
        return _refus("photo_sombre", mesures)
    if luminosite > LUMINOSITE_MAX:
        return _refus("photo_surexposee", mesures)
    if nettete < NETTETE_MIN:
        return _refus("photo_floue", mesures)
    return Verdict(True, mesures=mesures)
