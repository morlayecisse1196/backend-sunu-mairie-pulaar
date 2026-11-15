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


class TestDansLeDialogue:
    """Le comportement complet : ce que l'agent dit, et ce qu'il NE compte pas."""

    @pytest.fixture
    def demarche_en_place(self, monkeypatch):
        monkeypatch.setattr(slot_controller, "charger_definition_demarche", lambda _t, _v=None: CHAMPS)
        monkeypatch.setattr(slot_controller, "charger_documents_demarche", lambda _t, _v=None: [])
        monkeypatch.setattr(regles_demarche, "charger_regles", lambda _t, _v=None: [])
        monkeypatch.setattr(slot_controller, "list_documents", lambda _id: [])

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
