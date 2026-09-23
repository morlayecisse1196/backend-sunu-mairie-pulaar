from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth
from routers import notifications as routeur


class Requete:
    """Imite le constructeur de requêtes supabase-py pour une table en mémoire."""

    def __init__(self, base, table):
        self.base, self.table, self.filtres, self.operation, self.valeurs, self.compter = base, table, [], "select", None, False

    def select(self, *_colonnes, count=None):
        self.compter = count == "exact"
        return self

    def update(self, valeurs):
        self.operation, self.valeurs = "update", valeurs
        return self

    def upsert(self, valeurs, on_conflict=None):
        self.operation, self.valeurs = "upsert", valeurs
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def eq(self, colonne, valeur):
        self.filtres.append((colonne, valeur))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a):
        return self

    def execute(self):
        if self.base.get("erreur"):
            raise self.base["erreur"]
        lignes = [l for l in self.base.setdefault(self.table, []) if all(l.get(c) == v for c, v in self.filtres)]
        if self.operation == "update":
            for ligne in lignes:
                ligne.update(self.valeurs)
        elif self.operation == "upsert":
            self.base[self.table].append(dict(self.valeurs))
            lignes = [self.valeurs]
        return SimpleNamespace(data=lignes, count=len(lignes))


@pytest.fixture
def client(monkeypatch):
    base = {
        "notifications": [
            {"id": "n1", "destinataire_id": "u1", "lu": False, "titre": "Nouveau dossier"},
            {"id": "n2", "destinataire_id": "u1", "lu": True, "titre": "Ancien"},
            {"id": "n3", "destinataire_id": "autre", "lu": False, "titre": "Pas à moi"},
        ]
    }
    monkeypatch.setattr(routeur.db, "client", lambda: SimpleNamespace(table=lambda nom: Requete(base, nom)))
    app = FastAPI()
    app.include_router(routeur.router)
    app.dependency_overrides[auth.get_current_profile] = lambda: {"id": "u1", "role": "consultant", "commune": "Dakar"}
    return TestClient(app), base


def test_liste_uniquement_mes_notifications(client):
    http, _ = client
    corps = http.get("/notifications").json()
    assert {n["id"] for n in corps["notifications"]} == {"n1", "n2"}
    assert corps["non_lues"] == 1


def test_marquer_lu_et_notification_d_un_autre_introuvable(client):
    http, base = client
    assert http.post("/notifications/n1/lu").status_code == 204
    assert base["notifications"][0]["lu"] is True
    assert http.post("/notifications/n3/lu").status_code == 404


def test_tout_lu(client):
    http, base = client
    assert http.post("/notifications/tout-lu").status_code == 204
    assert base["notifications"][2]["lu"] is False  # celle d'un autre utilisateur n'est pas touchée


def test_migration_absente_503_explicite(client):
    http, base = client
    base["erreur"] = Exception("Could not find the table 'public.notifications' (PGRST205)")
    reponse = http.get("/notifications")
    assert reponse.status_code == 503 and reponse.json()["detail"]["migration"] == "014"


def test_enregistrer_appareil(client):
    http, base = client
    reponse = http.post("/me/appareils", json={"jeton_fcm": "x" * 40, "plateforme": "android", "langue": "pulaar"})
    assert reponse.status_code == 200 and reponse.json()["enregistre"] is True
    assert base["appareils"][0]["utilisateur_id"] == "u1"
