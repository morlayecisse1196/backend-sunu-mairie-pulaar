"""
Premier jet pulaar des trois démarches (migration 029).

Ce sont des BROUILLONS, écrits pour donner un point de départ à l'atelier.
Ce que les tests garantissent n'est donc pas leur justesse — seule une
personne qui parle pulaar peut en juger, à l'oreille — mais qu'ils ne peuvent
pas faire de dégâts :

  * aucune phrase n'est marquée relue : le dialogue n'en dira aucune ;
  * chaque question des trois démarches a bien reçu un brouillon, sinon
    l'atelier s'ouvrirait sur des lignes vides ;
  * les récapitulatifs gardent EXACTEMENT les mêmes trous que le français —
    un trou traduit ou oublié rend la phrase impossible à dire, au moment
    précis où le citoyen doit confirmer ce qui ira sur un acte ;
  * les relances ne sont remplies que là où il n'y a rien.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from services import gabarits

MIGRATIONS = pathlib.Path(__file__).parents[2] / "migrations"
SQL = (MIGRATIONS / "029_pulaar_brouillon.sql").read_text(encoding="utf-8")

SOURCES = {
    "extrait_naissance": ["025_sexe_enfant.sql", "026_declarant_pere.sql"],
    "constatation_mariage": ["027_constatation_mariage.sql"],
    "declaration_deces": ["028_declaration_deces.sql"],
}


def _champs_declares(type_demarche: str) -> set[str]:
    """Les champs que les migrations de la démarche ont créés."""
    noms: set[str] = set()
    for fichier in SOURCES[type_demarche]:
        texte = (MIGRATIONS / fichier).read_text(encoding="utf-8")
        # Champs créés par la migration...
        noms |= set(re.findall(rf"\(\s*'{type_demarche}',\s*\d+,\s*'(\w+)',\s*'\w+',", texte))
        # ...et champs plus anciens dont elle réécrit la question (026).
        noms |= set(re.findall(r"and nom_champ = '(\w+)'", texte))
    return noms


def _traduits(type_demarche: str) -> set[str]:
    """Les champs auxquels la migration 029 donne un pulaar."""
    if type_demarche == "extrait_naissance":
        return set(re.findall(
            r"update public\.demarche_champs set question_pulaar = '[^']*'\s*\n"
            r"where type_demarche = 'extrait_naissance' and nom_champ = '(\w+)'", SQL))
    bloc = SQL.split(f"where type_demarche = '{type_demarche}'")[0].rsplit("update public.demarche_champs", 1)[-1]
    return set(re.findall(r"when '(\w+)'\s+then", bloc))


def _pulaar_du_gabarit(type_demarche: str) -> str:
    bloc = SQL.split("update public.demarche_gabarits set pulaar =")[
        1 + list(SOURCES).index(type_demarche)]
    bloc = bloc.split("where type_demarche")[0]
    return "".join(m[1:-1].replace("''", "'") for m in re.findall(r"'(?:[^']|'')*'", bloc))


def _francais_du_gabarit(type_demarche: str) -> str:
    if type_demarche == "extrait_naissance":
        texte = (MIGRATIONS / "026_declarant_pere.sql").read_text(encoding="utf-8")
        bloc = texte.split("set francais =")[1].split("where type_demarche")[0]
    else:
        texte = (MIGRATIONS / SOURCES[type_demarche][0]).read_text(encoding="utf-8")
        bloc = texte.split("'recapitulatif',")[1].split("'Relecture avant confirmation")[0]
    return "".join(m[1:-1].replace("''", "'") for m in re.findall(r"'(?:[^']|'')*'", bloc))


class TestRienN_estValide:
    def test_aucune_phrase_n_est_marquee_relue(self):
        # Un brouillon validé serait DIT au citoyen sans que personne ne
        # l'ait entendu.
        assert "pulaar_valide = true" not in SQL
        assert "relances_pulaar_valide" not in SQL

    def test_la_migration_le_dit_en_clair(self):
        assert "BROUILLONS" in SQL and "pulaar_valide" in SQL


class TestCouverture:
    @pytest.mark.parametrize("type_demarche", list(SOURCES))
    def test_chaque_question_a_un_brouillon(self, type_demarche):
        manquants = _champs_declares(type_demarche) - _traduits(type_demarche)
        assert manquants == set(), f"sans pulaar : {sorted(manquants)}"

    @pytest.mark.parametrize("type_demarche", list(SOURCES))
    def test_aucun_brouillon_ne_vise_un_champ_inexistant(self, type_demarche):
        inconnus = _traduits(type_demarche) - _champs_declares(type_demarche)
        assert inconnus == set(), f"champs inconnus : {sorted(inconnus)}"

    def test_les_pieces_des_deux_nouvelles_demarches_sont_couvertes(self):
        for fichier in ("027_constatation_mariage.sql", "028_declaration_deces.sql"):
            texte = (MIGRATIONS / fichier).read_text(encoding="utf-8")
            declares = set(re.findall(r"\('\w+',\s*\d+,\s*'(\w+)',\s*(?:true|false),\s*", texte))
            for type_document in declares:
                assert f"when '{type_document}'" in SQL, type_document


class TestGabarits:
    @pytest.mark.parametrize("type_demarche", list(SOURCES))
    def test_les_trous_sont_identiques_au_francais(self, type_demarche):
        # Traduire « {nom_enfant} » ou en oublier un rend le récapitulatif
        # irrendable : l'agent se tait au moment de la confirmation.
        francais = gabarits.trous(_francais_du_gabarit(type_demarche))
        pulaar = gabarits.trous(_pulaar_du_gabarit(type_demarche))
        assert sorted(pulaar) == sorted(francais)

    @pytest.mark.parametrize("type_demarche", list(SOURCES))
    def test_le_pulaar_n_est_pas_du_francais_recopie(self, type_demarche):
        pulaar = _pulaar_du_gabarit(type_demarche)
        assert "Je vous relis" not in pulaar
        assert "Jooni mi fillitanay" in pulaar


class TestRelances:
    def test_les_relances_viennent_de_la_question(self):
        assert "'Mi faamaani e no fewi. ' || question_pulaar" in SQL
        assert "'En fuɗɗito seese. ' || question_pulaar" in SQL

    def test_une_relance_deja_ecrite_n_est_jamais_ecrasee(self):
        # Sinon un aller-retour de migration effacerait le travail fait à
        # l'atelier entre-temps.
        assert "coalesce(array_length(relances_pulaar, 1), 0) = 0" in SQL

    def test_seules_les_trois_demarches_sont_touchees(self):
        ligne = SQL.split("set relances_pulaar")[1]
        for type_demarche in SOURCES:
            assert f"'{type_demarche}'" in ligne
