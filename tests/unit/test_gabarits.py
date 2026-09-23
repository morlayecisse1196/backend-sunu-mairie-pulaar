"""
Gabarits à trous : le récapitulatif sort du traducteur (plan maître, étape 3.2).

Le récapitulatif est le moment décisif du dialogue : le citoyen y confirme des
informations qui finiront sur un acte d'état civil, sans pouvoir les lire.
Ce qui est verrouillé ici :

  * une phrase relue une fois n'est plus retraduite à chaque dossier ;
  * les dates sont énoncées en entier, pas lues comme des suites de chiffres ;
  * une valeur manquante EMPÊCHE le rendu — faire confirmer « non renseigné »
    est exactement ce qu'un récapitulatif doit empêcher.
"""
from __future__ import annotations

import pytest

from services import demarche, gabarits

CHAMPS = [
    {"type_demarche": "extrait_naissance", "nom_champ": "nom_enfant", "type_valeur": "texte", "ordre": 10},
    {"type_demarche": "extrait_naissance", "nom_champ": "date_naissance_enfant", "type_valeur": "date", "ordre": 20},
    {"type_demarche": "extrait_naissance", "nom_champ": "commune_naissance", "type_valeur": "texte", "ordre": 30},
    {"type_demarche": "extrait_naissance", "nom_champ": "age_enfant", "type_valeur": "age", "ordre": 40},
    {"type_demarche": "extrait_naissance", "nom_champ": "parents_maries", "type_valeur": "booleen", "ordre": 50},
]

SLOTS = {
    "nom_enfant": "Ibrahima Diallo",
    "date_naissance_enfant": "2026-09-07",
    "commune_naissance": "Ross-Béthio",
    "age_enfant": {"valeur": 7, "unite": "jours"},
    "parents_maries": True,
}

GABARIT_FR = "{nom_enfant}, né le {date_naissance_enfant} à {commune_naissance}. Est-ce exact ?"
GABARIT_PUL = "{nom_enfant}, jibinaaɗo {date_naissance_enfant} e {commune_naissance}. Ko goonga?"


class TestRendu:
    def test_les_trous_sont_remplis_en_francais(self):
        assert gabarits.rendre(GABARIT_FR, SLOTS, CHAMPS) == (
            "Ibrahima Diallo, né le 2026-09-07 à Ross-Béthio. Est-ce exact ?"
        )

    def test_une_date_est_enoncee_en_entier_en_pulaar(self):
        # Le cœur de la tâche : le citoyen doit ENTENDRE la date, pas une
        # suite de chiffres lue au hasard par la synthèse.
        rendu = gabarits.rendre(GABARIT_PUL, SLOTS, CHAMPS, gabarits.PULAAR)
        assert "ñalnde jeeɗiɗi, lewru Sattumbar, hitaande ujunaaje ɗiɗi e noogas e jeegom" in rendu
        assert "2026-09-07" not in rendu

    def test_un_nom_propre_n_est_jamais_traduit(self):
        rendu = gabarits.rendre(GABARIT_PUL, SLOTS, CHAMPS, gabarits.PULAAR)
        assert "Ibrahima Diallo" in rendu and "Ross-Béthio" in rendu

    def test_un_age_et_un_booleen_sont_enonces(self):
        rendu = gabarits.rendre("{age_enfant} / {parents_maries}", SLOTS, CHAMPS, gabarits.PULAAR)
        assert rendu == "balɗe jeeɗiɗi / eey"

    def test_le_meme_trou_peut_revenir_plusieurs_fois(self):
        assert gabarits.rendre("{nom_enfant} e {nom_enfant}", SLOTS, CHAMPS) == (
            "Ibrahima Diallo e Ibrahima Diallo"
        )

    def test_les_trous_sont_listables(self):
        assert gabarits.trous(GABARIT_FR) == [
            "nom_enfant", "date_naissance_enfant", "commune_naissance"
        ]


class TestCeQuiEmpecheLeRendu:
    def test_une_valeur_manquante_empeche_le_rendu(self):
        # Sinon le citoyen confirmerait « né le non renseigné ».
        incomplets = {**SLOTS, "commune_naissance": None}
        assert gabarits.rendre(GABARIT_FR, incomplets, CHAMPS) is None

    def test_une_date_illisible_empeche_le_rendu_en_pulaar(self):
        abimes = {**SLOTS, "date_naissance_enfant": "je ne sais pas"}
        assert gabarits.rendre(GABARIT_PUL, abimes, CHAMPS, gabarits.PULAAR) is None

    def test_un_champ_inexistant_empeche_le_rendu(self):
        # Faute de frappe dans le gabarit : mieux vaut ne rien dire que dire
        # « {nom_enfnat} » à voix haute.
        assert gabarits.rendre("{nom_enfnat} ?", SLOTS, CHAMPS) is None

    def test_un_gabarit_vide_ne_rend_rien(self):
        assert gabarits.rendre("", SLOTS, CHAMPS) is None
        assert gabarits.rendre(None, SLOTS, CHAMPS) is None


class TestRecapitulatif:
    @pytest.fixture
    def base(self, monkeypatch):
        tables = {
            "demarche_champs": CHAMPS,
            "demarche_gabarits": [{
                "type_demarche": "extrait_naissance", "cle": "recapitulatif",
                "francais": GABARIT_FR, "pulaar": GABARIT_PUL, "pulaar_valide": True,
                "contexte": "Relecture obligatoire",
            }],
        }

        def lire(nom, **filtres):
            lignes = tables.get(nom, [])
            for colonne, valeur in filtres.items():
                lignes = [l for l in lignes if l.get(colonne) == valeur]
            return lignes

        monkeypatch.setattr(demarche, "_table", lire)
        demarche.vider_cache()

    def test_un_gabarit_relu_ne_repasse_plus_par_le_traducteur(self, base):
        phrase = demarche.rendre_gabarit("recapitulatif", SLOTS)
        assert phrase.pulaar_pret() is not None
        assert "Ibrahima Diallo" in phrase.pulaar_pret()

    def test_un_gabarit_non_relu_laisse_le_francais_au_traducteur(self, base, monkeypatch):
        monkeypatch.setattr(demarche, "_table", lambda nom, **f: (
            [{"type_demarche": "extrait_naissance", "cle": "recapitulatif", "francais": GABARIT_FR,
              "pulaar": GABARIT_PUL, "pulaar_valide": False, "contexte": ""}]
            if nom == "demarche_gabarits" else (CHAMPS if nom == "demarche_champs" else [])
        ))
        demarche.vider_cache()
        phrase = demarche.rendre_gabarit("recapitulatif", SLOTS)
        assert phrase.francais
        assert phrase.pulaar_pret() is None

    def test_un_gabarit_relu_mais_avec_une_valeur_illisible_retombe_sur_le_francais(self, base):
        # Le gabarit pulaar est relu, mais cette date-là n'est pas énonçable
        # (elle n'a pas été normalisée). Le récapitulatif est quand même dit :
        # le français part au traducteur, comme avant l'étape 3. Ne rien dire
        # du tout serait pire — la relecture ne peut pas être sautée.
        abimes = {**SLOTS, "date_naissance_enfant": "date cassée"}
        phrase = demarche.rendre_gabarit("recapitulatif", abimes)
        assert phrase.francais.startswith("Ibrahima Diallo")
        assert phrase.pulaar_pret() is None

    def test_sans_gabarit_defini_rien_n_est_rendu(self):
        # Le conftest coupe les tables : le moteur retombe alors sur le
        # récapitulatif écrit en dur, qui ne peut pas être sauté.
        assert demarche.rendre_gabarit("recapitulatif", SLOTS) is None


class TestRecapitulatifDuMoteur:
    """Le maillon qui compte : la relecture RG7 passe bien par le gabarit."""

    SLOTS_COMPLETS = {
        **SLOTS,
        "nom_declarant": "Modou Diallo",
        "nom_mere": "Aissatou Ba",
        "date_naissance_mere": "1998-03-12",
    }

    def test_la_relecture_utilise_le_gabarit_relu(self, monkeypatch):
        from temps_reel import moteur

        monkeypatch.setattr(demarche, "_table", lambda nom, **f: (
            [{"type_demarche": "extrait_naissance", "cle": "recapitulatif",
              "francais": GABARIT_FR, "pulaar": GABARIT_PUL, "pulaar_valide": True, "contexte": ""}]
            if nom == "demarche_gabarits" else (CHAMPS if nom == "demarche_champs" else [])
        ))
        demarche.vider_cache()

        phrase = moteur._recapitulatif({"slots": self.SLOTS_COMPLETS, "type_demarche": "extrait_naissance"})

        assert phrase.origine == "gabarit:recapitulatif"
        assert phrase.pulaar_pret() is not None, "relu : la relecture ne passe plus par le traducteur"

    def test_sans_gabarit_la_relecture_a_quand_meme_lieu(self):
        # Le conftest coupe les tables. RG7 est un nœud obligatoire : il ne
        # peut jamais être sauté, même sans gabarit défini.
        from temps_reel import moteur

        phrase = moteur._recapitulatif({"slots": self.SLOTS_COMPLETS, "type_demarche": "extrait_naissance"})

        assert phrase.origine == "recapitulatif:repli"
        assert "Ibrahima Diallo" in phrase.francais
        assert phrase.pulaar_pret() is None


class TestAtelierDeRelecture:
    """
    Un gabarit doit apparaître dans l'atelier, sinon il n'est jamais relu.

    L'atelier lisait le cache des gabarits avec un chargeur qui ne chargeait
    rien : ils n'apparaissaient que si un AUTRE appel les y avait déjà mis.
    Dans un script qui démarre, jamais. Le récapitulatif — la phrase la plus
    importante du dialogue, celle que le citoyen confirme — est resté
    invisible à la relecture, en silence.
    """

    def test_le_recapitulatif_apparait_dans_ce_qui_est_a_relire(self, monkeypatch):
        from services import atelier

        monkeypatch.setattr(demarche, "_table", lambda nom, **f: (
            [{"type_demarche": "extrait_naissance", "cle": "recapitulatif",
              "francais": GABARIT_FR, "pulaar": "", "pulaar_valide": False,
              "contexte": "Relecture obligatoire"}]
            if nom == "demarche_gabarits" else (CHAMPS if nom == "demarche_champs" else [])
        ))
        demarche.vider_cache()  # cache FROID, comme au démarrage d'un script

        identifiants = [p.identifiant for p in atelier.collecter("extrait_naissance")]

        assert "gabarit:recapitulatif" in identifiants

    def test_le_relecteur_est_averti_de_ne_pas_traduire_les_trous(self, monkeypatch):
        # Traduire « {nom_enfant} » rendrait le gabarit inutilisable, et
        # l'erreur ne se verrait qu'au premier récapitulatif d'un vrai dossier.
        from services import atelier

        monkeypatch.setattr(demarche, "_table", lambda nom, **f: (
            [{"type_demarche": "extrait_naissance", "cle": "recapitulatif",
              "francais": GABARIT_FR, "pulaar": "", "pulaar_valide": False, "contexte": ""}]
            if nom == "demarche_gabarits" else []
        ))
        demarche.vider_cache()

        ligne = next(p for p in atelier.collecter("extrait_naissance")
                     if p.identifiant == "gabarit:recapitulatif")

        assert "{nom_champ}" in ligne.contexte
