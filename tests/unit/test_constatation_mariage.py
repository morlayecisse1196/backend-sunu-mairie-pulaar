"""
Constatation de mariage (plan maître, étape 5.2, migration 027).

Ces tests LISENT la migration et font tourner le vrai moteur dessus : une
démarche décrite en base doit se dérouler sans une ligne de code en plus.
C'est aussi le seul moyen de vérifier la migration avant de l'appliquer —
une condition mal écrite s'y voit, pas en relisant du SQL.

Ce qui est verrouillé ici :

  * la démarche est reconnue quand le citoyen parle de mariage, et le
    dialogue démarre CELLE-LÀ, pas l'extrait de naissance ;
  * le mariage de plus de six mois arrête la démarche et oriente vers le
    tribunal, au lieu de laisser constituer un dossier qui sera rejeté ;
  * polygamie et communauté des biens ne peuvent pas être choisies ensemble ;
  * la dispense d'âge n'est demandée que si l'un des époux était mineur ;
  * toutes les règles restent marquées « hypothèse » tant qu'un officier
    d'état civil ne les a pas confirmées.
"""
from __future__ import annotations

import pathlib
import re
from datetime import date, timedelta

import pytest

from services import demarche, editeur, regles_demarche, simulateur

SQL = (pathlib.Path(__file__).parents[2] / "migrations" / "027_constatation_mariage.sql").read_text(encoding="utf-8")
T = "constatation_mariage"

_TEXTE = r"(?:null|'(?:[^']|'')*')"


def _texte(brut: str):
    return None if brut == "null" else brut[1:-1].replace("''", "'")


def _tableau(brut: str) -> list[str]:
    return [_texte(m) for m in re.findall(r"'(?:[^']|'')*'", brut)]


CHAMPS = [
    {"type_demarche": T, "ordre": int(ordre), "nom_champ": nom, "type_valeur": type_valeur,
     "question": _texte(question), "regle_validation": _texte(regle),
     "obligatoire": obligatoire == "true", "condition": _texte(condition),
     "relances": _tableau(relances), "question_pulaar": None, "pulaar_valide": False,
     "relances_pulaar": [], "relances_pulaar_valide": []}
    for ordre, nom, type_valeur, question, regle, obligatoire, condition, relances in re.findall(
        rf"\('constatation_mariage',\s*(\d+),\s*'(\w+)',\s*'(\w+)',\s*({_TEXTE}),\s*({_TEXTE}),\s*"
        rf"(true|false),\s*({_TEXTE}),\s*array\[((?:[^\]])*)\]", SQL)
]

DOCUMENTS = [
    {"type_demarche": T, "ordre": int(ordre), "type_document": nom, "obligatoire": obligatoire == "true",
     "condition": _texte(condition), "apres_champ": _texte(apres), "message_demande": _texte(message),
     "messages_rappel": _tableau(rappels), "groupe": None, "message_demande_pulaar": None,
     "pulaar_valide": False, "messages_rappel_pulaar": [], "messages_rappel_pulaar_valide": []}
    for ordre, nom, obligatoire, condition, apres, message, rappels in re.findall(
        rf"\('constatation_mariage',\s*(\d+),\s*'(\w+)',\s*(true|false),\s*({_TEXTE}),\s*({_TEXTE}),\s*"
        rf"({_TEXTE}),\s*array\[((?:[^\]])*)\]", SQL)
]

_SUITE = r"(?:'(?:[^']|'')*'\s*)+"


def _concatene(brut: str) -> str:
    """Des littéraux SQL adjacents sur plusieurs lignes ne font qu'un texte."""
    return "".join(_texte(m) for m in re.findall(r"'(?:[^']|'')*'", brut))


REGLES = [
    {"type_demarche": T, "code": code, "ordre": int(ordre), "condition": _texte(condition), "effet": effet,
     "champ_concerne": _texte(champ), "message": _concatene(message), "source": _concatene(source),
     "hypothese": hypothese == "true"}
    for code, ordre, condition, effet, champ, message, source, hypothese in re.findall(
        rf"\('constatation_mariage',\s*'(\w+)',\s*(\d+),\s*({_TEXTE}),\s*'(bloquer|interdire)',\s*({_TEXTE}),\s*"
        rf"({_SUITE}),\s*({_SUITE}),\s*(true|false)\)", SQL)
]

GABARIT = {"type_demarche": T, "cle": "recapitulatif", "pulaar": None, "pulaar_valide": False,
           "francais": re.search(r"values \('constatation_mariage', 'recapitulatif',\s*((?:'(?:[^']|'')*'\s*)+),",
                                 SQL).group(1)}
GABARIT["francais"] = "".join(_texte(m) for m in re.findall(r"'(?:[^']|'')*'", GABARIT["francais"]))

_DEF = re.search(
    rf"values \('constatation_mariage', ('(?:[^']|'')*'),\s*array\[([^\]]*)\],\s*(true|false), ({_TEXTE})\)", SQL)

DEFINITION = {
    "type_demarche": T, "libelle": _texte(_DEF.group(1)), "mots_cles": _tableau(_DEF.group(2)),
    "traitable": _DEF.group(3) == "true", "champ_age": _texte(_DEF.group(4)), "version": 1,
}

TABLES = {
    "demarche_definitions": [DEFINITION], "demarche_champs": CHAMPS, "demarche_documents": DOCUMENTS,
    "demarche_regles": REGLES, "demarche_gabarits": [GABARIT],
    "demarche_cas": [{"type_demarche": T, "code": "constatation_en_mairie", "ordre": 10,
                      "condition": None, "libelle": "Constatation recevable en mairie"}],
}

AUJOURDHUI = date(2026, 9, 22)


@pytest.fixture(autouse=True)
def base(monkeypatch):
    def lire(nom, **filtres):
        return [l for l in TABLES.get(nom, []) if all(l.get(c) == v for c, v in filtres.items())]
    monkeypatch.setattr(demarche, "_table", lire)
    demarche.vider_cache()


def _scenario(**retouches):
    reponses = {c["nom_champ"]: "Ibrahima Diallo" for c in CHAMPS if c["type_valeur"] == "texte"}
    reponses.update({
        "date_naissance_epoux": "1990-04-12", "date_naissance_epouse": "1995-06-30",
        "date_celebration": (AUJOURDHUI - timedelta(days=60)).isoformat(),
        "option_matrimoniale": "monogamie", "regime_matrimonial": "communaute",
    })
    reponses.update({d["type_document"]: True for d in DOCUMENTS})
    reponses.update(retouches)
    return reponses


def _jouer(**retouches):
    return simulateur.jouer(_scenario(**retouches), T, aujourdhui=AUJOURDHUI)


class TestLaMigrationSeLit:
    def test_les_questions_ont_ete_relues(self):
        assert len(CHAMPS) == 24
        assert [c["nom_champ"] for c in CHAMPS][:2] == ["prenoms_epoux", "nom_epoux"]

    def test_les_pieces_et_les_regles_aussi(self):
        assert len(DOCUMENTS) == 7
        assert {r["code"] for r in REGLES} == {"delai_six_mois", "polygamie_sans_communaute"}


class TestParcours:
    def test_un_mariage_recent_va_jusqu_au_bout(self):
        rapport = _jouer()
        assert rapport.termine, rapport.arret
        assert rapport.cas == "constatation_en_mairie"

    def test_les_deux_epoux_et_les_temoins_sont_demandes(self):
        poses = [t.cle for t in _jouer().tours if t.genre == simulateur.QUESTION]
        for nom in ("prenoms_epoux", "prenoms_epouse", "nom_temoin_1", "nom_temoin_2"):
            assert nom in poses

    def test_le_recapitulatif_relit_le_mariage(self):
        recap = next(t for t in _jouer().tours if t.genre == simulateur.RECAPITULATIF).dit
        assert "célébré le" in recap and "Les témoins sont" in recap

    def test_le_scenario_type_de_l_editeur_passe(self):
        scenario = simulateur.scenario_type(T, aujourdhui=AUJOURDHUI)
        assert simulateur.jouer(scenario, T, aujourdhui=AUJOURDHUI).termine


class TestReglesDeDroit:
    def test_passe_six_mois_la_demarche_s_arrete(self):
        # Constituer le dossier quand même ferait perdre une heure au citoyen
        # pour un rejet certain.
        rapport = _jouer(date_celebration=(AUJOURDHUI - timedelta(days=210)).isoformat())
        assert not rapport.termine
        blocage = next(t for t in rapport.tours if t.genre == simulateur.BLOCAGE)
        assert "tribunal" in blocage.dit.lower()

    def test_juste_avant_six_mois_elle_continue(self):
        assert _jouer(date_celebration=(AUJOURDHUI - timedelta(days=150)).isoformat()).termine

    def test_polygamie_et_communaute_des_biens_sont_incompatibles(self):
        regle = next(r for r in REGLES if r["code"] == "polygamie_sans_communaute")
        violations = regles_demarche.evaluer_regles(
            [regle], {"option_matrimoniale": "polygamie_2", "regime_matrimonial": "communaute"},
            effets=(regles_demarche.INTERDIRE,))
        assert [v.champ for v in violations] == ["regime_matrimonial"]

    def test_la_polygamie_avec_separation_des_biens_passe(self):
        regle = next(r for r in REGLES if r["code"] == "polygamie_sans_communaute")
        assert regles_demarche.evaluer_regles(
            [regle], {"option_matrimoniale": "polygamie_2", "regime_matrimonial": "separation_des_biens"},
            effets=(regles_demarche.INTERDIRE,)) == []

    def test_la_monogamie_garde_le_choix_du_regime(self):
        regle = next(r for r in REGLES if r["code"] == "polygamie_sans_communaute")
        assert regles_demarche.evaluer_regles(
            [regle], {"option_matrimoniale": "monogamie", "regime_matrimonial": "communaute"},
            effets=(regles_demarche.INTERDIRE,)) == []

    def test_toutes_les_regles_restent_des_hypotheses(self):
        # Règle 3 du plan maître : aucune règle de droit affirmée sans
        # confirmation d'un officier d'état civil.
        assert all(r["hypothese"] for r in REGLES)
        assert all(len(r["source"]) > 30 for r in REGLES)


class TestDispenseDAge:
    def test_demandee_quand_l_epouse_est_mineure(self):
        rapport = _jouer(date_naissance_epouse=(AUJOURDHUI - timedelta(days=365 * 15)).isoformat())
        assert "dispense_age" in [t.cle for t in rapport.tours if t.genre == simulateur.PIECE]

    def test_pas_demandee_a_deux_majeurs(self):
        assert "dispense_age" not in [t.cle for t in _jouer().tours if t.genre == simulateur.PIECE]


class TestSanteDeLaDemarche:
    def test_aucun_probleme_bloquant(self):
        problemes = editeur._verifier(DEFINITION, CHAMPS, DOCUMENTS, TABLES["demarche_cas"], REGLES, [GABARIT])
        assert [p.en_dict() for p in problemes if p.gravite == editeur.BLOQUANT] == []

    @pytest.mark.parametrize("nom", [
        # Ce que le modèle recopie depuis la liste des démarches menables,
        # ou ce que la recherche documentaire remonte comme nom de démarche.
        "Constatation de mariage",
        "Certificat de mariage constaté",
        "constatation de mariage à la mairie",
    ])
    def test_le_dialogue_la_reconnait_a_son_nom(self, nom):
        trouvee = demarche.reconnaitre_demarche(nom)
        assert trouvee is not None and trouvee.type_demarche == T

    def test_elle_n_est_pas_confondue_avec_une_autre(self):
        assert demarche.reconnaitre_demarche("Extrait de naissance") is None

    def test_une_demarche_sans_nom_est_bloquante(self):
        # Le nom est ce que le modèle recopie pour dire quelle démarche
        # commencer : sans lui, elle ne peut pas être proposée.
        problemes = editeur._verifier({**DEFINITION, "libelle": " "}, CHAMPS, DOCUMENTS,
                                      TABLES["demarche_cas"], REGLES, [GABARIT])
        assert any(p.gravite == editeur.BLOQUANT and "pas de nom" in p.message for p in problemes)
