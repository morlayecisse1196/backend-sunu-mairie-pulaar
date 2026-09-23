"""
Le déclarant n'est pas toujours le père (étape 5.1, option C, migration 026).

Le dialogue demandait « Êtes-vous mariés, elle et vous ? » et récapitulait
« enfant de <déclarant> et de <mère> » : une grand-mère qui déclare se voyait
demander si elle était mariée à la mère, puis confirmer qu'elle était parent.

Les lignes ci-dessous reprennent la migration ; le premier test vérifie
qu'elles n'ont pas divergé.
"""
from __future__ import annotations

import pathlib
from datetime import date

import pytest

from services import demarche, editeur, simulateur

MIGRATION = (pathlib.Path(__file__).parents[2] / "migrations" / "026_declarant_pere.sql").read_text(encoding="utf-8")

T = "extrait_naissance"
QUESTION_PERE = "Êtes-vous le père de l'enfant ?"
QUESTION_NOM_PERE = "Quel est le nom complet du père de l'enfant ?"
QUESTION_MARIES = "Le père et la mère de l'enfant sont-ils mariés ?"
RECAP = ("Je vous relis maintenant tout ce que j'ai noté pour vérifier que c'est correct : "
         "{nom_enfant}, né le {date_naissance_enfant} à {commune_naissance}. "
         "Sa mère est {nom_mere}, née le {date_naissance_mere}. "
         "La déclaration est faite par {nom_declarant}. Est-ce que tout est exact ?")


def _champ(ordre, nom, type_valeur, question, *, obligatoire=True, condition=None, regle=None):
    return {"type_demarche": T, "ordre": ordre, "nom_champ": nom, "type_valeur": type_valeur,
            "question": question, "obligatoire": obligatoire, "condition": condition,
            "regle_validation": regle, "relances": ["?"], "question_pulaar": None,
            "pulaar_valide": False, "relances_pulaar": [], "relances_pulaar_valide": []}


CHAMPS = [
    _champ(10, "nom_enfant", "texte", "Nom de l'enfant ?"),
    _champ(20, "commune_naissance", "texte", "Commune ?"),
    _champ(30, "date_naissance_enfant", "date", "Date ?", regle="passee"),
    _champ(40, "nom_mere", "texte", "Nom de la mère ?"),
    _champ(45, "date_naissance_mere", "date", "Date de la mère ?", regle="passee|avant:date_naissance_enfant"),
    _champ(50, "nom_declarant", "texte", "Votre nom ?"),
    _champ(52, "declarant_est_pere", "booleen", QUESTION_PERE),
    _champ(54, "nom_pere", "texte", QUESTION_NOM_PERE, obligatoire=False, condition="declarant_est_pere = non"),
    _champ(90, "parents_maries", "booleen", QUESTION_MARIES),
]
TABLES = {
    "demarche_definitions": [{"type_demarche": T, "libelle": "Extrait", "version": 1, "traitable": True,
                              "mots_cles": ["extrait de naissance"], "champ_age": None}],
    "demarche_champs": CHAMPS, "demarche_documents": [], "demarche_regles": [],
    "demarche_cas": [{"type_demarche": T, "code": "defaut", "ordre": 10, "condition": None, "libelle": "D"}],
    "demarche_gabarits": [{"type_demarche": T, "cle": "recapitulatif", "francais": RECAP,
                           "pulaar": None, "pulaar_valide": False}],
}

REPONSES = {"nom_enfant": "Awa Diallo", "commune_naissance": "Tambacounda",
            "date_naissance_enfant": "2026-09-01", "nom_mere": "Mariama Ba",
            "date_naissance_mere": "1998-02-03", "nom_declarant": "Fatou Sow", "parents_maries": "oui"}


@pytest.fixture(autouse=True)
def base(monkeypatch):
    def lire(nom, **filtres):
        return [l for l in TABLES.get(nom, []) if all(l.get(c) == v for c, v in filtres.items())]
    monkeypatch.setattr(demarche, "_table", lire)
    demarche.vider_cache()


def _posees(rapport):
    return [t.cle for t in rapport.tours if t.genre == simulateur.QUESTION]


def test_les_lignes_suivent_la_migration():
    for texte in (QUESTION_PERE, QUESTION_NOM_PERE, QUESTION_MARIES):
        assert texte.replace("'", "''") in MIGRATION
    assert "'declarant_est_pere = non'" in MIGRATION
    for morceau in ("Sa mère est {nom_mere}", "La déclaration est faite par {nom_declarant}"):
        assert morceau in MIGRATION


def test_le_pere_qui_declare_n_a_pas_a_redonner_son_nom():
    rapport = simulateur.jouer({**REPONSES, "declarant_est_pere": "oui"}, T)
    assert rapport.termine
    assert "nom_pere" not in _posees(rapport)


def test_un_autre_declarant_donne_le_nom_du_pere():
    rapport = simulateur.jouer({**REPONSES, "declarant_est_pere": "non", "nom_pere": "Ousmane Diallo"}, T)
    assert rapport.termine
    assert _posees(rapport).index("nom_pere") == _posees(rapport).index("declarant_est_pere") + 1
    assert rapport.slots["nom_pere"] == "Ousmane Diallo"


def test_le_nom_du_pere_est_facultatif():
    # Père inconnu : l'acte l'admet (prenomPere est facultatif dans le XSD).
    ligne = next(c for c in CHAMPS if c["nom_champ"] == "nom_pere")
    assert ligne["obligatoire"] is False
    assert "false, 'declarant_est_pere = non'" in MIGRATION


def test_le_recapitulatif_ne_fait_plus_du_declarant_un_parent():
    rapport = simulateur.jouer({**REPONSES, "declarant_est_pere": "non", "nom_pere": "Ousmane Diallo"}, T)
    recap = next(t for t in rapport.tours if t.genre == simulateur.RECAPITULATIF).dit
    assert "La déclaration est faite par Fatou Sow" in recap
    assert "enfant de Fatou Sow" not in recap


def test_aucune_question_ne_suppose_que_le_declarant_est_le_pere():
    for champ in CHAMPS:
        assert "elle et vous" not in champ["question"]
    assert "set question = 'Le père et la mère" in MIGRATION


def test_la_relecture_pulaar_des_phrases_reecrites_est_retiree():
    # Le pulaar relu traduisait l'ancienne phrase : il ne traduit plus rien.
    assert MIGRATION.count("pulaar_valide = false") == 2


def test_la_demarche_reste_saine():
    problemes = editeur._verifier(
        TABLES["demarche_definitions"][0], CHAMPS, [], TABLES["demarche_cas"], [],
        TABLES["demarche_gabarits"])
    assert [p for p in problemes if p.gravite == editeur.BLOQUANT] == []


def test_le_scenario_type_passe_sans_retouche():
    scenario = simulateur.scenario_type(T, aujourdhui=date(2026, 9, 22))
    assert simulateur.jouer(scenario, T, aujourdhui=date(2026, 9, 22)).termine
