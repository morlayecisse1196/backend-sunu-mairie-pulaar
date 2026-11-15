"""
Écran « Informations » vu du web (étape 5.6).

Ce que l'agent dit aux citoyens doit pouvoir être corrigé par la mairie :
un tarif change, un bureau déménage. Sans cet écran, ces fiches ne se
modifiaient qu'en base, et vieillissaient en silence.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth
from routers import admin as routeur
from services import informations

ADMIN = {"id": "a1", "email": "admin@mairie.sn", "role": "admin"}
FICHE = {"id": "f1", "commune": "National", "categorie": "État Civil",
         "nom_demarche": "Constatation de mariage", "cout": None}


@pytest.fixture
def client(monkeypatch):
    appels: dict = {"modifs": []}

    def modifier(fiche_id, valeurs, *, par=None):
        if "nom_demarche" in valeurs:
            raise informations.ModificationRefusee("Champ(s) non modifiable(s) ici : nom_demarche.")
        appels["modifs"].append((fiche_id, valeurs, par))
        return {**FICHE, **valeurs}

    monkeypatch.setattr(routeur.informations, "lister", lambda: [FICHE])
    monkeypatch.setattr(routeur.informations, "modifier", modifier)

    app = FastAPI()
    app.include_router(routeur.router)
    app.dependency_overrides[auth.get_current_admin] = lambda: ADMIN
    return TestClient(app), appels


def test_les_fiches_sont_listees_avec_ce_qui_est_modifiable(client):
    http, _ = client
    corps = http.get("/admin/informations").json()
    assert corps["fiches"][0]["nom_demarche"] == "Constatation de mariage"
    assert "cout" in corps["modifiables"] and "conditions" in corps["listes"]


def test_une_correction_est_enregistree_avec_son_auteur(client):
    http, appels = client
    reponse = http.put("/admin/informations/f1", json={"valeurs": {"cout": "2 000 FCFA"}})
    assert reponse.status_code == 200
    assert appels["modifs"] == [("f1", {"cout": "2 000 FCFA"}, "admin@mairie.sn")]


def test_un_champ_non_modifiable_donne_422(client):
    # 422 et non 500 : la demande est refusée pour une raison qu'on explique.
    http, appels = client
    reponse = http.put("/admin/informations/f1", json={"valeurs": {"nom_demarche": "Autre"}})
    assert reponse.status_code == 422
    assert "nom_demarche" in reponse.json()["detail"]
    assert appels["modifs"] == []
