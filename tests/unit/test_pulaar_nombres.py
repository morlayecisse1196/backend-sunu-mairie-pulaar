"""
Nombres, dates et âges en pulaar, sans modèle (plan maître, étape 3.2).

Ces valeurs finissent sur un acte d'état civil : le citoyen les confirme à
l'oreille, sans pouvoir les lire. Une date mal énoncée est une date mal
confirmée.
"""
from __future__ import annotations

from datetime import date

import pytest

from services import pulaar_nombres as n


class TestNombres:
    @pytest.mark.parametrize("valeur,attendu", [
        (0, "meere"),
        (1, "go'o"),
        (7, "jeeɗiɗi"),
        (10, "sappo"),
        (11, "sappo e go'o"),
        (19, "sappo e jeenayi"),
        (20, "noogas"),
        (21, "noogas e go'o"),
        (30, "cappanɗe tati"),
        (45, "cappanɗe nayi e joyi"),
        (99, "cappanɗe jeenayi e jeenayi"),
        (100, "teemedere"),
        (101, "teemedere e go'o"),
        (200, "teemedde ɗiɗi"),
        (365, "teemedde tati e cappanɗe jeegom e joyi"),
        (500, "teemedde joyi"),
        (1000, "ujunere"),
        (2026, "ujunaaje ɗiɗi e noogas e jeegom"),
        (1998, "ujunere e teemedde jeenayi e cappanɗe jeenayi e jeetati"),
    ])
    def test_enonce(self, valeur, attendu):
        assert n.nombre(valeur) == attendu

    def test_le_corpus_confirme_les_centaines(self):
        # « Vignette nden ko teemedde ɗiɗi haa teemedde joy FCFA » —
        # dataset_ful_fr_ameliorer.jsonl, pour « de 200 à 500 FCFA ».
        assert n.nombre(200).startswith("teemedde ɗiɗi")
        assert n.nombre(500).startswith("teemedde joyi")

    def test_un_nombre_trop_grand_n_est_pas_approxime(self):
        # Mieux vaut des chiffres qu'une énonciation inventée.
        assert n.nombre(12_345_678) == "12345678"

    def test_un_numero_s_epelle_au_lieu_de_se_dire(self):
        # Un numéro de suivi n'est pas une quantité : personne ne dit
        # « quatre mille cinquante-deux » pour lire un identifiant.
        assert n.chiffre_par_chiffre("407") == "nayi meere jeeɗiɗi"
        assert n.chiffre_par_chiffre("SN-2026") == "ɗiɗi meere ɗiɗi jeegom"


class TestDates:
    def test_une_date_est_dite_en_entier(self):
        assert n.date_pulaar("2026-09-07") == (
            "ñalnde jeeɗiɗi, lewru Sattumbar, hitaande ujunaaje ɗiɗi e noogas e jeegom"
        )

    def test_un_objet_date_est_accepte(self):
        assert n.date_pulaar(date(1998, 3, 12)).startswith("ñalnde sappo e ɗiɗi, lewru Marse")

    def test_une_date_illisible_ne_produit_rien(self):
        # `None` laisse l'appelant décider, plutôt que de faire dire n'importe
        # quoi au citoyen.
        assert n.date_pulaar("je ne sais pas") is None
        assert n.date_pulaar(None) is None


class TestAges:
    @pytest.mark.parametrize("valeur,unite,attendu", [
        (7, "jours", "balɗe jeeɗiɗi"),
        (1, "jours", "ñalawma go'o"),
        (3, "mois", "lebbi tati"),
        (1, "mois", "lewru go'o"),
        (4, "ans", "duuɓi nayi"),
        (1, "ans", "hitaande go'o"),
        (2, "semaines", "jonte ɗiɗi"),
    ])
    def test_enonce(self, valeur, unite, attendu):
        assert n.age_pulaar({"valeur": valeur, "unite": unite}) == attendu

    def test_le_corpus_confirme_le_pluriel_des_mois(self):
        # « lebbi tati » apparaît tel quel dans le corpus de traduction.
        assert n.age_pulaar({"valeur": 3, "unite": "mois"}) == "lebbi tati"

    def test_une_unite_inconnue_ne_produit_rien(self):
        assert n.age_pulaar({"valeur": 2, "unite": "lunes"}) is None
        assert n.age_pulaar({"valeur": None, "unite": "mois"}) is None
        assert n.age_pulaar("7 jours") is None


class TestMontantsEtBooleens:
    def test_un_montant_porte_sa_monnaie(self):
        assert n.montant_pulaar(200) == "teemedde ɗiɗi faraŋ seefaa"

    def test_un_montant_illisible_ne_produit_rien(self):
        assert n.montant_pulaar("beaucoup") is None

    def test_oui_et_non(self):
        assert n.booleen_pulaar(True) == "eey"
        assert n.booleen_pulaar(False) == "alaa"
