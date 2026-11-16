"""
« Bonjour » n'est pas une mauvaise réponse.

CE QUI N'ALLAIT PAS

En mode administratif, TOUT message partait au modèle ciblé sur le champ en
cours ; ce qui n'y répondait pas comptait comme un échec. Mesuré sur le vrai
modèle, quatre messages sur quatre :

    « Bonjour »            -> « Je n'ai pas compris. Quel âge a votre enfant ? »
    « Salaam alaikum »     -> « Je n'ai pas compris. … »
    « Merci »              -> « Je n'ai pas compris. … »
    « Attends un instant » -> « Je n'ai pas compris. … »

Et `SEUIL_ECHECS_CHAMP` vaut 3 : trois politesses d'affilée abandonnaient le
champ et ouvraient un cas particulier. Dire bonjour, merci et attends suffisait
à saboter sa propre demande.
"""
from __future__ import annotations

import asyncio

import pytest

import slot_controller
from services import regles_demarche, tours_sociaux
from temps_reel import intentions

CHAMPS = [
    {"nom_champ": "age_enfant", "type_valeur": "age", "ordre": 10,
     "question": "Quel âge a votre enfant ?", "obligatoire": True,
     "relances": ["Je n'ai pas compris. Quel âge a votre enfant ?"]},
]


class TestCeQuiEstReconnu:
    @pytest.mark.parametrize("message", [
        "Bonjour", "bonsoir", "Salut", "Salaam alaikum", "salam alaikum",
        "Bonjour, comment ça va ?", "jam tan", "Coucou",
    ])
    def test_les_salutations(self, message):
        assert tours_sociaux.classer(message) == tours_sociaux.SALUTATION

    @pytest.mark.parametrize("message", ["Merci", "Merci beaucoup", "Jerejef", "jaaraama"])
    def test_les_remerciements(self, message):
        assert tours_sociaux.classer(message) == tours_sociaux.REMERCIEMENT

    @pytest.mark.parametrize("message", [
        "Attends", "Attendez un instant", "un instant s'il vous plaît", "une minute",
    ])
    def test_les_demandes_de_pause(self, message):
        assert tours_sociaux.classer(message) == tours_sociaux.PATIENCE

    @pytest.mark.parametrize("message", [
        "Répète", "Répétez s'il vous plaît", "Je n'ai pas compris",
        "je n'ai pas entendu", "Pardon ?",
    ])
    def test_les_demandes_de_repetition(self, message):
        assert tours_sociaux.classer(message) == tours_sociaux.REPETITION


class TestCeQuiNeDoitJAMAISEtreAvale:
    """
    La propriété qui compte. Classer à tort, c'est perdre une réponse que le
    citoyen a déjà donnée — et la lui redemander, ce qui est exactement le
    défaut qu'on corrige.
    """

    @pytest.mark.parametrize("message", [
        "Il a trois jours",
        "trois jours",
        "Ibrahima Diallo",
        "Awa",
        "le 7 septembre 2026",
        "Ross-Béthio",
        "C'est un garçon",
        "oui",
        "non",
    ])
    def test_une_vraie_reponse_passe_au_dialogue(self, message):
        assert tours_sociaux.classer(message) is None

    @pytest.mark.parametrize("message", [
        "Bonjour, il a trois jours",
        "Merci, c'est Awa",
        "Bonjour, mon enfant s'appelle Ibrahima",
    ])
    def test_une_politesse_SUIVIE_dune_reponse_nest_pas_une_politesse(self, message):
        # Le message porte la réponse : l'avaler la perdrait.
        assert tours_sociaux.classer(message) is None

    def test_un_message_vide_ne_classe_rien(self):
        assert tours_sociaux.classer("") is None
        assert tours_sociaux.classer("   ") is None

    def test_un_long_message_nest_pas_une_formule(self):
        assert tours_sociaux.classer(
            "bonjour je voudrais savoir si mon enfant peut avoir un extrait aujourd hui"
        ) is None


@pytest.fixture
def demarche_en_place(monkeypatch):
    """Une démarche d'un seul champ, sans base ni réseau."""
    monkeypatch.setattr(slot_controller, "charger_definition_demarche", lambda _t, _v=None: CHAMPS)
    monkeypatch.setattr(slot_controller, "charger_documents_demarche", lambda _t, _v=None: [])
    monkeypatch.setattr(regles_demarche, "charger_regles", lambda _t, _v=None: [])
    monkeypatch.setattr(slot_controller, "list_documents", lambda _id: [])


class TestDansLeDialogue:
    """Le comportement complet : ce que l'agent dit, et ce qu'il NE compte pas."""

    def _tour(self, etat, message, monkeypatch, *, llm_appele=None):
        async def llm_interdit(_headers, _payload, retries=2):
            if llm_appele is not None:
                llm_appele.append(True)
            pytest.fail("le modèle a été appelé pour un simple bonjour")

        monkeypatch.setattr(slot_controller, "_call_openrouter_structured_isole", llm_interdit)
        return asyncio.run(slot_controller.traiter_tour_administratif(etat, message, {}))

    def _etat(self):
        return {"slots": {}, "type_demarche": "fictive", "dossier_id": None}

    def test_une_salutation_ne_passe_pas_par_le_modele(self, demarche_en_place, monkeypatch):
        # Économie réelle : un appel distant en moins, donc une seconde de
        # moins avant que l'agent reparle.
        self._tour(self._etat(), "Bonjour", monkeypatch)

    def test_la_question_est_reposee_telle_quelle(self, demarche_en_place, monkeypatch):
        resultat = self._tour(self._etat(), "Bonjour", monkeypatch)
        assert "Quel âge a votre enfant" in resultat["reponse_fr"]

    def test_lagent_ne_dit_pas_quil_na_pas_compris(self, demarche_en_place, monkeypatch):
        for message in ("Bonjour", "Merci", "Attends un instant"):
            resultat = self._tour(self._etat(), message, monkeypatch)
            assert "pas compris" not in resultat["reponse_fr"].lower(), message

    def test_aucun_compteur_dechec_ne_bouge(self, demarche_en_place, monkeypatch):
        """
        Le cœur du correctif. Trois politesses de suite laissaient le champ
        abandonné ; elles doivent maintenant le laisser intact, avec ses trois
        essais encore disponibles.
        """
        etat = self._etat()
        for message in ("Bonjour", "Merci", "Attends un instant"):
            resultat = self._tour(etat, message, monkeypatch)
            assert resultat.get("cas_particulier_cree") is False, message
        compteurs = etat.get("compteurs_echec") or etat.get("compteurs") or {}
        assert not compteurs.get("age_enfant"), "une politesse a été comptée comme un échec"
        assert etat["slots"] == {}, "aucune valeur ne doit avoir été écrite"

    def test_une_demande_de_pause_ne_repose_pas_la_question(self, demarche_en_place, monkeypatch):
        # Il vient de demander un instant : la lui reposer serait ne pas
        # l'avoir écouté.
        resultat = self._tour(self._etat(), "Attends un instant", monkeypatch)
        assert "Quel âge" not in resultat["reponse_fr"]

    def test_une_vraie_reponse_atteint_toujours_le_modele(self, demarche_en_place, monkeypatch):
        """Le garde-fou du garde-fou : le tri ne doit rien intercepter d'utile."""
        vu = []

        async def faux_llm(_headers, _payload, retries=2):
            vu.append(True)
            return {"reponse_valide": True, "valeur": {"valeur": 3, "unite": "jours"},
                    "reponse": "Noté."}

        monkeypatch.setattr(slot_controller, "_call_openrouter_structured_isole", faux_llm)
        asyncio.run(slot_controller.traiter_tour_administratif(self._etat(), "Il a trois jours", {}))
        assert vu, "une vraie réponse doit être soumise au modèle"


class TestLaPremiereQuestionNeSexcusePas:
    """
    La remarque d'origine du terrain : « si l'agent dit "Je n'ai pas compris.
    Quel âge a votre enfant", ce n'est pas normal ».

    Cause trouvée en jouant le dialogue : au moment où le citoyen accepte de
    commencer, le moteur rejoue SON message dans le collecteur de champs.
    C'est voulu — « je veux un extrait pour mon fils de sept jours » contient
    déjà la première réponse. Mais sur un simple « eey », il n'y a rien à
    extraire : le modèle jugeait la réponse invalide, et la toute PREMIÈRE
    question de chaque démarche arrivait précédée d'excuses.
    """

    @pytest.mark.parametrize("message", ["oui", "eey", "eyyi", "ok", "oui merci", "bonjour oui"])
    def test_un_accord_nu_est_reconnu(self, message):
        assert intentions.est_confirmation_seule(message) is True

    @pytest.mark.parametrize("message", [
        "oui il a trois jours",     # porte la réponse : surtout ne pas la jeter
        "oui, c'est Awa",
        "non",
        "alaa",
        "il a trois jours",
        "oui mais la date est fausse",
    ])
    def test_ce_qui_porte_autre_chose_nest_pas_un_accord_nu(self, message):
        assert intentions.est_confirmation_seule(message) is False

    def test_le_collecteur_pose_la_question_sans_sexcuser(self, demarche_en_place, monkeypatch):
        async def llm_interdit(_headers, _payload, retries=2):
            pytest.fail("le modèle a été appelé alors qu'il n'y avait rien à lire")

        monkeypatch.setattr(slot_controller, "_call_openrouter_structured_isole", llm_interdit)
        etat = {"slots": {}, "type_demarche": "fictive", "dossier_id": None}
        resultat = asyncio.run(
            slot_controller.traiter_tour_administratif(etat, "oui", {}, True))

        assert "Quel âge a votre enfant" in resultat["reponse_fr"]
        assert "pas compris" not in resultat["reponse_fr"].lower()
        assert not (etat.get("compteurs_echecs") or {}).get("age_enfant")

    def test_sans_le_drapeau_le_message_est_bien_interprete(self, demarche_en_place, monkeypatch):
        """Le chemin normal ne change pas : un vrai message part au modèle."""
        vu = []

        async def faux_llm(_headers, _payload, retries=2):
            vu.append(True)
            return {"reponse_valide": True, "valeur": {"valeur": 3, "unite": "jours"}, "reponse": "Noté."}

        monkeypatch.setattr(slot_controller, "_call_openrouter_structured_isole", faux_llm)
        etat = {"slots": {}, "type_demarche": "fictive", "dossier_id": None}
        asyncio.run(slot_controller.traiter_tour_administratif(etat, "trois jours", {}, False))
        assert vu


class TestUnChampOuiNonAccepteToujoursOui:
    """
    Le garde-fou qui compte. `sans_interpreter` n'est posé qu'à la bascule,
    jamais en pleine collecte : sinon « oui » cesserait d'être une réponse
    valable pour un champ booléen — « Les parents sont-ils mariés ? » — et la
    correction aurait cassé la moitié des démarches.
    """

    CHAMP_BOOLEEN = [{
        "nom_champ": "parents_maries", "type_valeur": "booleen", "ordre": 10,
        "question": "Les parents sont-ils mariés ?", "obligatoire": True, "relances": [],
    }]

    def test_oui_reste_une_reponse(self, monkeypatch):
        monkeypatch.setattr(slot_controller, "charger_definition_demarche",
                            lambda _t, _v=None: self.CHAMP_BOOLEEN)
        monkeypatch.setattr(slot_controller, "charger_documents_demarche", lambda _t, _v=None: [])
        monkeypatch.setattr(regles_demarche, "charger_regles", lambda _t, _v=None: [])
        monkeypatch.setattr(slot_controller, "list_documents", lambda _id: [])

        async def faux_llm(_headers, _payload, retries=2):
            return {"reponse_valide": True, "valeur": True, "reponse": "Noté."}

        monkeypatch.setattr(slot_controller, "_call_openrouter_structured_isole", faux_llm)
        etat = {"slots": {}, "type_demarche": "fictive", "dossier_id": None}
        asyncio.run(slot_controller.traiter_tour_administratif(etat, "oui", {}))
        assert etat["slots"]["parents_maries"] is True

    def test_tours_sociaux_nintercepte_pas_un_oui(self):
        # « oui » n'est ni une salutation ni un remerciement : il doit
        # traverser le tri social intact.
        assert tours_sociaux.classer("oui") is None
        assert tours_sociaux.classer("eey") is None
        assert tours_sociaux.classer("non") is None


DOCUMENT = [{"type_document": "certificat_naissance", "obligatoire": True, "ordre": 20,
             "message_demande": "Envoyez-moi la photo du certificat de naissance."}]


class TestCeQuiEstDitPendantQuOnAttendUnePhoto:
    """
    Pendant l'attente d'une pièce, tout ce que disait le citoyen était écarté
    EN SILENCE. Observé en jouant le dialogue : à la demande de photo, le
    citoyen répond « Ibrahima Diallo » — et l'agent se contente de redemander
    la photo. Ce nom tombe dans le vide, et le citoyen croit avoir été entendu.
    """

    @pytest.fixture
    def attente_de_photo(self, monkeypatch):
        monkeypatch.setattr(slot_controller, "charger_definition_demarche", lambda _t, _v=None: [])
        monkeypatch.setattr(slot_controller, "charger_documents_demarche", lambda _t, _v=None: DOCUMENT)
        monkeypatch.setattr(regles_demarche, "charger_regles", lambda _t, _v=None: [])
        monkeypatch.setattr(slot_controller, "list_documents", lambda _id: [])

        async def pas_de_refus(_type, _message, _headers):
            return False

        monkeypatch.setattr(slot_controller, "_citoyen_dit_ne_pas_avoir", pas_de_refus)

    def _tour(self, etat, message):
        return asyncio.run(slot_controller.traiter_tour_administratif(etat, message, {}))

    def test_le_premier_tour_ne_dit_rien_de_plus(self, attente_de_photo):
        # À ce moment-là le message répond encore à la question PRÉCÉDENTE,
        # pas à la demande de photo qui vient d'être posée.
        etat = {"slots": {}, "type_demarche": "fictive", "dossier_id": None}
        resultat = self._tour(etat, "Ibrahima Diallo")
        assert "entendu" not in resultat["reponse_fr"].lower()

    def test_ensuite_lagent_dit_quil_a_entendu(self, attente_de_photo):
        etat = {"slots": {}, "type_demarche": "fictive", "dossier_id": None}
        self._tour(etat, "")                       # 1er tour : la photo est demandée
        resultat = self._tour(etat, "Ibrahima Diallo")
        assert "entendu" in resultat["reponse_fr"].lower()
        # La demande de photo reste : c'est toujours elle qu'on attend.
        assert "photo" in resultat["reponse_fr"].lower()

    def test_une_simple_politesse_nappelle_pas_cet_accuse(self, attente_de_photo):
        etat = {"slots": {}, "type_demarche": "fictive", "dossier_id": None}
        self._tour(etat, "")
        resultat = self._tour(etat, "merci")
        assert "entendu" not in resultat["reponse_fr"].lower()

    def test_aucune_valeur_nest_devinee(self, attente_de_photo):
        """
        On accuse réception, on n'extrait rien : deviner à quel champ ce
        message répondrait reviendrait sur la discipline « une information à
        la fois », au risque d'écrire un nom d'enfant dans la case du
        déclarant.
        """
        etat = {"slots": {}, "type_demarche": "fictive", "dossier_id": None}
        self._tour(etat, "")
        self._tour(etat, "Ibrahima Diallo")
        assert etat["slots"] == {}
