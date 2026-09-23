from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth
from routers import admin as routeur_admin


@pytest.fixture
def client(monkeypatch):
    etat = {
        "dossier": {"id": "d-1", "statut": "bloque", "numero_suivi": "SM-2026-000452", "nb_iterations_correction": 3},
        "transitions": [],
        "audits": [],
        "reinit": {"id": "u-1", "email": "agent@mairie.sn", "mot_de_passe_temporaire": "secret-temporaire"},
    }

    async def charger(dossier_id):
        if dossier_id != "d-1":
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Dossier introuvable")
        return dict(etat["dossier"])

    async def transition(dossier_id, statut, **kwargs):
        etat["transitions"].append((dossier_id, statut, kwargs))
        return {"id": dossier_id, "statut": statut, "nb_iterations_correction": kwargs["champs"].get("nb_iterations_correction")}

    async def journaliser(action, **kwargs):
        etat["audits"].append((action, kwargs))

    async def executer(fonction, *args, **kwargs):
        return fonction(*args, **kwargs)

    monkeypatch.setattr(routeur_admin.acces, "charger_dossier", charger)
    monkeypatch.setattr(routeur_admin.evenements, "transition_statut", transition)
    monkeypatch.setattr(routeur_admin.audit, "journaliser", journaliser)
    monkeypatch.setattr(routeur_admin.db, "executer", executer)
    monkeypatch.setattr(routeur_admin, "reinitialiser_mot_de_passe_consultant", lambda user_id: etat["reinit"] if user_id == "u-1" else None)
    monkeypatch.setattr(routeur_admin, "list_dossiers_admin", lambda inclure: [{"id": "d-1", "commune_nom": "Ross-Béthio"}])

    app = FastAPI()
    app.include_router(routeur_admin.router)
    app.dependency_overrides[auth.get_current_admin] = lambda: {"id": "admin-1", "role": "admin", "commune": "National"}
    return TestClient(app), etat


def test_deblocage_avec_motif(client):
    http, etat = client
    reponse = http.post("/admin/dossiers/d-1/debloquer", json={"motif": "Citoyen joint par téléphone, nom confirmé.", "statut_cible": "en_traitement"})
    assert reponse.status_code == 200 and reponse.json()["statut"] == "en_traitement"
    dossier_id, statut, kwargs = etat["transitions"][0]
    assert kwargs["acteur_type"] == "admin" and kwargs["champs"]["motif_blocage"] is None
    assert kwargs["champs"]["nb_iterations_correction"] == 0
    assert "Citoyen joint" in kwargs["libelle"]
    assert etat["audits"][0][0] == "dossier_debloque"


def test_motif_trop_court_refuse(client):
    http, etat = client
    assert http.post("/admin/dossiers/d-1/debloquer", json={"motif": "ok"}).status_code == 422
    assert etat["transitions"] == []


def test_dossier_non_bloque_refuse(client):
    http, etat = client
    etat["dossier"]["statut"] = "en_traitement"
    reponse = http.post("/admin/dossiers/d-1/debloquer", json={"motif": "Motif suffisamment long"})
    assert reponse.status_code == 409 and reponse.json()["detail"]["code"] == "dossier_non_bloque"


def test_dossier_inexistant(client):
    http, _ = client
    assert http.post("/admin/dossiers/inconnu/debloquer", json={"motif": "Motif suffisamment long"}).status_code == 404


def test_reinitialisation_mot_de_passe(client):
    http, etat = client
    reponse = http.post("/admin/consultants/u-1/reinitialiser-mot-de-passe")
    assert reponse.status_code == 200 and reponse.json()["mot_de_passe_temporaire"] == "secret-temporaire"
    assert etat["audits"][-1][0] == "consultant_mdp_reinitialise"
    assert http.post("/admin/consultants/inconnu/reinitialiser-mot-de-passe").status_code == 404


def test_liste_des_dossiers(client):
    http, _ = client
    assert http.get("/admin/dossiers").json()["dossiers"][0]["commune_nom"] == "Ross-Béthio"
