"""
Relecture du document par le citoyen, pour un certificat de mariage (5.5).

L'endpoint lisait une liste de champs fixe, celle de l'extrait de naissance.
Un citoyen qui relisait son certificat de mariage recevait donc une liste
VIDE : aucun champ, aucun audio, rien à vérifier — et pourtant l'écran suivant
lui demande de valider un document qui engage les époux.

Les tests unitaires de `services.libelles_document` vérifient la liste ;
celui-ci vérifie que l'endpoint s'en sert vraiment, avec la démarche du
dossier.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main
from routers import citoyen as routeur
from auth import get_current_citoyen

CITOYEN = {"id": "citoyen-1"}

DOSSIER_MARIAGE = {
    "id": "d1", "citoyen_id": "citoyen-1", "commune_id": "c1",
    "type_demarche": "constatation_mariage",
    "statut": "en_attente_validation_citoyen",
    "slots": {
        "prenoms_epoux": "Amadou", "nom_epoux": "Diallo",
        "prenoms_epouse": "Maty", "nom_epouse": "Sene",
        "date_celebration": "2020-09-11", "lieu_celebration": "Dakar",
        "option_matrimoniale": "monogamie",
        "regime_matrimonial": "separation_des_biens",
    },
}

COMMUNE = {"nom": "Fann - Point E - Amitié", "region": "Dakar", "departement": "Dakar"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(routeur, "get_dossier", lambda _id: DOSSIER_MARIAGE)
    monkeypatch.setattr(routeur, "get_commune", lambda _id: COMMUNE)
    monkeypatch.setattr(routeur, "list_document_formulaires", lambda _id: [])
    monkeypatch.setattr(routeur, "get_or_create_formulaire_acte", lambda _id: None)
    main.app.dependency_overrides[get_current_citoyen] = lambda: CITOYEN
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def _champs(client):
    reponse = client.get("/mes-dossiers/d1/document/lecture")
    assert reponse.status_code == 200
    return reponse.json()["champs"]


def test_le_citoyen_entend_bien_quelque_chose(client):
    assert _champs(client), "aucun champ à relire sur un certificat de mariage"


def test_les_deux_epoux_sont_nommes(client):
    valeurs = [c["valeur"] for c in _champs(client)]
    assert "Amadou" in valeurs and "Maty" in valeurs


def test_aucun_champ_de_l_extrait_de_naissance_ne_s_y_glisse(client):
    cles = {c["cle"] for c in _champs(client)}
    assert not cles & {"prenomEnfant", "nomFamilleEnfant", "sexe"}


def test_l_option_souscrite_est_dite_en_francais(client):
    phrases = [c["phrase_fr"] for c in _champs(client)]
    assert "Option souscrite : Monogamie." in phrases
    assert not any("separation_des_biens" in p for p in phrases)


def test_chaque_champ_a_son_audio(client):
    # Le citoyen visé ne lit pas : une ligne sans audio est une ligne perdue.
    for champ in _champs(client):
        assert champ["audio_url"].endswith(f"/document/lecture/{champ['cle']}/audio")
