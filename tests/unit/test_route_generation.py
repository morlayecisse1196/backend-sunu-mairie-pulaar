"""
Génération du document, vue du consultant (étape 5.5).

Le moteur ne sait fabriquer que l'extrait de naissance. Pour les deux autres
démarches, le bouton « Générer » lançait quand même la fabrication d'un
extrait de naissance à partir de leurs données.

Ce qui est verrouillé ici : le refus est explicite, et distinct des autres.
Un 404 ferait croire que le dossier a disparu ; c'est le modèle qui manque,
pas le dossier — et la réponse doit le dire à l'agent qui a cliqué.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main
from document_generator import DemarcheSansModele

CONSULTANT = {"id": "c1", "email": "agent@mairie.sn", "commune": "Tambacounda"}
DOSSIER = {"id": "d1", "statut": "en_traitement", "type_demarche": "constatation_mariage",
           "commune_id": "commune-1", "citoyen_id": "citoyen-1"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "_verifier_dossier_commune_consultant", lambda _id, _c: DOSSIER)
    monkeypatch.setattr(main, "_exiger_action_autorisee", lambda _d, _a: None)
    main.app.dependency_overrides[main.get_current_consultant] = lambda: CONSULTANT
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def test_une_demarche_sans_modele_donne_422_et_s_explique(client, monkeypatch):
    def sans_modele(_dossier_id):
        raise DemarcheSansModele("Aucun modèle de document pour la démarche « constatation_mariage ».")

    monkeypatch.setattr(main, "generer_document", sans_modele)
    reponse = client.post("/consultant/dossiers/d1/generer")
    assert reponse.status_code == 422
    assert "modèle" in reponse.json()["detail"]["message"]


def test_un_dossier_introuvable_reste_un_404(client, monkeypatch):
    def introuvable(_dossier_id):
        raise ValueError("Dossier introuvable : d1")

    monkeypatch.setattr(main, "generer_document", introuvable)
    assert client.post("/consultant/dossiers/d1/generer").status_code == 404


def test_rien_n_est_stocke_quand_le_modele_manque(client, monkeypatch):
    monkeypatch.setattr(main, "generer_document",
                        lambda _id: (_ for _ in ()).throw(DemarcheSansModele("pas de modèle")))
    monkeypatch.setattr(main, "upload_document_genere",
                        lambda *a, **k: pytest.fail("PDF stocké alors qu'aucun n'a été produit"))
    monkeypatch.setattr(main, "create_document_genere",
                        lambda *a, **k: pytest.fail("document enregistré sans PDF"))
    assert client.post("/consultant/dossiers/d1/generer").status_code == 422
