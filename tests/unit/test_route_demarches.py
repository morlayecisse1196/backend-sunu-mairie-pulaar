"""
Éditeur de démarche vu du web (plan maître, étape 4.1).

Ce qui est verrouillé ici :

  * une modification qui casserait le dialogue donne 409 et n'écrit rien —
    409 et non 400 : la demande est bien formée, c'est l'état de la démarche
    qui la rend impossible ;
  * la réponse dit OÙ est le problème, pas seulement qu'il y en a un ;
  * publier une démarche cassée est refusé : la version figée deviendrait une
    impasse pour tous les dialogues qui démarreraient dessus ;
  * une suppression laisse une trace dans le journal.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth
from routers import demarches as routeur
from services import brouillon, demarche, editeur, simulateur

ADMIN = {"id": "a1", "email": "moussa@mairie.sn", "role": "admin"}

CASSE = editeur.Probleme(editeur.BLOQUANT, "champ:nom_enfant",
                         "La condition parle de nom_enfant, qui n'existe pas.")
PRUDENCE = editeur.Probleme(editeur.AVERTISSEMENT, "champ:age_enfant", "Aucune relance.")


@pytest.fixture
def client(monkeypatch):
    appels: dict = {"enregistre": [], "supprime": [], "publie": [], "reordonne": [], "abandonne": []}

    def enregistrer(famille, cle, valeurs, *, type_demarche=None):
        if valeurs.get("casser"):
            raise editeur.EditionRefusee([CASSE])
        appels["enregistre"].append((famille, cle, valeurs))
        return [PRUDENCE]

    def supprimer(famille, cle, *, type_demarche=None):
        if cle == "indispensable":
            raise editeur.EditionRefusee([CASSE])
        appels["supprime"].append((famille, cle))
        return []

    monkeypatch.setattr(routeur.editeur, "enregistrer", enregistrer)
    monkeypatch.setattr(routeur.editeur, "supprimer", supprimer)
    monkeypatch.setattr(routeur.editeur, "verifier", lambda _t: [])
    monkeypatch.setattr(routeur.editeur, "reordonner",
                        lambda famille, cles, *, type_demarche=None:
                        appels["reordonne"].append((famille, cles)))
    monkeypatch.setattr(routeur.demarche, "publier",
                        lambda t, par=None: appels["publie"].append((t, par)) or 7)
    # Par défaut, le brouillon contient une modification : il y a de quoi publier.
    monkeypatch.setattr(routeur.brouillon, "etat", lambda _t: brouillon.Etat(
        version_publiee=6, ecarts=[brouillon.Ecart("champ", "age_enfant", brouillon.MODIFIE, ("question",))]))
    monkeypatch.setattr(routeur.brouillon, "abandonner",
                        lambda t, par=None: appels["abandonne"].append((t, par)) or 3)

    app = FastAPI()
    app.include_router(routeur.router)
    app.dependency_overrides[auth.get_current_admin] = lambda: ADMIN
    return TestClient(app), appels


class TestEcriture:
    def test_une_modification_saine_passe_et_remonte_les_avertissements(self, client):
        http, appels = client
        reponse = http.put("/admin/demarches/d/champ/age_enfant",
                           json={"valeurs": {"question": "Quel âge ?"}})
        assert reponse.status_code == 200
        assert appels["enregistre"][0][1] == "age_enfant"
        assert reponse.json()["avertissements"][0]["gravite"] == editeur.AVERTISSEMENT

    def test_une_modification_qui_casse_le_dialogue_donne_409(self, client):
        # 400 accuserait la saisie ; c'est l'état de la démarche qui bloque.
        http, appels = client
        reponse = http.put("/admin/demarches/d/champ/nom_enfant",
                           json={"valeurs": {"casser": True}})
        assert reponse.status_code == 409
        assert appels["enregistre"] == []

    def test_le_refus_dit_ou_est_le_probleme(self, client):
        # Sans cela, l'administrateur sait qu'il a cassé quelque chose mais pas
        # quoi — et cherche dans une démarche de cinquante lignes.
        http, _ = client
        detail = http.put("/admin/demarches/d/champ/nom_enfant",
                          json={"valeurs": {"casser": True}}).json()["detail"]
        assert detail["problemes"][0]["ou"] == "champ:nom_enfant"
        assert "nom_enfant" in detail["problemes"][0]["message"]

    def test_une_famille_inconnue_est_refusee(self, client):
        http, _ = client
        assert http.put("/admin/demarches/d/couleurs/bleu",
                        json={"valeurs": {}}).status_code == 404


class TestSuppression:
    def test_supprimer_ce_dont_rien_ne_depend_passe(self, client):
        http, appels = client
        assert http.delete("/admin/demarches/d/document/livret").status_code == 200
        assert appels["supprime"] == [("document", "livret")]

    def test_supprimer_un_element_dont_tout_depend_donne_409(self, client):
        http, appels = client
        assert http.delete("/admin/demarches/d/champ/indispensable").status_code == 409
        assert appels["supprime"] == []


class TestOrdre:
    def test_reordonner_transmet_la_liste_complete(self, client):
        http, appels = client
        reponse = http.post("/admin/demarches/d/champ/ordre",
                            json={"cles": ["b", "a", "c"]})
        assert reponse.status_code == 200
        assert appels["reordonne"] == [("champ", ["b", "a", "c"])]

    def test_une_liste_partielle_refusee_par_le_service_donne_422(self, client, monkeypatch):
        def refuser(famille, cles, *, type_demarche=None):
            raise ValueError("Élément(s) absent(s) de l'ordre donné : c")

        monkeypatch.setattr(routeur.editeur, "reordonner", refuser)
        http, _ = client
        assert http.post("/admin/demarches/d/champ/ordre",
                         json={"cles": ["a"]}).status_code == 422

    def test_un_ordre_vide_est_refuse_par_le_schema(self, client):
        http, _ = client
        assert http.post("/admin/demarches/d/champ/ordre", json={"cles": []}).status_code == 422


class TestPublication:
    def test_publier_une_demarche_saine_cree_une_version(self, client):
        http, appels = client
        reponse = http.post("/admin/demarches/d/publier")
        assert reponse.json()["version"] == 7
        assert appels["publie"] == [("d", "moussa@mairie.sn")]

    def test_publier_une_demarche_cassee_est_refuse(self, client, monkeypatch):
        # La version figée deviendrait une impasse : les dialogues qui
        # démarreraient dessus n'auraient aucun moyen d'en sortir.
        monkeypatch.setattr(routeur.editeur, "verifier", lambda _t: [CASSE])
        http, appels = client
        reponse = http.post("/admin/demarches/d/publier")
        assert reponse.status_code == 409
        assert appels["publie"] == []

    def test_un_simple_avertissement_n_empeche_pas_de_publier(self, client, monkeypatch):
        monkeypatch.setattr(routeur.editeur, "verifier", lambda _t: [PRUDENCE])
        http, appels = client
        assert http.post("/admin/demarches/d/publier").status_code == 200
        assert appels["publie"]


class TestBrouillon:
    """
    Ce qui attend d'être publié (étape 4.4). Aucun citoyen ne l'entend encore :
    l'écran doit le dire, sinon l'agent qui ne l'entend pas au téléphone
    conclut que l'outil ne marche pas.
    """

    def test_publier_un_brouillon_identique_est_refuse(self, client, monkeypatch):
        # Une v7 identique à la v6 brouille l'historique.
        monkeypatch.setattr(routeur.brouillon, "etat", lambda _t: brouillon.Etat(version_publiee=6))
        http, appels = client
        reponse = http.post("/admin/demarches/d/publier")
        assert reponse.status_code == 409
        assert "Rien à publier" in reponse.json()["detail"]["message"]
        assert appels["publie"] == []

    def test_des_gabarits_jamais_figes_suffisent_a_publier(self, client, monkeypatch):
        monkeypatch.setattr(routeur.brouillon, "etat", lambda _t: brouillon.Etat(
            version_publiee=6, gabarits_non_figes=True))
        http, appels = client
        assert http.post("/admin/demarches/d/publier").status_code == 200

    def test_une_base_injoignable_donne_503_et_ne_publie_pas(self, client, monkeypatch):
        def en_panne(_t):
            raise demarche.LectureImpossible("demarche_champs : réseau")
        monkeypatch.setattr(routeur.brouillon, "etat", en_panne)
        http, appels = client
        assert http.post("/admin/demarches/d/publier").status_code == 503
        assert appels["publie"] == []

    def test_une_publication_qui_lit_mal_donne_503(self, client, monkeypatch):
        def en_panne(_t, par=None):
            raise demarche.LectureImpossible("demarche_champs : réseau")
        monkeypatch.setattr(routeur.demarche, "publier", en_panne)
        http, _ = client
        assert http.post("/admin/demarches/d/publier").status_code == 503

    def test_l_etat_du_brouillon_liste_les_ecarts(self, client):
        http, _ = client
        corps = http.get("/admin/demarches/d/brouillon").json()
        assert corps["version_publiee"] == 6
        assert corps["ecarts"] == [{"famille": "champ", "cle": "age_enfant",
                                    "nature": "modifie", "colonnes": ["question"]}]
        assert corps["a_publier"] is True

    def test_abandonner_trace_qui(self, client):
        http, appels = client
        reponse = http.post("/admin/demarches/d/abandonner")
        assert reponse.json() == {"remis": 3}
        assert appels["abandonne"] == [("d", "moussa@mairie.sn")]

    def test_un_abandon_impossible_donne_409(self, client, monkeypatch):
        def refuse(_t, par=None):
            raise brouillon.AbandonImpossible("Aucune version publiée à restaurer.")
        monkeypatch.setattr(routeur.brouillon, "abandonner", refuse)
        http, _ = client
        reponse = http.post("/admin/demarches/d/abandonner")
        assert reponse.status_code == 409
        assert "Aucune version" in reponse.json()["detail"]

    def test_un_abandon_sur_base_injoignable_donne_503(self, client, monkeypatch):
        def en_panne(_t, par=None):
            raise demarche.LectureImpossible("réseau")
        monkeypatch.setattr(routeur.brouillon, "abandonner", en_panne)
        http, _ = client
        assert http.post("/admin/demarches/d/abandonner").status_code == 503


class TestSimulateur:
    """
    Jouer une démarche sans téléphone (étape 4.3).

    Ce que l'écran doit rendre visible : jusqu'où va le dialogue, et quelles
    phrases appellent encore le traducteur.
    """

    @pytest.fixture
    def simulation(self, client, monkeypatch):
        http, appels = client
        appels["simule"] = []

        def jouer(reponses, type_demarche=None, version=None):
            appels["simule"].append((reponses, type_demarche, version))
            rapport = simulateur.Rapport(termine=True, cas="tardif")
            rapport.tours = [
                simulateur.Tour(genre="question", cle="nom", dit="Le nom ?",
                                pulaar="Innde?", audio_pret=True, origine="champ:nom"),
                simulateur.Tour(genre="question", cle="age", dit="L'âge ?",
                                pulaar=None, audio_pret=False, origine="champ:age"),
            ]
            return rapport

        monkeypatch.setattr(routeur.simulateur, "jouer", jouer)
        monkeypatch.setattr(routeur.simulateur, "scenario_type",
                            lambda _t: {"nom": "Ibrahima", "age": {"valeur": 7, "unite": "jours"}})
        return http, appels

    def test_le_scenario_de_depart_est_pret_a_jouer(self, simulation):
        http, _ = simulation
        corps = http.get("/admin/demarches/d/scenario").json()
        assert corps["reponses"]["nom"] == "Ibrahima"

    def test_le_rapport_dit_ce_qui_passe_encore_par_le_traducteur(self, simulation):
        http, _ = simulation
        corps = http.post("/admin/demarches/d/simuler",
                          json={"reponses": {"nom": "Ibrahima"}}).json()
        assert corps["termine"] is True
        assert corps["cas"] == "tardif"
        assert corps["a_traduire"] == ["champ:age"]
        assert corps["sans_traducteur"] is False

    def test_le_scenario_est_transmis_tel_quel(self, simulation):
        http, appels = simulation
        http.post("/admin/demarches/d/simuler", json={"reponses": {"nom": "Awa"}})
        assert appels["simule"][0][0] == {"nom": "Awa"}

    def test_une_version_figee_peut_etre_rejouee(self, simulation):
        # Reproduire ce qu'a vécu un citoyen demande SA version, pas la
        # définition d'aujourd'hui.
        http, appels = simulation
        http.post("/admin/demarches/d/simuler?version=3", json={"reponses": {}})
        assert appels["simule"][0][2] == 3
