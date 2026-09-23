"""
Simulateur de démarche (plan maître, étape 4.3).

Vérifier une modification demandait un téléphone, un réseau, le service vocal
réveillé et quelqu'un pour parler pulaar dix minutes. Autant dire qu'on ne
vérifiait pas.

Ce qui est verrouillé ici :

  * le simulateur emprunte les MÊMES fonctions que le dialogue réel — simuler
    avec un autre moteur ne prouverait rien ;
  * les conditions branchent : une pièce conditionnée n'est pas réclamée quand
    sa condition est fausse ;
  * une réponse invalide est refusée ici comme elle le serait en vrai ;
  * le rapport dit quelles phrases repassent encore par le traducteur — le
    critère de vérification de l'étape 3, rendu observable ;
  * une démarche qui boucle est arrêtée au lieu de faire tourner le serveur.
"""
from __future__ import annotations

import pytest

from services import catalogue_audio, demarche, simulateur

CHAMPS = [
    {"type_demarche": "d", "nom_champ": "nom_enfant", "ordre": 10, "type_valeur": "texte",
     "question": "Quel est le nom ?", "obligatoire": True, "condition": None,
     "relances": ["Le nom, s'il vous plaît ?"], "regle_validation": None,
     "question_pulaar": "Innde?", "pulaar_valide": True, "relances_pulaar": [], "relances_pulaar_valide": []},
    {"type_demarche": "d", "nom_champ": "parents_maries", "ordre": 20, "type_valeur": "booleen",
     "question": "Les parents sont-ils mariés ?", "obligatoire": True, "condition": None,
     "relances": ["Oui ou non ?"], "regle_validation": None,
     "question_pulaar": None, "pulaar_valide": False, "relances_pulaar": [], "relances_pulaar_valide": []},
    {"type_demarche": "d", "nom_champ": "date_naissance_enfant", "ordre": 30, "type_valeur": "date",
     "question": "Quelle est sa date de naissance ?", "obligatoire": True, "condition": None,
     "relances": ["La date ?"], "regle_validation": None,
     "question_pulaar": "Ñalnde?", "pulaar_valide": True, "relances_pulaar": [], "relances_pulaar_valide": []},
]
DOCUMENTS = [
    {"type_demarche": "d", "type_document": "livret_famille", "ordre": 25,
     "message_demande": "Une photo du livret de famille.", "apres_champ": "parents_maries",
     "condition": "parents_maries = oui", "obligatoire": True, "groupe": None,
     "messages_rappel": ["Toujours pas reçue."], "message_demande_pulaar": None,
     "pulaar_valide": False, "messages_rappel_pulaar": [], "messages_rappel_pulaar_valide": []},
]
CAS = [
    {"type_demarche": "d", "code": "dans_les_delais", "ordre": 10,
     "condition": "parents_maries = oui", "libelle": "Mariés"},
    {"type_demarche": "d", "code": "autre", "ordre": 20, "condition": None, "libelle": "Autre"},
]
GABARITS = [
    {"type_demarche": "d", "cle": "recapitulatif",
     "francais": "{nom_enfant}, né le {date_naissance_enfant}. Est-ce exact ?",
     "pulaar": "{nom_enfant}, jibinaaɗo {date_naissance_enfant}. Ko goonga?",
     "pulaar_valide": True, "contexte": "RG7"},
]
DEFINITION = [{"type_demarche": "d", "libelle": "Démarche", "version": 1, "traitable": True,
               "mots_cles": ["test"], "champ_age": None}]

TABLES = {
    "demarche_champs": CHAMPS, "demarche_documents": DOCUMENTS, "demarche_cas": CAS,
    "demarche_gabarits": GABARITS, "demarche_definitions": DEFINITION, "demarche_regles": [],
}

COMPLET = {
    "nom_enfant": "Ibrahima Diallo",
    "parents_maries": "oui",
    "date_naissance_enfant": "2026-09-07",
    "livret_famille": True,
}


@pytest.fixture(autouse=True)
def base(monkeypatch):
    def lire(nom, **filtres):
        lignes = TABLES.get(nom, [])
        for colonne, valeur in filtres.items():
            lignes = [l for l in lignes if l.get(colonne) == valeur]
        return lignes

    monkeypatch.setattr(demarche, "_table", lire)
    demarche.vider_cache()


def _genres(rapport):
    return [t.genre for t in rapport.tours]


def _cles(rapport):
    return [t.cle for t in rapport.tours]


class TestDeroule:
    def test_un_scenario_complet_va_jusqu_au_recapitulatif(self):
        rapport = simulateur.jouer(COMPLET, "d")
        assert rapport.termine is True
        assert rapport.arret is None
        assert _genres(rapport)[-1] == simulateur.RECAPITULATIF

    def test_les_etapes_suivent_l_ordre_de_la_demarche(self):
        # Le livret (ordre 25) s'intercale entre parents_maries et la date.
        rapport = simulateur.jouer(COMPLET, "d")
        assert _cles(rapport) == [
            "nom_enfant", "parents_maries", "livret_famille",
            "date_naissance_enfant", "recapitulatif",
        ]

    def test_le_recapitulatif_porte_les_valeurs_du_scenario(self):
        rapport = simulateur.jouer(COMPLET, "d")
        dernier = rapport.tours[-1]
        assert "Ibrahima Diallo" in dernier.dit
        assert "2026-09-07" in dernier.dit

    def test_le_cas_legal_est_determine(self):
        assert simulateur.jouer(COMPLET, "d").cas == "dans_les_delais"

    def test_les_slots_finaux_sont_normalises(self):
        # `valider_valeur` normalise : « oui » devient un vrai booléen.
        rapport = simulateur.jouer(COMPLET, "d")
        assert rapport.slots["parents_maries"] is True


class TestConditions:
    def test_une_piece_conditionnee_n_est_pas_reclamee_si_la_condition_est_fausse(self):
        # Le point le plus utile de l'écran : voir une branche sans la jouer
        # pour de vrai. Parents non mariés → pas de livret de famille.
        rapport = simulateur.jouer({**COMPLET, "parents_maries": "non"}, "d")
        assert "livret_famille" not in _cles(rapport)
        assert rapport.termine is True

    def test_le_cas_bascule_avec_la_condition(self):
        rapport = simulateur.jouer({**COMPLET, "parents_maries": "non"}, "d")
        assert rapport.cas == "autre"


class TestRefus:
    def test_une_reponse_invalide_est_refusee_comme_en_vrai(self):
        rapport = simulateur.jouer({**COMPLET, "date_naissance_enfant": "un mardi"}, "d")
        assert rapport.termine is False
        assert simulateur.REFUS in _genres(rapport)
        assert "date_naissance_enfant" in rapport.arret

    def test_le_refus_montre_la_relance_qui_serait_dite(self):
        rapport = simulateur.jouer({**COMPLET, "date_naissance_enfant": "un mardi"}, "d")
        relance = next(t for t in rapport.tours if t.genre == simulateur.REFUS)
        assert relance.dit == "La date ?"

    def test_une_etape_sans_reponse_au_scenario_arrete_proprement(self):
        # Ce n'est pas une erreur : ça dit jusqu'où le scénario mène.
        sans_date = {k: v for k, v in COMPLET.items() if k != "date_naissance_enfant"}
        rapport = simulateur.jouer(sans_date, "d")
        assert rapport.termine is False
        assert "date_naissance_enfant" in rapport.arret

    def test_une_piece_non_fournie_arrete_proprement(self):
        sans_piece = {k: v for k, v in COMPLET.items() if k != "livret_famille"}
        rapport = simulateur.jouer(sans_piece, "d")
        assert rapport.termine is False
        assert "livret_famille" in rapport.arret


class TestVerificationDeLEtape3:
    """Le rapport doit répondre : ce dialogue appelle-t-il encore le modèle ?"""

    def test_les_phrases_sans_pulaar_relu_sont_nommees(self):
        rapport = simulateur.jouer(COMPLET, "d")
        # parents_maries et le livret n'ont pas de pulaar relu.
        assert "champ:parents_maries" in rapport.a_traduire
        assert "document:livret_famille" in rapport.a_traduire
        assert "champ:nom_enfant" not in rapport.a_traduire

    def test_un_dialogue_entierement_relu_est_annonce_comme_tel(self, monkeypatch):
        relus = [{**c, "question_pulaar": "Pulaar relu.", "pulaar_valide": True} for c in CHAMPS]
        tables = {**TABLES, "demarche_champs": relus, "demarche_documents": []}
        monkeypatch.setattr(demarche, "_table", lambda nom, **f: tables.get(nom, []))
        demarche.vider_cache()

        rapport = simulateur.jouer(COMPLET, "d")

        assert rapport.a_traduire == [], "aucun appel de traduction"
        assert rapport.en_dict()["sans_traducteur"] is True

    def test_les_phrases_relues_sans_audio_sont_nommees(self):
        rapport = simulateur.jouer(COMPLET, "d")
        assert "champ:nom_enfant" in rapport.sans_audio

    def test_une_phrase_dont_l_audio_existe_n_est_pas_signalee(self):
        import asyncio

        asyncio.run(catalogue_audio.enregistrer_phrase("Innde?", b"WAV"))
        rapport = simulateur.jouer(COMPLET, "d")
        assert "champ:nom_enfant" not in rapport.sans_audio


class TestGardeFous:
    def test_une_demarche_qui_boucle_est_arretee(self, monkeypatch):
        # Un champ dont la valeur validée reste vide ne se remplit jamais :
        # sans garde-fou, la requête ne reviendrait pas.
        monkeypatch.setattr(
            simulateur.slot_controller, "valider_valeur",
            lambda *a, **k: (True, None, None))
        rapport = simulateur.jouer(COMPLET, "d")
        assert rapport.termine is False
        assert "tours" in (rapport.arret or "")

    def test_sans_gabarit_le_manque_est_dit_au_lieu_d_etre_taise(self, monkeypatch):
        # Le dialogue réel retomberait sur le texte figé ; le simulateur doit
        # le dire, sinon on croit le récapitulatif relu alors qu'il ne l'est pas.
        tables = {**TABLES, "demarche_gabarits": []}
        monkeypatch.setattr(demarche, "_table", lambda nom, **f: tables.get(nom, []))
        demarche.vider_cache()

        rapport = simulateur.jouer(COMPLET, "d")

        assert rapport.tours[-1].genre == simulateur.MANQUE
        assert rapport.termine is True


class TestScenarioType:
    def test_le_scenario_de_depart_couvre_tous_les_champs_et_pieces(self):
        scenario = simulateur.scenario_type("d")
        assert set(scenario) == {
            "nom_enfant", "parents_maries", "date_naissance_enfant", "livret_famille"}

    def test_le_scenario_de_depart_se_deroule_jusqu_au_bout(self):
        # Ouvrir l'écran sur quelque chose qui marche, pas sur un formulaire vide.
        assert simulateur.jouer(simulateur.scenario_type("d"), "d").termine is True


class TestDatesDuScenario:
    """
    Un scénario de départ qui se fait refuser dès la deuxième question fait
    croire à l'utilisateur qu'il a cassé quelque chose, alors qu'il vient
    d'ouvrir l'écran.
    """

    CHAMPS_DATES = [
        {"type_demarche": "d", "nom_champ": "date_enfant", "ordre": 10, "type_valeur": "date",
         "question": "Date de l'enfant ?", "obligatoire": True, "condition": None,
         "relances": [], "regle_validation": "passee", "pulaar_valide": False},
        {"type_demarche": "d", "nom_champ": "date_mere", "ordre": 20, "type_valeur": "date",
         "question": "Date de la mère ?", "obligatoire": True, "condition": None,
         "relances": [], "regle_validation": "passee|avant:date_enfant", "pulaar_valide": False},
    ]

    @pytest.fixture
    def base_dates(self, monkeypatch):
        tables = {**TABLES, "demarche_champs": self.CHAMPS_DATES,
                  "demarche_documents": [], "demarche_gabarits": []}
        monkeypatch.setattr(demarche, "_table", lambda nom, **f: tables.get(nom, []))
        demarche.vider_cache()

    def test_une_date_qui_doit_en_preceder_une_autre_recule(self, base_dates):
        scenario = simulateur.scenario_type("d")
        assert scenario["date_mere"] < scenario["date_enfant"]

    def test_le_scenario_par_defaut_passe_la_regle_croisee(self, base_dates):
        rapport = simulateur.jouer(simulateur.scenario_type("d"), "d")
        assert rapport.termine is True, rapport.arret

    def test_une_regle_circulaire_ne_fait_pas_boucler(self, monkeypatch):
        # Démarche mal formée : A avant B et B avant A. Le simulateur doit
        # rendre la main, pas tourner indéfiniment.
        circulaires = [
            {**self.CHAMPS_DATES[0], "regle_validation": "avant:date_mere"},
            {**self.CHAMPS_DATES[1], "regle_validation": "avant:date_enfant"},
        ]
        tables = {**TABLES, "demarche_champs": circulaires, "demarche_documents": []}
        monkeypatch.setattr(demarche, "_table", lambda nom, **f: tables.get(nom, []))
        demarche.vider_cache()

        scenario = simulateur.scenario_type("d")

        assert set(scenario) == {"date_enfant", "date_mere"}

    def test_la_date_de_naissance_reste_dans_le_passe(self, base_dates):
        # `regle_validation="passee"` refuserait une date future.
        from datetime import date as _date

        assert simulateur.scenario_type("d")["date_enfant"] < _date.today().isoformat()


class TestDateDeSimulation:
    """
    Le cas légal doit être calculé à la date SIMULÉE, pas à celle du jour.

    Sinon, rejouer un dossier d'il y a six mois donnait le cas d'aujourd'hui :
    on croyait vérifier une démarche, on vérifiait le calendrier. Le défaut
    est resté invisible tant que les tests tournaient le jour même où ils
    avaient été écrits.
    """

    def test_le_cas_suit_la_date_donnee(self):
        from datetime import date as _date
        cas_dates = [
            {"type_demarche": "d", "code": "recent", "ordre": 10,
             "condition": "jours_depuis(date_naissance_enfant) <= 30", "libelle": "Récent"},
            {"type_demarche": "d", "code": "ancien", "ordre": 20, "condition": None, "libelle": "Ancien"},
        ]
        TABLES["demarche_cas"] = cas_dates
        try:
            reponses = {**COMPLET, "date_naissance_enfant": "2026-01-10"}
            proche = simulateur.jouer(reponses, "d", aujourdhui=_date(2026, 1, 20))
            lointain = simulateur.jouer(reponses, "d", aujourdhui=_date(2026, 9, 20))
            assert (proche.cas, lointain.cas) == ("recent", "ancien")
        finally:
            TABLES["demarche_cas"] = CAS
