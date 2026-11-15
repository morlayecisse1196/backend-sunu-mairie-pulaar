"""
Allègement du tampon numérique avant stockage.

POURQUOI

Le tampon est posé sur le document en `data:` URI, et non en lien : le PDF
doit rester complet une fois enregistré ou imprimé (cf.
`document_generator.tampon_de_la_commune`). Son poids est donc **recopié en
base64 dans chaque acte délivré**, avec le tiers de surcoût de l'encodage.

Mesuré sur le seul tampon enregistré du projet, le 2026-11-05 :

    fichier source    716 536 octets (700 Ko), 864x853, RGBA, 63 550 couleurs
    en base64         955 381 octets dans CHAQUE PDF
    PDF resultant     639 474 octets — contre 19 170 octets sans tampon

Autrement dit, le sceau pesait 97 % de l'acte que le citoyen télécharge. Pour
quelqu'un qui relève sa demande en 3G, c'est la différence entre un fichier qui
arrive et un fichier qu'on abandonne.

CE QUI COÛTE, ET CE QUI NE COÛTE PAS

Ce n'est pas la taille en pixels : passer de 864 à 600 px ne gagnait qu'un
facteur 1,8. C'est la PALETTE. Un tampon est de l'encre sur du transparent,
deux ou trois teintes — mais le fichier en portait 63 550, héritées du scan.
Une palette de 256 couleurs suffit largement et divise le poids par 13.

À 600 px, 256 couleurs ne coûtent pas plus que 64 (55 682 contre 55 576
octets) : on prend donc les 256, pour garder le lissé des bords.

CE QUI N'EST JAMAIS FAIT

- Agrandir une image déjà petite : on ne fabrique pas du détail absent.
- Rendre un fichier plus lourd : si le résultat dépasse l'original, l'original
  est conservé.
- Faire échouer l'enregistrement. Un tampon qui n'a pas pu être allégé est
  stocké tel quel : mieux vaut un acte lourd qu'une commune sans sceau.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Optional

from services.journal import obtenir_logger

log = obtenir_logger("tampon_image")

#: Un tampon s'imprime sur deux à trois centimètres. 600 px laisse de la marge
#: même pour un rendu à 300 points par pouce, et reste lisible à l'écran.
COTE_MAX = 600

#: Palette du PNG de sortie. Voir l'en-tête : au-delà, le gain est nul.
COULEURS_MAX = 256

#: Qualité du JPEG de sortie. Un tampon en JPEG est un mauvais choix (pas de
#: transparence, artefacts sur les traits fins) mais le format est accepté :
#: on ne dégrade pas davantage.
QUALITE_JPEG = 85


@dataclass(frozen=True)
class ResultatAllegement:
    """Ce qui est à stocker, et ce qu'il faut pouvoir dire à l'administrateur."""

    octets: bytes
    octets_avant: int
    largeur: Optional[int] = None
    hauteur: Optional[int] = None
    largeur_avant: Optional[int] = None
    hauteur_avant: Optional[int] = None
    allege: bool = False
    raison: Optional[str] = None

    @property
    def octets_apres(self) -> int:
        return len(self.octets)

    @property
    def facteur(self) -> float:
        return self.octets_avant / self.octets_apres if self.octets_apres else 1.0

    def resume(self) -> dict:
        """Charge utile pour la réponse d'API et le journal d'audit."""
        return {
            "allege": self.allege,
            "octets_avant": self.octets_avant,
            "octets_apres": self.octets_apres,
            "facteur": round(self.facteur, 1),
            "dimensions_avant": (
                f"{self.largeur_avant}x{self.hauteur_avant}" if self.largeur_avant else None
            ),
            "dimensions_apres": f"{self.largeur}x{self.hauteur}" if self.largeur else None,
            "raison": self.raison,
        }


def alleger(contenu: bytes, extension: str) -> ResultatAllegement:
    """
    Réduit le tampon pour qu'il ne plombe pas chaque acte délivré.

    Ne lève jamais : toute difficulté renvoie le contenu d'origine, avec la
    raison, pour que l'enregistrement du tampon aboutisse quand même.
    """
    avant = len(contenu)
    try:
        from PIL import Image
    except Exception as exc:  # noqa: BLE001
        log.warning("Pillow indisponible (%s) — tampon stocké tel quel.", type(exc).__name__)
        return ResultatAllegement(contenu, avant, raison="Pillow indisponible")

    try:
        image = Image.open(io.BytesIO(contenu))
        image.load()
    except Exception as exc:  # noqa: BLE001
        log.warning("Tampon illisible par Pillow (%s) — stocké tel quel.", type(exc).__name__)
        return ResultatAllegement(contenu, avant, raison="image illisible")

    largeur_avant, hauteur_avant = image.size

    try:
        if extension == "png":
            # RGBA : FASTOCTREE est la seule méthode de quantification de
            # Pillow qui conserve le canal alpha. Sans transparence, le tampon
            # arriverait sur le document dans un rectangle blanc qui masquerait
            # le texte en dessous.
            travail = image.convert("RGBA")
            travail.thumbnail((COTE_MAX, COTE_MAX), Image.LANCZOS)
            sortie = travail.quantize(colors=COULEURS_MAX, method=Image.FASTOCTREE)
            tampon = io.BytesIO()
            sortie.save(tampon, format="PNG", optimize=True)
        else:
            travail = image.convert("RGB")
            travail.thumbnail((COTE_MAX, COTE_MAX), Image.LANCZOS)
            tampon = io.BytesIO()
            travail.save(tampon, format="JPEG", quality=QUALITE_JPEG, optimize=True)
        octets = tampon.getvalue()
    except Exception as exc:  # noqa: BLE001
        log.warning("Allègement du tampon échoué (%s) — stocké tel quel.", type(exc).__name__)
        return ResultatAllegement(contenu, avant, largeur_avant=largeur_avant,
                                  hauteur_avant=hauteur_avant, raison="traitement échoué")

    # Une image déjà sobre peut ressortir plus lourde du ré-encodage : on garde
    # alors la meilleure des deux.
    if len(octets) >= avant:
        return ResultatAllegement(
            contenu, avant, largeur=largeur_avant, hauteur=hauteur_avant,
            largeur_avant=largeur_avant, hauteur_avant=hauteur_avant,
            allege=False, raison="déjà optimal",
        )

    largeur, hauteur = travail.size
    log.info(
        "tampon.allege %dx%d->%dx%d %d->%d octets (x%.1f)",
        largeur_avant, hauteur_avant, largeur, hauteur, avant, len(octets),
        avant / len(octets),
    )
    return ResultatAllegement(
        octets, avant, largeur=largeur, hauteur=hauteur,
        largeur_avant=largeur_avant, hauteur_avant=hauteur_avant, allege=True,
    )
