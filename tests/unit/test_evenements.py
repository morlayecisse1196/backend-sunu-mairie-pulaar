import asyncio
from types import SimpleNamespace

import pytest

from services import evenements


class FauxClient:
    def __init__(self, inserts, echec=None):
        self.inserts = inserts
        self.echec = echec

    def table(self, nom):
        client = self

        class Table:
            def insert(self, ligne):
                self.ligne = ligne
                return self

            def execute(self):
                if client.echec:
                    raise client.echec
                client.inserts.append((nom, self.ligne))
                return SimpleNamespace(data=[self.ligne])

        return Table()


@pytest.fixture
def environnement(monkeypatch):
    etat = {"inserts": [], "maj": [], "echec_update": set(), "recus": []}
    evenements.reinitialiser_abonnes()
    monkeypatch.setattr(evenements, "get_dossier", lambda dossier_id: {"id": dossier_id, "statut": "en_traitement", "citoyen_id": "c1"})

    def update(dossier_id, **champs):
        etat["maj"].append(champs)
        return not (etat["echec_update"] & champs.keys()) and "tout" not in etat["echec_update"]

    monkeypatch.setattr(evenements, "update_dossier", update)
    monkeypatch.setattr(evenements.db, "client", lambda: FauxClient(etat["inserts"]))

    async def abonne(transition):
        etat["recus"].append(transition)

    evenements.abonner(abonne)
    yield etat
    evenements.reinitialiser_abonnes()


async def _attendre_diffusion():
    await asyncio.gather(*list(evenements._taches_en_vol))


async def test_transition_ecrit_historique_et_diffuse(environnement):
    apres = await evenements.transition_statut("d1", "genere", acteur_type="consultant", acteur_id="u1")
    await _attendre_diffusion()
    assert apres["statut"] == "genere"
    table, ligne = environnement["inserts"][0]
    assert table == "dossier_evenements"
    assert ligne["statut_avant"] == "en_traitement" and ligne["statut_apres"] == "genere"
    assert ligne["libelle"] == evenements.LIBELLES_TRANSITION["genere"]
    assert environnement["recus"][0].statut_apres == "genere"
    assert environnement["recus"][0].dossier["citoyen_id"] == "c1"


async def test_colonne_de_migration_absente_ne_bloque_pas_la_transition(environnement):
    environnement["echec_update"] = {"motif_blocage"}
    apres = await evenements.transition_statut(
        "d1", "bloque", acteur_type="systeme", champs={"motif_blocage": "relecture_rg7", "nb_iterations_correction": 3}
    )
    assert apres is not None and apres["statut"] == "bloque"
    assert "motif_blocage" not in apres
    assert environnement["maj"][-1] == {"statut": "bloque", "nb_iterations_correction": 3}


async def test_echec_d_ecriture_aucune_diffusion(environnement):
    environnement["echec_update"] = {"tout"}
    assert await evenements.transition_statut("d1", "finalise", acteur_type="citoyen") is None
    await _attendre_diffusion()
    assert environnement["recus"] == [] and environnement["inserts"] == []


async def test_table_historique_absente_ne_fait_pas_echouer(monkeypatch, environnement):
    monkeypatch.setattr(evenements.db, "client", lambda: FauxClient([], echec=Exception("Could not find the table (PGRST205)")))
    apres = await evenements.transition_statut("d1", "recu", acteur_type="citoyen")
    await _attendre_diffusion()
    assert apres["statut"] == "recu" and len(environnement["recus"]) == 1
