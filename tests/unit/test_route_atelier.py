"""
Atelier pulaar vu du web (plan maître, étape 4.2).

Ce qui est verrouillé ici :

  * l'écoute AVANT la validation : ces phrases sont dites, pas lues, et une
    traduction juste à l'écrit peut être imprononçable ;
  * écouter range l'audio — la phrase écoutée puis validée est déjà
    pré-générée, sans appel supplémentaire (étape 3.4) ;
  * le service vocal en panne donne 503, pas 500 : l'interface propose de
    réessayer au lieu d'annoncer un bug ;
  * la relecture est attribuée à quelqu'un — « validé » sans nom ne vaut pas
    grand-chose trois mois plus tard ;
  * un identifiant inconnu est refusé au lieu d'écrire à côté.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth
from routers import atelier as routeur
from services import atelier as service
from services import catalogue_audio, phrases

ADMIN = {"id": "a1", "email": "moussa@mairie.sn", "role": "admin"}

PHRASE = service.Phrase(
    identifiant="champ:nom_mere:question",
    francais="Quel est le nom de la maman ?",
    pulaar="Innde neene ko honɗum?",
    valide=False,
    contexte="Question du champ « nom_mere »",
    cible=service.Cible("demarche_champs", "nom_champ", "nom_mere", "question_pulaar"),
)


@pytest.fixture
def client(monkeypatch):
    appels: dict = {"enregistre": [], "synthetise": []}

    monkeypatch.setattr(routeur.atelier, "collecter", lambda _d=None: [PHRASE])
    monkeypatch.setattr(routeur.atelier, "avancement", lambda _d=None: {
        "total": 1, "relues": 0, "deposees": 1, "vides": 0, "audios_prets": 0})
    monkeypatch.setattr(routeur.atelier, "historique", lambda _i=None, _d=None: [])

    def enregistrer(traductions, *, valider=False, par=None, type_demarche=None):
        if "inconnu" in next(iter(traductions)):
            raise ValueError("Identifiant(s) inconnu(s) : " + next(iter(traductions)))
        appels["enregistre"].append((traductions, valider, par))
        return {"phrases": len(traductions), "lignes": 1, "validees": 1 if valider else 0}

    monkeypatch.setattr(routeur.atelier, "enregistrer", enregistrer)

    async def synthese(texte, timeout=None):
        appels["synthetise"].append(texte)
        return b"WAV " + texte.encode()

    monkeypatch.setattr(routeur, "synthesize_remote", synthese)

    app = FastAPI()
    app.include_router(routeur.router)
    app.dependency_overrides[auth.get_current_admin] = lambda: ADMIN
    return TestClient(app), appels


class TestListe:
    def test_la_liste_porte_le_contexte_et_l_avancement(self, client):
        http, _ = client
        corps = http.get("/admin/atelier/phrases").json()
        assert corps["avancement"]["total"] == 1
        phrase = corps["phrases"][0]
        assert phrase["identifiant"] == "champ:nom_mere:question"
        assert phrase["contexte"], "traduire sans contexte est un pari"
        assert phrase["audio_pret"] is False


class TestEnregistrement:
    def test_deposer_sans_valider_est_le_cas_par_defaut(self, client):
        # On dépose, on écoute, PUIS on valide. Valider d'emblée ferait dire
        # au citoyen une phrase que personne n'a entendue.
        http, appels = client
        reponse = http.put("/admin/atelier/phrases/champ:nom_mere:question",
                           json={"pulaar": "Innde neene?"})
        assert reponse.status_code == 200
        _traductions, valider, _par = appels["enregistre"][0]
        assert valider is False

    def test_la_relecture_est_attribuee_a_son_auteur(self, client):
        http, appels = client
        http.put("/admin/atelier/phrases/champ:nom_mere:question",
                 json={"pulaar": "Innde neene?", "valider": True})
        _traductions, valider, par = appels["enregistre"][0]
        assert valider is True
        assert par == "moussa@mairie.sn"

    def test_un_identifiant_inconnu_est_refuse(self, client):
        http, appels = client
        reponse = http.put("/admin/atelier/phrases/champ:inconnu:question",
                           json={"pulaar": "Texte."})
        assert reponse.status_code == 404
        assert appels["enregistre"] == []

    def test_une_traduction_vide_est_refusee_par_le_schema(self, client):
        http, _ = client
        assert http.put("/admin/atelier/phrases/champ:nom_mere:question",
                        json={"pulaar": ""}).status_code == 422


class TestEcoute:
    def test_ecouter_synthetise_et_range_l_audio(self, client):
        # Écouter une phrase qu'on valide ensuite, c'est aussi la pré-générer.
        http, appels = client
        reponse = http.post("/admin/atelier/ecouter", json={"pulaar": "Innde neene?"})

        assert reponse.status_code == 200
        assert reponse.headers["content-type"] == "audio/wav"
        assert reponse.headers["X-Audio-Source"] == "synthetise"
        assert appels["synthetise"] == ["Innde neene?"]
        assert catalogue_audio.phrase_deja_generee("Innde neene?") is True

    def test_une_phrase_deja_generee_n_est_pas_resynthetisee(self, client):
        http, appels = client
        http.post("/admin/atelier/ecouter", json={"pulaar": "Innde neene?"})
        appels["synthetise"].clear()

        reponse = http.post("/admin/atelier/ecouter", json={"pulaar": "Innde neene?"})

        assert reponse.headers["X-Audio-Source"] == "pre-genere"
        assert appels["synthetise"] == [], "le Space vocal n'est pas rappelé pour rien"

    def test_un_service_vocal_en_panne_donne_503(self, client, monkeypatch):
        # 503 et non 500 : l'interface doit proposer de réessayer, la panne
        # est temporaire (le Space redémarre à froid).
        from tts_client import TTSError

        async def en_panne(_texte, timeout=None):
            raise TTSError("Space injoignable")

        monkeypatch.setattr(routeur, "synthesize_remote", en_panne)
        http, _ = client
        reponse = http.post("/admin/atelier/ecouter", json={"pulaar": "Texte."})
        assert reponse.status_code == 503

    def test_une_panne_d_ecoute_ne_range_rien(self, client, monkeypatch):
        from tts_client import TTSError

        async def en_panne(_texte, timeout=None):
            raise TTSError("panne")

        monkeypatch.setattr(routeur, "synthesize_remote", en_panne)
        http, _ = client
        http.post("/admin/atelier/ecouter", json={"pulaar": "Jamais synthetise."})
        assert catalogue_audio.phrase_deja_generee("Jamais synthetise.") is False


class TestSignalements:
    def test_le_plus_frequent_vient_en_premier(self, client):
        # Une phrase qui revient souvent mérite d'être relue avant une phrase
        # rare, même si les deux sont également « non relues ».
        phrases.reinitialiser_signalements()
        rare = phrases.reponse(phrases.Phrase(francais="Rare.", origine="champ:rare"))
        frequente = phrases.reponse(phrases.Phrase(francais="Souvent.", origine="champ:frequent"))
        phrases.signaler(rare)
        for _ in range(3):
            phrases.signaler(frequente)

        http, _ = client
        corps = http.get("/admin/atelier/signalements").json()

        assert corps["signalements"][0] == {"origine": "champ:frequent", "fois": 3}
        assert corps["total"] == 4
        phrases.reinitialiser_signalements()
