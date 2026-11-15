"""
Où en est le citoyen dans sa démarche (barre d'avancement de l'application).

Un décompte d'avancement est facile à écrire et facile à rendre faux : il
suffit qu'il compte des questions que le dialogue ne posera jamais. Ces
démarches posent justement des questions CONDITIONNELLES — le nom du père
n'est demandé que si les parents sont mariés, le nombre d'épouses que si
l'union est polygame.

La règle tenue ici : la progression compte exactement les étapes que
`determiner_etape_courante` peut encore servir. Ni plus (sinon la barre
n'atteint jamais le bout), ni moins (sinon elle saute).

La démarche ci-dessous est FICTIVE : elle ne décrit aucune règle de droit,
elle fait travailler le moteur.
"""
from __future__ import annotations

import asyncio

import pytest

import slot_controller
from services import regles_demarche

CHAMPS = [
    {"nom_champ": "date_ceremonie", "type_valeur": "date", "ordre": 10, "obligatoire": True,
     "question": "Quel jour ?", "regle_validation": "passee", "condition": None},
    {"nom_champ": "option", "type_valeur": "enum", "ordre": 20, "obligatoire": True,
     "question": "Monogamie ou polygamie ?", "regle_validation": "monogamie|polygamie", "condition": None},
    {"nom_champ": "surnom", "type_valeur": "texte", "ordre": 30, "obligatoire": False,
     "question": "Un surnom ?", "regle_validation": None, "condition": None},
    # La question qui n'existe que dans un cas.
    {"nom_champ": "nombre_epouses", "type_valeur": "nombre", "ordre": 40, "obligatoire": True,
     "question": "Combien d'épouses ?", "regle_validation": "1:4", "condition": "option = polygamie"},
]

# Une pièce OU l'autre suffit : c'est UNE étape, pas deux.
DOCUMENTS = [
    {"type_document": "certificat_medical", "ordre": 50, "obligatoire": True,
     "groupe": "preuve", "condition": None, "condition_champ": None},
    {"type_document": "attestation_temoins", "ordre": 51, "obligatoire": True,
     "groupe": "preuve", "condition": None, "condition_champ": None},
]


def avancement(slots, documents=frozenset(), ignores=frozenset()):
    return slot_controller.progression(slots, set(documents), CHAMPS, DOCUMENTS, set(ignores))


def etape(slots, documents=frozenset(), ignores=frozenset()):
    return slot_controller.determiner_etape_courante(slots, set(documents), CHAMPS, DOCUMENTS, set(ignores))


class TestDecompte:
    def test_au_depart_rien_n_est_fait(self):
        # 3 champs sans condition + 1 groupe de pièces + la question
        # conditionnelle, encore indécidable.
        assert avancement({}) == {"faites": 0, "total": 5}

    def test_chaque_reponse_avance_d_une_etape(self):
        assert avancement({"date_ceremonie": "2026-09-01"})["faites"] == 1
        assert avancement({"date_ceremonie": "2026-09-01", "option": "monogamie"})["faites"] == 2

    def test_une_question_ecartee_disparait_du_total(self):
        # En monogamie, « combien d'épouses » ne sera JAMAIS posée : la
        # compter empêcherait la barre d'arriver au bout.
        monogame = avancement({"option": "monogamie"})
        assert monogame["total"] == 4
        # En polygamie elle reste due.
        assert avancement({"option": "polygamie"})["total"] == 5

    def test_une_condition_encore_inconnue_reste_comptee(self):
        # Tant qu'on ignore le régime de l'union, la question peut arriver :
        # l'oublier ferait reculer la barre au tour suivant.
        assert avancement({"date_ceremonie": "2026-09-01"})["total"] == 5

    def test_une_seule_piece_suffit_pour_le_groupe(self):
        sans = avancement({})
        avec = avancement({}, documents={"attestation_temoins"})
        assert avec["total"] == sans["total"], "un groupe alternatif reste UNE étape"
        assert avec["faites"] == 1

    def test_un_champ_facultatif_abandonne_compte_comme_fait(self):
        # Il ne sera plus jamais demandé : le laisser « à faire » bloquerait
        # la barre juste avant la fin.
        assert avancement({}, ignores={"surnom"})["faites"] == 1

    def test_tout_rempli_ferme_la_barre(self):
        slots = {"date_ceremonie": "2026-09-01", "option": "monogamie", "surnom": "Baay"}
        fin = avancement(slots, documents={"certificat_medical"})
        assert fin["faites"] == fin["total"] == 4


class TestAccordAvecLeDialogue:
    """La barre et les questions posées doivent raconter la même histoire."""

    CAS = [
        ({}, frozenset(), frozenset()),
        ({"date_ceremonie": "2026-09-01"}, frozenset(), frozenset()),
        ({"date_ceremonie": "2026-09-01", "option": "polygamie"}, frozenset(), frozenset()),
        ({"date_ceremonie": "2026-09-01", "option": "monogamie"}, frozenset(), {"surnom"}),
        ({"date_ceremonie": "2026-09-01", "option": "monogamie", "surnom": "Baay"},
         {"certificat_medical"}, frozenset()),
    ]

    @pytest.mark.parametrize("slots,documents,ignores", CAS)
    def test_il_reste_une_etape_exactement_quand_il_reste_du_chemin(self, slots, documents, ignores):
        reste = etape(slots, documents, ignores) is not None
        compte = avancement(slots, documents, ignores)
        assert reste == (compte["faites"] < compte["total"])

    @pytest.mark.parametrize("slots,documents,ignores", CAS)
    def test_la_barre_ne_deborde_jamais(self, slots, documents, ignores):
        compte = avancement(slots, documents, ignores)
        assert 0 <= compte["faites"] <= compte["total"]


class TestCeQuiEstEnvoyeAuTelephone:
    @pytest.fixture
    def demarche(self, monkeypatch):
        monkeypatch.setattr(slot_controller, "charger_definition_demarche", lambda _t, _v=None: CHAMPS)
        monkeypatch.setattr(slot_controller, "charger_documents_demarche", lambda _t, _v=None: DOCUMENTS)
        monkeypatch.setattr(regles_demarche, "charger_regles", lambda _t, _v=None: [])
        monkeypatch.setattr(slot_controller, "list_documents", lambda _id: [])

    def _tour(self, etat, valeur, monkeypatch):
        async def faux_llm(_headers, _payload, retries=2):
            return {"reponse_valide": True, "valeur": valeur, "reponse": "Merci."}

        monkeypatch.setattr(slot_controller, "_call_openrouter_structured_isole", faux_llm)
        return asyncio.run(slot_controller.traiter_tour_administratif(etat, "peu importe", {}))

    def test_le_tour_dit_ou_on_en_est_APRES_la_reponse(self, demarche, monkeypatch):
        etat = {"slots": {}, "type_demarche": "fictive", "dossier_id": None}
        resultat = self._tour(etat, "2026-09-01", monkeypatch)
        # Après cette réponse, une étape est faite : la barre doit bouger tout
        # de suite, pas au tour suivant.
        assert resultat["progression"] == {"faites": 1, "total": 5}

    def test_une_demarche_bloquee_n_annonce_aucun_avancement(self, demarche, monkeypatch):
        # Le délai légal est dépassé : il n'y a plus de chemin, donc plus
        # d'avancement à montrer.
        monkeypatch.setattr(regles_demarche, "charger_regles", lambda _t, _v=None: [
            {"code": "trop_tard", "ordre": 10, "effet": "bloquer", "condition": "rempli(date_ceremonie)",
             "champ_concerne": None, "source": "fictive", "message": "Trop tard."},
        ])
        etat = {"slots": {"date_ceremonie": "2026-09-01"}, "type_demarche": "fictive", "dossier_id": None}
        resultat = self._tour(etat, "monogamie", monkeypatch)

        assert resultat["phase_suivante"] == "bloque"
        assert "progression" not in resultat
