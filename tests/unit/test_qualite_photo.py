import cv2
import numpy as np
import pytest

from services import qualite_photo


def _jpeg(image: np.ndarray) -> bytes:
    ok, tampon = cv2.imencode(".jpg", image)
    assert ok
    return tampon.tobytes()


def _document_net(largeur=1200, hauteur=800) -> np.ndarray:
    """Fond clair avec du « texte » (traits fins contrastés), comme une pièce d'identité."""
    image = np.full((hauteur, largeur), 210, dtype=np.uint8)
    for y in range(60, hauteur - 60, 40):
        for x in range(60, largeur - 200, 25):
            cv2.putText(image, "A", (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 20, 1, cv2.LINE_AA)
    return image


def test_document_net_accepte():
    verdict = qualite_photo.evaluer(_jpeg(_document_net()))
    assert verdict.acceptable, verdict.mesures


def test_document_flou_refuse():
    flou = cv2.GaussianBlur(_document_net(), (0, 0), sigmaX=9)
    verdict = qualite_photo.evaluer(_jpeg(flou))
    assert not verdict.acceptable and verdict.code == "photo_floue"
    assert "floue" in verdict.message_fr


def test_document_sombre_refuse():
    sombre = (_document_net() * 0.12).astype(np.uint8)
    verdict = qualite_photo.evaluer(_jpeg(sombre))
    assert verdict.code == "photo_sombre"


def test_document_surexpose_refuse():
    verdict = qualite_photo.evaluer(_jpeg(np.full((800, 1200), 252, dtype=np.uint8)))
    assert verdict.code == "photo_surexposee"


def test_photo_trop_petite_refusee():
    verdict = qualite_photo.evaluer(_jpeg(_document_net(300, 200)))
    assert verdict.code == "photo_trop_petite"


@pytest.mark.parametrize("octets", [b"", b"ceci n'est pas une image"])
def test_fichier_illisible(octets):
    assert qualite_photo.evaluer(octets).code == "photo_illisible"


def test_tres_grande_photo_analysee_rapidement_et_acceptee():
    grande = cv2.resize(_document_net(), (4000, 3000), interpolation=cv2.INTER_LINEAR)
    verdict = qualite_photo.evaluer(_jpeg(grande))
    assert verdict.acceptable, verdict.mesures
