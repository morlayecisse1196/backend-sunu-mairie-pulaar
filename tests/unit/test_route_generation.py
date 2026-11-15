"""
Génération du document, vue du consultant (étape 5.5).

Le moteur ne savait fabriquer que l'extrait de naissance. Pour les deux autres
démarches, le bouton « Générer » lançait quand même la fabrication d'un
extrait de naissance à partir de leurs données. Le mariage a depuis reçu son
modèle (5.5) ; la déclaration de décès attend toujours le sien.

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
DOSSIER = {"id": "d1", "statut": "en_traitement", "type_demarche": "declaration_deces",
           "commune_id": "commune-1", "citoyen_id": "citoyen-1"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "_verifier_dossier_commune_consultant", lambda _id, _c: DOSSIER)
    monkeypatch.setattr(main, "_exiger_action_autorisee", lambda _d, _a: None)
    main.app.dependency_overrides[main.get_current_consultant] = lambda: CONSULTANT
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def test_une_demarche_sans_modele_donne_422_et_s_explique(client, monkeypatch):
    def sans_modele(_dossier_id, **_):
        raise DemarcheSansModele("Aucun modèle de document pour la démarche « declaration_deces ».")

    monkeypatch.setattr(main, "generer_document", sans_modele)
    reponse = client.post("/consultant/dossiers/d1/generer")
    assert reponse.status_code == 422
    assert "modèle" in reponse.json()["detail"]["message"]


def test_un_dossier_introuvable_reste_un_404(client, monkeypatch):
    def introuvable(_dossier_id, **_):
        raise ValueError("Dossier introuvable : d1")

    monkeypatch.setattr(main, "generer_document", introuvable)
    assert client.post("/consultant/dossiers/d1/generer").status_code == 404


def test_rien_n_est_stocke_quand_le_modele_manque(client, monkeypatch):
    monkeypatch.setattr(main, "generer_document",
                        lambda _id, **_: (_ for _ in ()).throw(DemarcheSansModele("pas de modèle")))
    monkeypatch.setattr(main, "upload_document_genere",
                        lambda *a, **k: pytest.fail("PDF stocké alors qu'aucun n'a été produit"))
    monkeypatch.setattr(main, "create_document_genere",
                        lambda *a, **k: pytest.fail("document enregistré sans PDF"))
    assert client.post("/consultant/dossiers/d1/generer").status_code == 422


def test_le_document_est_archive_sous_le_nom_de_son_gabarit(client, monkeypatch):
    """
    `main.py` passait « extrait_naissance_v1 » EN DUR à `create_document_genere`,
    alors que `generer_document` résout le modèle par démarche. Un acte de
    décès se retrouvait donc archivé sous le nom d'un extrait de naissance —
    invisible tant qu'une seule démarche avait un modèle, et impossible à
    rattraper après coup : `documents_generes` est le seul endroit qui dit
    avec quel gabarit un acte a été établi.
    """
    def faux_generer(_dossier_id, rapport=None):
        if rapport is not None:
            rapport["template"] = "acte_deces_v1"
            rapport["type_demarche"] = "declaration_deces"
            rapport["tampon_appose"] = True
            rapport["tampon_enregistre"] = True
        return b"%PDF-faux"

    archives = {}
    monkeypatch.setattr(main, "generer_document", faux_generer)
    monkeypatch.setattr(main, "get_next_version_documents_generes", lambda _id: 1)
    monkeypatch.setattr(main, "upload_document_genere", lambda *a, **k: "d1/v1.pdf")
    monkeypatch.setattr(main, "get_document_genere_signed_url", lambda _c: "https://exemple/signe")

    def faux_create(dossier_id, template_utilise, version, contenu_url):
        archives["template"] = template_utilise
        return {"id": "dg1", "statut": "genere"}

    monkeypatch.setattr(main, "create_document_genere", faux_create)

    async def sans_effet(*a, **k):
        return DOSSIER

    monkeypatch.setattr(main.evenements, "transition_statut", sans_effet)
    monkeypatch.setattr(main.audit, "journaliser", sans_effet)

    reponse = client.post("/consultant/dossiers/d1/generer")
    assert reponse.status_code == 200, reponse.text
    assert archives["template"] == "acte_deces_v1", (
        "le nom archivé doit venir du modèle employé, pas d'une constante"
    )
