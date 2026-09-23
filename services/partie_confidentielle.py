"""
Refus de la partie confidentielle du certificat de décès (étape 5.4).

Le formulaire officiel est en deux parties détachables. La partie HAUTE,
« CERTIFICAT DE DÉCÈS », est celle que les mairies conservent : c'est la seule
que l'application demande. La partie BASSE, « CERTIFICAT DE CAUSES DE DÉCÈS »,
porte la cause médicale du décès. Le formulaire lui-même indique qu'elle « ne
peut être communiqué ni en original ni en copie » et « sera détruit » par le
médecin chargé de la statistique.

POURQUOI UN CONTRÔLE, ET PAS SEULEMENT UNE CONSIGNE

La consigne est dite à voix haute avant la photo. Mais le citoyen ne lit pas,
le formulaire arrive souvent d'un seul tenant, et détacher la partie basse
n'a rien d'évident. Sans contrôle, une donnée de santé finirait dans le
stockage de la mairie, consultable par des agents administratifs, pour une
démarche d'état civil qui n'en a aucun besoin. Une fois la photo enregistrée,
il est trop tard : elle est copiée, sauvegardée, peut-être déjà lue.

CE QUE CE MODULE NE FAIT JAMAIS

Retenir ce qu'il a lu. Le texte reconnu n'est ni retourné, ni journalisé, ni
mis en cache : seul le marqueur reconnu — un libellé du formulaire, jamais
une donnée du défunt — sort de cette fonction.
"""
from __future__ import annotations

import os
import unicodedata

from services.journal import obtenir_logger

log = obtenir_logger("partie_confidentielle")

#: Mentions IMPRIMÉES sur la partie basse du formulaire. Jamais un mot qui
#: pourrait venir de la partie haute : refuser une photo valide renverrait le
#: citoyen photographier un document qu'il a bien envoyé.
MARQUEURS = (
    "certificat de causes de deces",
    "causes du deces",
    "renseignements confidentiels",
    "cause immediate",
    "cause initiale",
    "une autopsie a-t-elle ete pratiquee",
    "ne peut etre communique",
)

MESSAGE = (
    "Cette photo montre la partie confidentielle du certificat, celle qui indique la cause du décès. "
    "La mairie n'en a pas besoin et je ne peux pas l'enregistrer. Détachez le formulaire en suivant "
    "les pointillés et photographiez seulement la partie du haut, celle qui s'appelle « certificat de décès »."
)

MESSAGE_VERIFICATION_IMPOSSIBLE = (
    "Je n'arrive pas à vérifier cette photo pour l'instant. Comme ce document contient une partie "
    "confidentielle, je préfère ne pas l'enregistrer. Réessayez dans un moment."
)

#: Quand la lecture du texte est impossible (moteur absent, image illisible),
#: on REFUSE plutôt que d'enregistrer sans savoir. Une donnée de santé stockée
#: par erreur ne se rattrape pas ; une photo refusée se reprend.
REFUSER_SI_VERIFICATION_IMPOSSIBLE = os.getenv("REFUSER_CERTIFICAT_NON_VERIFIE", "1") == "1"

CONFIDENTIELLE = "partie_confidentielle"
VERIFICATION_IMPOSSIBLE = "verification_impossible"

_lecteur = None


def _normaliser(texte: str) -> str:
    """Sans accents, en minuscules, espaces tassés — l'OCR est approximatif."""
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFD", texte or "")
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(sans_accents.lower().split())


def _texte_par_ocr(octets: bytes) -> str:
    """Le texte visible sur la photo. Jamais conservé par l'appelant."""
    global _lecteur
    import cv2
    import numpy as np

    image = cv2.imdecode(np.frombuffer(octets, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError("image illisible")
    if _lecteur is None:
        import easyocr
        _lecteur = easyocr.Reader(["fr"], gpu=False)
    return " ".join(_lecteur.readtext(image, detail=0, paragraph=True))


def examiner(octets: bytes, *, lire_texte=None) -> tuple[str | None, str | None]:
    """
    Regarde si la photo montre la partie confidentielle.

    Retourne `(code, message)` — `(None, None)` quand la photo peut être
    enregistrée. `lire_texte` permet de fournir un autre lecteur (tests).
    """
    lire = lire_texte or _texte_par_ocr
    try:
        texte = _normaliser(lire(octets))
    except Exception as exc:  # noqa: BLE001
        # Volontairement sans le texte lu : le journal ne doit rien porter du
        # contenu de la photo.
        log.warning("Lecture du certificat impossible (%s).", type(exc).__name__)
        if REFUSER_SI_VERIFICATION_IMPOSSIBLE:
            return VERIFICATION_IMPOSSIBLE, MESSAGE_VERIFICATION_IMPOSSIBLE
        return None, None

    for marqueur in MARQUEURS:
        if marqueur in texte:
            # Le marqueur est une mention imprimée du formulaire, jamais une
            # donnée du défunt : il peut être journalisé.
            log.warning("Partie confidentielle refusée (mention reconnue : %r).", marqueur)
            return CONFIDENTIELLE, MESSAGE
    return None, None
