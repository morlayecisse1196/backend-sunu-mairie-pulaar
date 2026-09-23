"""
Le langage de conditions des démarches (plan maître, étape 2.1).

Ce qui est verrouillé ici, au-delà de la syntaxe : la logique à TROIS valeurs.
Avec deux valeurs, un champ pas encore renseigné rendrait la condition fausse,
et un document conditionné serait sauté avant même que la question dont il
dépend ne soit posée — donc jamais demandé, sans que rien ne le signale.
"""
from __future__ import annotations

from datetime import date

import pytest

from services import conditions
from services.conditions import ConditionInvalide, FAUX, INCONNU, VRAI


class TestLectureDUneCondition:
    @pytest.mark.parametrize(
        "expression",
        [
            "parents_maries",
            "parents_maries = oui",
            "option_matrimoniale = polygamie et regime_biens = communaute",
            "mois_depuis(date_mariage) > 6",
            "non (age_jours(age_enfant) <= 30)",
            "rempli(certificat) ou nom = \"Diallo\"",
            "a = 1 et (b = 2 ou c = 3)",
        ],
    )
    def test_conditions_acceptees(self, expression):
        conditions.analyser(expression)

    @pytest.mark.parametrize(
        "expression",
        [
            "",
            "et parents_maries",
            "parents_maries =",
            "mois_depuis date_mariage > 6",
            "(a = 1",
            "a = 1 b = 2",
            "et = oui",
            "a = 1 ~ b",
        ],
    )
    def test_conditions_refusees(self, expression):
        with pytest.raises(ConditionInvalide):
            conditions.analyser(expression)

    def test_les_champs_cites_sont_listables(self):
        # Sert à détecter une faute de frappe dans une règle : un champ qui
        # n'existe pas dans la démarche rendrait la règle éternellement
        # indéterminée, donc sans effet, et personne ne le verrait.
        assert conditions.champs_utilises(
            "option_matrimoniale = polygamie et mois_depuis(date_mariage) > 6"
        ) == {"option_matrimoniale", "date_mariage"}


class TestTroisValeurs:
    def test_un_champ_absent_est_indetermine_jamais_faux(self):
        assert conditions.evaluer("parents_maries", {}) == INCONNU
        assert conditions.evaluer("parents_maries = oui", {}) == INCONNU

    def test_une_condition_absente_vaut_vrai(self):
        # Pas de condition = l'étape s'applique toujours.
        assert conditions.evaluer(None, {}) == VRAI
        assert conditions.evaluer("   ", {}) == VRAI

    def test_un_champ_rempli_tranche(self):
        assert conditions.evaluer("parents_maries", {"parents_maries": True}) == VRAI
        assert conditions.evaluer("parents_maries", {"parents_maries": False}) == FAUX

    def test_et_conclut_faux_meme_avec_un_inconnu(self):
        # Une seule branche fausse suffit : inutile d'attendre les autres.
        assert conditions.evaluer("a = 1 et b = 2", {"a": 9}) == FAUX
        assert conditions.evaluer("a = 1 et b = 2", {"a": 1}) == INCONNU

    def test_ou_conclut_vrai_meme_avec_un_inconnu(self):
        assert conditions.evaluer("a = 1 ou b = 2", {"a": 1}) == VRAI
        assert conditions.evaluer("a = 1 ou b = 2", {"a": 9}) == INCONNU

    def test_non_laisse_passer_l_indetermine(self):
        assert conditions.evaluer("non a", {}) == INCONNU
        assert conditions.evaluer("non a", {"a": True}) == FAUX
        assert conditions.evaluer("non a", {"a": False}) == VRAI

    def test_rempli_tranche_toujours(self):
        # Seule fonction qui répond sur un champ absent : c'est son objet.
        assert conditions.evaluer("rempli(certificat)", {}) == FAUX
        assert conditions.evaluer("rempli(certificat)", {"certificat": "x"}) == VRAI

    def test_une_condition_mal_ecrite_ne_casse_pas_le_dialogue(self):
        # Elle est journalisée (services/conditions.py) mais ne lève pas :
        # une faute de saisie côté admin ne doit pas couper un citoyen.
        assert conditions.evaluer("a = = 1", {"a": 1}) == INCONNU


class TestComparaisons:
    def test_texte_insensible_a_la_casse_et_aux_espaces(self):
        slots = {"option_matrimoniale": " Polygamie "}
        assert conditions.evaluer("option_matrimoniale = polygamie", slots) == VRAI

    def test_texte_entre_guillemets_pour_les_valeurs_composees(self):
        assert conditions.evaluer('commune = "Ross-Béthio"', {"commune": "Ross-Béthio"}) == VRAI

    def test_nombres_compares_comme_des_nombres(self):
        assert conditions.evaluer("nombre_epouses > 2", {"nombre_epouses": 10}) == VRAI

    def test_types_incomparables_restent_indetermines(self):
        # Mieux vaut ne pas trancher que trancher au hasard.
        assert conditions.evaluer("nom > 3", {"nom": "Diallo"}) == INCONNU


class TestDelais:
    UN_JOUR = date(2026, 9, 19)

    def test_mois_revolus_et_pas_une_division_par_trente(self):
        # Six mois civils du 31 janvier, c'est le 31 juillet — pas 180 jours.
        slots = {"date_mariage": "2026-01-31"}
        assert conditions.evaluer("mois_depuis(date_mariage) > 6", slots, date(2026, 7, 30)) == FAUX
        assert conditions.evaluer("mois_depuis(date_mariage) > 6", slots, date(2026, 8, 1)) == VRAI

    def test_le_delai_expire_le_lendemain_du_sixieme_mois(self):
        # Le jour même des six mois, le délai n'est pas encore dépassé ; le
        # lendemain, il l'est. Un modèle en mois ENTIERS aurait laissé passer
        # un dossier hors délai pendant presque un mois de plus.
        slots = {"date_mariage": "2026-03-15"}
        assert conditions.evaluer("mois_depuis(date_mariage) > 6", slots, date(2026, 9, 15)) == FAUX
        assert conditions.evaluer("mois_depuis(date_mariage) > 6", slots, date(2026, 9, 16)) == VRAI
        assert conditions.evaluer("mois_depuis(date_mariage) >= 6", slots, date(2026, 9, 15)) == VRAI

    def test_annees_depuis_pour_le_delai_d_un_an_du_deces(self):
        slots = {"date_deces": "2025-09-19"}
        assert conditions.evaluer("annees_depuis(date_deces) >= 1", slots, date(2026, 9, 18)) == FAUX
        assert conditions.evaluer("annees_depuis(date_deces) >= 1", slots, date(2026, 9, 19)) == VRAI

    def test_jours_depuis(self):
        assert conditions.evaluer("jours_depuis(d) > 30", {"d": "2026-08-01"}, self.UN_JOUR) == VRAI

    def test_une_date_illisible_reste_indeterminee(self):
        assert conditions.evaluer("mois_depuis(d) > 6", {"d": "je ne sais pas"}) == INCONNU

    def test_age_jours_lit_un_champ_de_type_age(self):
        # Le champ `age` est stocké {"valeur": ..., "unite": ...} : sans cette
        # fonction, la règle des cas légaux ne pourrait pas sortir du code.
        slots = {"age_enfant": {"valeur": 2, "unite": "mois"}}
        assert conditions.evaluer("age_jours(age_enfant) > 30", slots) == VRAI
        assert conditions.evaluer("age_jours(age_enfant) > 365", slots) == FAUX

    def test_age_jours_sur_une_unite_inconnue_reste_indetermine(self):
        assert conditions.evaluer("age_jours(a) > 30", {"a": {"valeur": 2, "unite": "lunes"}}) == INCONNU
