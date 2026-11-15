"""
Les dates écrites en toutes lettres sur les actes (étape 5.5).

Ce fichier est volontairement exhaustif : cette conversion sort sur un acte
d'état civil qu'un officier signe. Une erreur ici n'est pas un affichage bancal,
c'est un acte faux. Les cas piégeux du français — 71, 80, 81, 91, 200, 1000,
le premier du mois — sont donc tous écrits, pas échantillonnés.

Les valeurs de référence viennent des trois documents réels fournis par le
porteur du projet : « Trente et un Mai mille neuf cent quatre-vingt-quatre »,
« Douze Février mille neuf cent quatre-vingt-treize », « Onze Septembre l'an
deux mille vingt », « le neuf octobre deux mil quatre ».
"""
import pytest

from services.dates_en_lettres import MAXIMUM, date_en_lettres, nombre_en_lettres


class TestLesNombres:
    @pytest.mark.parametrize("nombre,attendu", [
        (0, "zéro"), (1, "un"), (7, "sept"), (11, "onze"), (16, "seize"),
        (17, "dix-sept"), (18, "dix-huit"), (19, "dix-neuf"), (20, "vingt"),
        (21, "vingt et un"), (22, "vingt-deux"), (30, "trente"),
        (31, "trente et un"), (40, "quarante"), (50, "cinquante"),
        (60, "soixante"), (61, "soixante et un"),
    ])
    def test_jusqu_a_soixante_dix(self, nombre, attendu):
        assert nombre_en_lettres(nombre) == attendu

    @pytest.mark.parametrize("nombre,attendu", [
        (70, "soixante-dix"),
        (71, "soixante et onze"),   # et non « soixante-onze »
        (72, "soixante-douze"),
        (77, "soixante-dix-sept"),
        (79, "soixante-dix-neuf"),
    ])
    def test_les_soixante_dix(self, nombre, attendu):
        assert nombre_en_lettres(nombre) == attendu

    @pytest.mark.parametrize("nombre,attendu", [
        (80, "quatre-vingts"),      # seul : prend un s
        (81, "quatre-vingt-un"),    # suivi : perd le s, et pas de « et »
        (84, "quatre-vingt-quatre"),
        (90, "quatre-vingt-dix"),
        (91, "quatre-vingt-onze"),
        (93, "quatre-vingt-treize"),
        (99, "quatre-vingt-dix-neuf"),
    ])
    def test_les_quatre_vingts(self, nombre, attendu):
        assert nombre_en_lettres(nombre) == attendu

    @pytest.mark.parametrize("nombre,attendu", [
        (100, "cent"),              # jamais « un cent »
        (101, "cent un"),
        (180, "cent quatre-vingts"),
        (200, "deux cents"),        # seul : prend un s
        (201, "deux cent un"),      # suivi : perd le s
        (999, "neuf cent quatre-vingt-dix-neuf"),
    ])
    def test_les_centaines(self, nombre, attendu):
        assert nombre_en_lettres(nombre) == attendu

    @pytest.mark.parametrize("annee,attendu", [
        (1000, "mille"),            # jamais « un mille »
        (1930, "mille neuf cent trente"),
        (1984, "mille neuf cent quatre-vingt-quatre"),
        (1993, "mille neuf cent quatre-vingt-treize"),
        (1997, "mille neuf cent quatre-vingt-dix-sept"),
        (2000, "deux mille"),
        (2004, "deux mille quatre"),
        (2020, "deux mille vingt"),
        (2023, "deux mille vingt-trois"),
        (2026, "deux mille vingt-six"),
    ])
    def test_les_annees_des_documents_reels(self, annee, attendu):
        assert nombre_en_lettres(annee) == attendu

    def test_mille_est_invariable(self):
        # « deux mille », jamais « deux milles ».
        assert not nombre_en_lettres(2000).endswith("milles")

    @pytest.mark.parametrize("valeur", [-1, MAXIMUM + 1, 1.5, "2020", None, True])
    def test_ce_qui_n_est_pas_un_nombre_d_acte_est_refuse(self, valeur):
        # Y compris True, que Python compterait volontiers pour 1.
        with pytest.raises(ValueError):
            nombre_en_lettres(valeur)


class TestLesDates:
    @pytest.mark.parametrize("iso,attendu", [
        ("2020-09-11", "onze septembre deux mille vingt"),
        ("1984-05-31", "trente et un mai mille neuf cent quatre-vingt-quatre"),
        ("1993-02-12", "douze février mille neuf cent quatre-vingt-treize"),
        ("2004-10-09", "neuf octobre deux mille quatre"),
        ("2023-05-07", "sept mai deux mille vingt-trois"),
        ("1997-08-19", "dix-neuf août mille neuf cent quatre-vingt-dix-sept"),
    ])
    def test_les_dates_des_documents_reels(self, iso, attendu):
        assert date_en_lettres(iso) == attendu

    def test_le_premier_du_mois_n_est_pas_un(self):
        # « le premier janvier », jamais « le un janvier ».
        assert date_en_lettres("2024-01-01") == "premier janvier deux mille vingt-quatre"
        assert date_en_lettres("2024-01-02") == "deux janvier deux mille vingt-quatre"

    @pytest.mark.parametrize("mois,nom", [
        (1, "janvier"), (2, "février"), (4, "avril"), (8, "août"),
        (9, "septembre"), (12, "décembre"),
    ])
    def test_les_mois_sont_accentues(self, mois, nom):
        assert date_en_lettres(f"2020-{mois:02d}-15") == f"quinze {nom} deux mille vingt"

    def test_un_horodatage_complet_est_accepte(self):
        # Certaines valeurs remontent de la base sous cette forme.
        assert date_en_lettres("2020-09-11T00:00:00+00:00") == "onze septembre deux mille vingt"

    @pytest.mark.parametrize("valeur", [
        "11/09/2020",        # format français, pas ISO
        "2020-13-01",        # mois inexistant
        "2020-02-30",        # jour inexistant
        "hier", "", None, 42, "2020-09",
    ])
    def test_une_date_illisible_ne_produit_rien(self, valeur):
        # None fait échouer la génération sur un champ manquant, ce qui se voit
        # et se corrige. Une date fausse, elle, se signe.
        assert date_en_lettres(valeur) is None

    def test_aucune_date_n_est_arrondie_ou_devinee(self):
        # Une valeur partielle ne doit pas être complétée au hasard.
        assert date_en_lettres("2020-09-00") is None
