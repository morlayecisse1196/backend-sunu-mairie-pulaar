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


class TestEnoncerNombres:
    """
    `enoncer_nombres` est la couche qui voit TOUT ce qui part au synthétiseur.

    Le modèle vocal ne sait pas dire un chiffre : les dix caractères sont dans
    son vocabulaire, mais pratiquement jamais vus à l'entraînement. Mesuré sur
    `rnjema-unima/mms-tts-pul-baseline` : « 2026 » produit 0,21 s d'audio,
    « ujunaaje ɗiɗi e noogas e jeegom » en produit 3,09 s. Tout chiffre qui
    franchit cette couche est donc inaudible pour le citoyen.
    """

    def test_un_texte_sans_chiffre_n_est_pas_touche(self):
        assert n.enoncer_nombres("Aucun chiffre ici.") == "Aucun chiffre ici."
        assert n.enoncer_nombres("") == ""

    def test_une_date_iso_est_enoncee(self):
        assert n.enoncer_nombres("jibinaaɗo 2026-09-07 e Dakar") == (
            "jibinaaɗo ñalnde jeeɗiɗi, lewru Sattumbar, "
            "hitaande ujunaaje ɗiɗi e noogas e jeegom e Dakar"
        )

    def test_une_date_francaise_est_enoncee(self):
        assert n.enoncer_nombres("le 07/09/2026").startswith("le ñalnde jeeɗiɗi, lewru Sattumbar")

    # Le préfixe porte son propre espacement : sans séparateur, « ñalnde1967 »
    # n'offre aucune frontière de mot et le motif de date ne s'accroche pas.
    @pytest.mark.parametrize("avant", ["ñalnde ", "nyalnde ", "ÑALNDE ", "ñalnde  "])
    def test_le_jour_n_est_pas_dit_deux_fois(self, avant):
        """
        `date_pulaar` préfixe toujours sa sortie par « ñalnde ». Le traducteur,
        lui, écrit volontiers « ñalnde 1967-10-14 » — le corpus dit « ñalnde
        jibineede » pour « date de naissance », donc le mot précède
        naturellement la date restée en chiffres. Le citoyen entendait alors
        « jour jour quatorze ».

        Les deux graphies de la nasale palatale comptent : « ny » est la même
        lettre écrite autrement, et le modèle emploie les deux.
        """
        dit = n.enoncer_nombres(f"jibinaaɗo {avant}1967-10-14")
        assert "ñalnde ñalnde" not in dit.lower().replace("nyalnde", "ñalnde")
        assert dit.startswith(f"jibinaaɗo {avant}sappo e nayi,")

    def test_un_jour_eloigne_de_la_date_est_conserve(self):
        # « ñalnde jibineede ko ñalnde sappo e ɗiɗi » est correct : le premier
        # « ñalnde » appartient à « date de naissance », le second annonce le
        # quantième. Ne dédoublonner que ce qui est ADJACENT.
        dit = n.enoncer_nombres("ñalnde jibineede ko 1998-03-12")
        assert dit == "ñalnde jibineede ko ñalnde sappo e ɗiɗi, lewru Marse, hitaande " + n.nombre(1998)

    @pytest.mark.parametrize("texte", ["le 31/02/2026", "2026-13-45", "le 00/00/2026"])
    def test_une_date_impossible_reste_intacte(self, texte):
        # Le point de cette passe unique : une règle qui renonce laisse ses
        # chiffres EN PLACE, et aucune règle plus générale ne vient les
        # découper ensuite. Enchaînées, les règles produisaient
        # « cappanɗe tati e go'o/ɗiɗi/ujunaaje... » — une date inventée, le
        # pire résultat possible sur un acte d'état civil.
        assert n.enoncer_nombres(texte) == texte

    @pytest.mark.parametrize("texte,attendu", [
        ("200 francs", "teemedde ɗiɗi faraŋ seefaa"),
        ("200 francs CFA", "teemedde ɗiɗi faraŋ seefaa"),
        ("200 FCFA", "teemedde ɗiɗi faraŋ seefaa"),
        ("200 faraŋ", "teemedde ɗiɗi faraŋ seefaa"),
        ("200 faraŋ seefaa", "teemedde ɗiɗi faraŋ seefaa"),
        ("1 500 FCFA", "ujunere e teemedde joyi faraŋ seefaa"),
    ])
    def test_un_montant_porte_sa_monnaie_une_seule_fois(self, texte, attendu):
        # L'unité ne doit jamais être dite deux fois : « faraŋ seefaa CFA »
        # arriverait si la règle tournait après `orthographe_tts`, qui réécrit
        # déjà « francs » en « faraŋ ». D'où l'ordre de `texte_pour_synthese`.
        assert n.enoncer_nombres(texte) == attendu

    def test_un_montant_trop_grand_est_epele_plutot_que_rendu_en_chiffres(self):
        # `nombre()` rend les chiffres tels quels au-delà d'un million : les
        # laisser passer remettrait le défaut en place.
        dit = n.enoncer_nombres("1500000 francs")
        assert not any(c.isdigit() for c in dit)
        assert dit.endswith(n.MONNAIE)

    def test_un_numero_de_suivi_est_epele_chiffre_par_chiffre(self):
        # Format de `dossiers_repo.generer_numero_suivi`. Les lettres restent
        # groupées : « S M » se dirait comme deux consonnes sans voyelle.
        assert n.enoncer_nombres("SM-2026-000452") == (
            "SM ɗiɗi meere ɗiɗi jeegom meere meere meere nayi joyi ɗiɗi"
        )

    def test_la_ponctuation_autour_d_un_numero_est_conservee(self):
        assert n.enoncer_nombres("ko SM-2026-000452.").endswith("ɗiɗi.")

    @pytest.mark.parametrize("texte,attendu", [
        ("3 mois", "tati mois"),
        ("dossier 1234", "dossier ujunere e teemedde ɗiɗi e cappanɗe tati e nayi"),
    ])
    def test_un_entier_court_est_dit_comme_une_quantite(self, texte, attendu):
        assert n.enoncer_nombres(texte) == attendu

    def test_un_entier_long_est_epele_comme_un_identifiant(self):
        # Au seuil, le basculement : quatre chiffres restent une quantité
        # (une année, un montant), cinq deviennent un identifiant.
        assert n.SEUIL_EPELLATION == 5
        assert n.enoncer_nombres("48219") == "nayi jeetati ɗiɗi go'o jeenayi"
        assert n.enoncer_nombres("2026") == "ujunaaje ɗiɗi e noogas e jeegom"

    @pytest.mark.parametrize("texte,attendu", [
        ("9h30", "waktu jeenayi e minute cappanɗe tati"),
        ("9h00", "waktu jeenayi"),
        ("9:30", "waktu jeenayi e minute cappanɗe tati"),
    ])
    def test_une_heure_est_enoncee(self, texte, attendu):
        assert n.enoncer_nombres(texte) == attendu

    @pytest.mark.parametrize("texte", ["99h99", "30h00"])
    def test_une_heure_impossible_reste_intacte(self, texte):
        assert n.enoncer_nombres(texte) == texte

    def test_aucun_chiffre_ne_franchit_la_couche(self):
        # Le contrat qui résume tout le reste : ce qui sort est audible.
        phrases = (
            "Voilà, votre demande est envoyée. Votre numéro de suivi est SM-2026-000452. "
            "Je vous redis les derniers chiffres un par un : 0, 0, 0, 4, 5, 2.",
            "Aɗa soklii 200 francs CFA e pièce d'identité maa.",
            "Jibinaaɗo 2026-09-07, lewru 3 e hitaande 2026.",
        )
        for phrase in phrases:
            dit = n.enoncer_nombres(phrase)
            assert not any(c.isdigit() for c in dit), dit
