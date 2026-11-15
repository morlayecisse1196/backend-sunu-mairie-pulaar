"""
Le sélecteur de commune de l'inscription (`GET /communes`).

CE QUI N'ALLAIT PAS

Cet endpoint listait les valeurs distinctes de `demarches.commune`. Sur la base
réelle, cela donnait exactement deux entrées : « Dakar » et « National ».

  * « National » n'est pas une commune : c'est la sentinelle des démarches
    valables partout. Un citoyen inscrit sur « National » voyait
    `resoudre_commune_id` échouer — son dossier n'était rattaché à aucune
    mairie et n'apparaissait dans la liste d'aucun consultant.
  * Ross-Béthio et Dindéfélo, les deux communes du pilote (seedées avec leurs
    coordonnées et leur tampon), étaient absentes : elles n'ont pas de démarche
    propre, toutes leurs démarches étant nationales. Leurs habitants ne
    pouvaient donc pas s'inscrire pour leur propre mairie.

La liste vient maintenant de la table `communes`, celle que l'administration
gère et que `resoudre_commune_id` interroge.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client():
    return TestClient(main.app)


def test_les_communes_viennent_de_la_table_communes(client, monkeypatch):
    monkeypatch.setattr(main, "list_noms_communes", lambda: ["Dindéfélo", "Ross-Béthio"])
    assert client.get("/communes").json() == {"communes": ["Dindéfélo", "Ross-Béthio"]}


def test_la_sentinelle_nationale_n_est_pas_proposee(client, monkeypatch):
    # `communes` ne contient pas « National » ; ce test verrouille le fait que
    # l'endpoint ne va plus la chercher dans `demarches`.
    monkeypatch.setattr(main, "list_noms_communes", lambda: ["Dakar", "Ross-Béthio"])
    assert "National" not in client.get("/communes").json()["communes"]


def test_une_liste_vide_reste_un_200(client, monkeypatch):
    # Les clients ont un repli statique : un 500 les priverait de ce repli.
    monkeypatch.setattr(main, "list_noms_communes", lambda: [])
    reponse = client.get("/communes")
    assert reponse.status_code == 200
    assert reponse.json() == {"communes": []}


def test_l_endpoint_reste_public(client, monkeypatch):
    # Sans auth : on choisit sa commune AVANT d'avoir un compte.
    monkeypatch.setattr(main, "list_noms_communes", lambda: ["Ross-Béthio"])
    assert client.get("/communes").status_code == 200


def test_le_choix_propose_est_resolvable(monkeypatch):
    """
    Le lien que ce correctif rétablit : tout nom proposé à l'inscription doit
    être un nom que `resoudre_commune_id` sait traduire en commune_id — sinon
    le dossier du citoyen n'a pas de mairie.
    """
    from dossiers_repo import list_noms_communes, resoudre_commune_id

    table = [{"id": "c-1", "nom": "Ross-Béthio"}, {"id": "c-2", "nom": "Dindéfélo"}]

    class FausseRequete:
        def __init__(self, lignes):
            self._lignes = lignes

        def select(self, *_a, **_k):
            return self

        def order(self, *_a, **_k):
            return self

        def limit(self, *_a, **_k):
            return self

        def ilike(self, _colonne, valeur):
            return FausseRequete([l for l in self._lignes if l["nom"].lower() == valeur.lower()])

        def execute(self):
            return type("R", (), {"data": self._lignes})()

    import dossiers_repo

    monkeypatch.setattr(
        dossiers_repo, "get_supabase_client",
        lambda: type("C", (), {"table": staticmethod(lambda _nom: FausseRequete(table))})(),
    )

    for nom in list_noms_communes():
        assert resoudre_commune_id(nom) is not None, f"« {nom} » est proposé mais ne résout pas"
