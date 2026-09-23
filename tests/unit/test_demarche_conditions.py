"""
Les quatre formes de conditions, exercées sur une démarche FICTIVE
(plan maître, étapes 2.1 et 2.5).

La démarche ci-dessous n'existe pas et ne prétend décrire aucune règle de
droit : ses valeurs sont choisies pour faire travailler le moteur, pas pour
servir de référence. Les vraies règles de la constatation de mariage et de la
déclaration de décès viendront à l'étape 5, après relecture par un officier
d'état civil.

Elle sert à prouver ce qui compte : le moteur est piloté par la DONNÉE. Aucun
nom de champ, aucun seuil, aucune incompatibilité n'est écrit dans le code.
"""
from __future__ import annotations

from datetime import date

import pytest

import slot_controller
from services import regles_demarche

# ---------------------------------------------------------------------------
# Démarche fictive
# ---------------------------------------------------------------------------

CHAMPS = [
    {"nom_champ": "date_ceremonie", "type_valeur": "date", "ordre": 10, "obligatoire": True,
     "question": "Quel jour la cérémonie a-t-elle eu lieu ?", "regle_validation": "passee", "condition": None},
    {"nom_champ": "option", "type_valeur": "enum", "ordre": 20, "obligatoire": True,
     "question": "Monogamie ou polygamie ?", "regle_validation": "monogamie|polygamie", "condition": None},
    # Forme 3 — n'est posée que dans un cas : condition croisée à l'affichage.
    {"nom_champ": "regime", "type_valeur": "enum", "ordre": 30, "obligatoire": True,
     "question": "Communauté de biens ou séparation ?", "regle_validation": "communaute|separation",
     "condition": None},
    # Forme 1 — champ FACULTATIF : s'il ne sait pas, on continue sans.
    {"nom_champ": "surnom", "type_valeur": "texte", "ordre": 40, "obligatoire": False,
     "question": "Un surnom à inscrire ?", "regle_validation": None, "condition": None},
    {"nom_champ": "nombre_epouses", "type_valeur": "nombre", "ordre": 50, "obligatoire": True,
     "question": "Combien d'épouses ?", "regle_validation": "1:4", "condition": "option = polygamie"},
]

# Forme 4 — alternative : l'une OU l'autre des deux pièces suffit.
DOCUMENTS = [
    {"type_document": "certificat_medical", "ordre": 60, "obligatoire": True,
     "groupe": "preuve_union", "condition": None, "condition_champ": None},
    {"type_document": "attestation_temoins", "ordre": 61, "obligatoire": True,
     "groupe": "preuve_union", "condition": None, "condition_champ": None},
]

REGLES = [
    # Forme 2 — délai qui interrompt la démarche.
    {"code": "delai_depasse", "ordre": 10, "effet": "bloquer",
     "condition": "mois_depuis(date_ceremonie) > 6", "champ_concerne": None, "source": "démarche fictive",
     "message": "Plus de six mois se sont écoulés : cette démarche n'est plus possible, il faut passer par le tribunal."},
    # Forme 3 — combinaison interdite entre deux champs.
    {"code": "polygamie_sans_communaute", "ordre": 20, "effet": "interdire",
     "condition": "option = polygamie et regime = communaute", "champ_concerne": "regime",
     "source": "démarche fictive",
     "message": "La polygamie est incompatible avec la communauté de biens."},
]


@pytest.fixture
def demarche(monkeypatch):
    """Branche la démarche fictive à la place des tables Supabase."""
    monkeypatch.setattr(slot_controller, "charger_definition_demarche", lambda _t, _version=None: CHAMPS)
    monkeypatch.setattr(slot_controller, "charger_documents_demarche", lambda _t, _version=None: DOCUMENTS)
    monkeypatch.setattr(regles_demarche, "charger_regles", lambda _t, _version=None: REGLES)
    monkeypatch.setattr(slot_controller, "list_documents", lambda _id: [])


def nouvel_etat(**slots):
    return {"slots": dict(slots), "type_demarche": "demarche_fictive", "dossier_id": None}


def etape(slots, documents_recus=frozenset(), champs_ignores=frozenset()):
    return slot_controller.determiner_etape_courante(
        slots, set(documents_recus), CHAMPS, DOCUMENTS, set(champs_ignores)
    )


def repondre(etat, valeur, monkeypatch, *, reponse="Merci."):
    """Un tour : le modèle extrait `valeur`, le code valide et décide."""
    async def faux_llm(_headers, _payload, retries=2):
        return {"reponse_valide": True, "valeur": valeur, "reponse": reponse}

    monkeypatch.setattr(slot_controller, "_call_openrouter_structured_isole", faux_llm)
    import asyncio

    return asyncio.run(slot_controller.traiter_tour_administratif(etat, "peu importe", {}))


# ---------------------------------------------------------------------------
# Forme 1 — champ obligatoire / facultatif
# ---------------------------------------------------------------------------

class TestChampObligatoire:
    def test_un_champ_facultatif_abandonne_ne_revient_plus(self, demarche):
        slots = {"date_ceremonie": "2026-09-01", "option": "monogamie", "regime": "separation"}
        assert etape(slots)["definition"]["nom_champ"] == "surnom"
        # Une fois abandonné, le moteur passe à la suite.
        suivante = etape(slots, champs_ignores={"surnom"})
        assert suivante["type"] == "document"

    def test_trois_echecs_sur_un_champ_facultatif_font_avancer(self, demarche, monkeypatch):
        etat = nouvel_etat(date_ceremonie="2026-09-01", option="monogamie", regime="separation")

        async def refus(_headers, _payload, retries=2):
            return {"reponse_valide": False, "valeur": None, "reponse": "Je n'ai pas compris."}

        monkeypatch.setattr(slot_controller, "_call_openrouter_structured_isole", refus)
        import asyncio

        for _ in range(slot_controller.SEUIL_ECHECS_CHAMP - 1):
            resultat = asyncio.run(slot_controller.traiter_tour_administratif(etat, "euh", {}))
            assert "champ_ignore" not in resultat

        resultat = asyncio.run(slot_controller.traiter_tour_administratif(etat, "euh", {}))
        assert resultat["champ_ignore"] == "surnom"
        assert resultat["cas_particulier_cree"] is False, "un champ facultatif n'est pas un incident"
        # Et la question suivante est posée dans le même souffle : un citoyen
        # qui ne lit pas ne devinerait pas qu'il doit reparler.
        assert resultat["document_attendu"] == "certificat_medical"

    def test_un_champ_obligatoire_en_echec_reste_un_incident(self, demarche, monkeypatch):
        etat = nouvel_etat()  # premier champ : date_ceremonie, obligatoire

        async def refus(_headers, _payload, retries=2):
            return {"reponse_valide": False, "valeur": None, "reponse": "Quelle date ?"}

        monkeypatch.setattr(slot_controller, "_call_openrouter_structured_isole", refus)
        import asyncio

        for _ in range(slot_controller.SEUIL_ECHECS_CHAMP):
            resultat = asyncio.run(slot_controller.traiter_tour_administratif(etat, "euh", {}))
        assert resultat["cas_particulier_cree"] is True
        assert resultat["champ_en_echec"] == "date_ceremonie"


# ---------------------------------------------------------------------------
# Forme 2 — délai qui interrompt la démarche
# ---------------------------------------------------------------------------

class TestDelaiBloquant:
    def test_dans_les_delais_la_demarche_continue(self, demarche, monkeypatch):
        etat = nouvel_etat()
        resultat = repondre(etat, date.today().isoformat(), monkeypatch)
        assert resultat["phase_suivante"] == "collecte"
        assert etat["slots"]["date_ceremonie"] == date.today().isoformat()

    def test_hors_delai_la_demarche_s_arrete_avec_le_message_de_la_regle(self, demarche, monkeypatch):
        etat = nouvel_etat()
        resultat = repondre(etat, "2020-01-01", monkeypatch)
        assert resultat["phase_suivante"] == "bloque"
        assert resultat["regle_declenchee"] == "delai_depasse"
        assert "tribunal" in resultat["reponse_fr"], "le message doit orienter, pas seulement refuser"

    def test_une_session_reprise_hors_delai_bloque_sans_attendre_une_saisie(self, demarche, monkeypatch):
        # Tous les champs sont déjà remplis : l'étape courante est une PIÈCE,
        # et le tour ne valide donc aucune valeur. Sans contrôle en tête de
        # tour, le citoyen serait invité à photographier des documents pour un
        # dossier déjà hors délai — le seul contrôle après saisie ne se
        # déclencherait jamais.
        etat = nouvel_etat(
            date_ceremonie="2020-01-01", option="monogamie", regime="separation", surnom="Baay"
        )
        resultat = repondre(etat, "peu importe", monkeypatch)
        assert resultat["phase_suivante"] == "bloque"
        assert resultat["document_attendu"] is None


# ---------------------------------------------------------------------------
# Forme 3 — condition croisée entre deux champs
# ---------------------------------------------------------------------------

class TestConditionCroisee:
    def test_une_combinaison_interdite_est_refusee_et_redemandee(self, demarche, monkeypatch):
        etat = nouvel_etat(date_ceremonie=date.today().isoformat(), option="polygamie")
        resultat = repondre(etat, "communaute", monkeypatch)

        assert resultat["regle_declenchee"] == "polygamie_sans_communaute"
        assert "regime" not in etat["slots"], "une combinaison illégale ne doit jamais être conservée"
        assert "incompatible" in resultat["reponse_fr"]
        assert "Communauté de biens ou séparation ?" in resultat["reponse_fr"], "la question est reposée"

    def test_la_meme_valeur_est_acceptee_dans_l_autre_cas(self, demarche, monkeypatch):
        etat = nouvel_etat(date_ceremonie=date.today().isoformat(), option="monogamie")
        repondre(etat, "communaute", monkeypatch)
        assert etat["slots"]["regime"] == "communaute"

    def test_un_champ_conditionne_n_est_pose_que_si_sa_condition_est_vraie(self, demarche):
        base = {"date_ceremonie": "2026-09-01", "regime": "separation", "surnom": "Baay"}
        # nombre_epouses est conditionné par « option = polygamie ».
        assert etape({**base, "option": "monogamie"})["type"] == "document"
        assert etape({**base, "option": "polygamie"})["definition"]["nom_champ"] == "nombre_epouses"

    def test_tant_que_la_condition_est_indeterminee_l_etape_attend(self, demarche):
        # `option` pas encore renseignée : nombre_epouses n'est ni posé ni
        # définitivement écarté — il reviendra si la réponse l'exige.
        courante = etape({"date_ceremonie": "2026-09-01"})
        assert courante["definition"]["nom_champ"] == "option"


# ---------------------------------------------------------------------------
# Forme 4 — alternative entre deux pièces
# ---------------------------------------------------------------------------

class TestAlternativeEntreDeuxPieces:
    SLOTS = {"date_ceremonie": "2026-09-01", "option": "monogamie", "regime": "separation", "surnom": "Baay"}

    def test_une_seule_des_deux_pieces_suffit(self, demarche):
        assert etape(self.SLOTS)["type"] == "document"
        assert etape(self.SLOTS, documents_recus={"attestation_temoins"}) is None
        assert etape(self.SLOTS, documents_recus={"certificat_medical"}) is None

    def test_le_groupe_est_nomme_pas_deduit_de_l_ordre(self, demarche):
        # Les deux pièces ont des `ordre` DIFFÉRENTS (60 et 61) : sous
        # l'ancienne convention — même ordre = même groupe — elles auraient été
        # demandées l'une APRÈS l'autre, toutes les deux obligatoires.
        groupes = slot_controller.grouper_documents(DOCUMENTS)
        assert len(groupes) == 1
        assert {d["type_document"] for d in groupes[0]} == {"certificat_medical", "attestation_temoins"}

    def test_l_ancienne_convention_de_l_ordre_partage_reste_comprise(self, demarche):
        # Les lignes non migrées (sans colonne `groupe`) doivent continuer de
        # fonctionner : la migration 017 peut être appliquée après coup.
        anciens = [
            {"type_document": "livret_famille", "ordre": 100, "obligatoire": False, "condition_champ": "parents_maries"},
            {"type_document": "certificat_mariage", "ordre": 100, "obligatoire": False, "condition_champ": "parents_maries"},
        ]
        groupes = slot_controller.grouper_documents(anciens)
        assert len(groupes) == 1

    def test_l_ancienne_colonne_condition_champ_est_traduite(self):
        ancienne = {"condition_champ": "parents_maries", "condition": None}
        assert slot_controller.condition_de(ancienne) == "parents_maries = oui"
        nouvelle = {"condition_champ": "parents_maries", "condition": "option = polygamie"}
        assert slot_controller.condition_de(nouvelle) == "option = polygamie"


# ---------------------------------------------------------------------------
# Les règles ne sont pas déclenchées au hasard
# ---------------------------------------------------------------------------

class TestDeclenchementDesRegles:
    def test_une_regle_indeterminee_ne_declenche_rien(self):
        # `date_ceremonie` inconnue : on ne bloque jamais une démarche sur une
        # information qu'on n'a pas encore demandée.
        assert regles_demarche.evaluer_regles(REGLES, {}) == []

    def test_seuls_les_effets_demandes_sont_evalues(self):
        slots = {"option": "polygamie", "regime": "communaute", "date_ceremonie": "2020-01-01"}
        blocages = regles_demarche.evaluer_regles(REGLES, slots, effets=(regles_demarche.BLOQUER,))
        assert [v.code for v in blocages] == ["delai_depasse"]
        interdits = regles_demarche.evaluer_regles(REGLES, slots, effets=(regles_demarche.INTERDIRE,))
        assert [v.code for v in interdits] == ["polygamie_sans_communaute"]

    def test_une_regle_cite_ses_champs_et_sa_source(self):
        # Règle 3 du plan maître : aucune règle de droit sans source.
        from services import conditions

        noms_champs = {c["nom_champ"] for c in CHAMPS}
        for regle in REGLES:
            assert regle["source"], f"règle sans source : {regle['code']}"
            inconnus = conditions.champs_utilises(regle["condition"]) - noms_champs
            assert not inconnus, f"règle {regle['code']} : champs inexistants {inconnus}"
