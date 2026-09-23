from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth
from routers import moi


class FausseTable:
    def __init__(self, journal, echec_colonnes=False):
        self.journal = journal
        self.echec_colonnes = echec_colonnes
        self._operation = None

    def upsert(self, donnees, on_conflict=None):
        self._operation = ("upsert", donnees)
        return self

    def update(self, donnees):
        self._operation = ("update", donnees)
        return self

    def eq(self, *_):
        return self

    def execute(self):
        if self._operation[0] == "update" and self.echec_colonnes:
            raise Exception("Could not find the 'nom_complet' column of 'profiles' (PGRST204)")
        self.journal.append(self._operation)
        return SimpleNamespace(data=[{}])


@pytest.fixture
def client_http(monkeypatch):
    journal: list = []
    options = {"echec_colonnes": False, "role": "citoyen"}

    monkeypatch.setattr(moi.db, "client", lambda: SimpleNamespace(table=lambda _nom: FausseTable(journal, options["echec_colonnes"])))

    app = FastAPI()
    app.include_router(moi.router)
    app.dependency_overrides[auth.get_current_citoyen] = lambda: {"id": "user-1", "commune": "National", "role": options["role"]}
    return TestClient(app), journal, options


def test_route_enregistree_et_ecrit_le_profil(client_http):
    client, journal, _ = client_http
    reponse = client.post("/me/profil-citoyen", json={"commune": " Ross-Béthio ", "nom_complet": "Modou Diallo", "langue": "pulaar"})
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["commune"] == "Ross-Béthio"
    assert ("upsert", {"id": "user-1", "commune": "Ross-Béthio"}) in journal
    assert ("update", {"nom_complet": "Modou Diallo", "langue_preferee": "pulaar"}) in journal


def test_colonnes_absentes_signalees_sans_echec(client_http):
    client, _, options = client_http
    options["echec_colonnes"] = True
    reponse = client.post("/me/profil-citoyen", json={"commune": "Dakar", "nom_complet": "Awa"})
    assert reponse.status_code == 200
    assert reponse.json()["champs_ignores"] == ["nom_complet"]


def test_agent_refuse(client_http):
    client, _, options = client_http
    options["role"] = "consultant"
    assert client.post("/me/profil-citoyen", json={"commune": "Dakar"}).status_code == 403


def test_commune_obligatoire(client_http):
    client, _, _ = client_http
    assert client.post("/me/profil-citoyen", json={"commune": ""}).status_code == 422
