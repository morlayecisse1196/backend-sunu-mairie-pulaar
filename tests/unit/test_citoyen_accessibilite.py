import pytest

from routers.citoyen import distance_km
from services import catalogue_audio, libelles_document


def test_distance_haversine():
    # Dakar -> Saint-Louis : environ 200 km à vol d'oiseau.
    assert distance_km(14.6928, -17.4467, 16.0179, -16.4896) == pytest.approx(200, abs=25)
    assert distance_km(14.6928, -17.4467, 14.6928, -17.4467) == 0


def test_phrases_de_lecture_du_document():
    assert libelles_document.phrase_lecture("prenomEnfant", "Ibrahima") == "Prénom de l'enfant : Ibrahima."
    assert libelles_document.phrase_lecture("heureNaissance", None) == "Heure de naissance : non renseigné."
    assert libelles_document.libelle("champInconnu") == "champInconnu"


def test_ordre_de_lecture_couvert_par_les_libelles():
    manquants = [cle for cle in libelles_document.ORDRE_LECTURE if cle not in libelles_document.LIBELLES]
    assert manquants == []


def test_cle_de_cache_stable_et_insensible_a_la_casse():
    a = catalogue_audio.cle_pour_texte("Prénom de l'enfant : Ibrahima.")
    b = catalogue_audio.cle_pour_texte("  prénom de l'enfant : ibrahima.  ")
    assert a == b and a.startswith("txt_")
    assert catalogue_audio.cle_pour_texte("Autre phrase") != a


async def test_audio_interface_inconnue(monkeypatch):
    assert await catalogue_audio.audio_interface("cle-qui-nexiste-pas") is None


async def test_audio_genere_une_seule_fois_puis_mis_en_cache(monkeypatch, tmp_path):
    appels = {"traduction": 0, "synthese": 0}

    async def fausse_traduction(texte):
        appels["traduction"] += 1
        return "pulaar : " + texte

    async def fausse_synthese(texte, timeout=None):
        appels["synthese"] += 1
        return b"RIFF-audio"

    monkeypatch.setattr(catalogue_audio, "DOSSIER_CACHE", str(tmp_path))
    monkeypatch.setattr(catalogue_audio, "_traduire_en_pulaar", fausse_traduction)
    monkeypatch.setattr(catalogue_audio, "synthesize_remote", fausse_synthese)

    assert await catalogue_audio.audio_interface("accueil") == b"RIFF-audio"
    assert await catalogue_audio.audio_interface("accueil") == b"RIFF-audio"
    assert appels == {"traduction": 1, "synthese": 1}
    assert catalogue_audio.existe("accueil")
