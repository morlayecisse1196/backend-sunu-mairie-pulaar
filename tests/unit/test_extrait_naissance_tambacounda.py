"""
Extrait de naissance : les écarts vus sur l'acte réel de Tambacounda (étape 5.1).

  * l'arrondissement n'apparaît pas sur cet acte : l'exiger faisait échouer
    la génération pour toutes les communes dans le même cas ;
  * le sexe est stocké M/F mais s'imprime en toutes lettres ;
  * le dialogue demande désormais le sexe (champ « choix »), ce qui
    pré-remplit le formulaire du consultant au lieu de le lui faire deviner.
"""
from __future__ import annotations

from datetime import date

import pytest

import dialogue_engine
import document_generator as gen
from prompts import build_prompt_champ_cible, build_schema_champ_cible
from services import editeur, gabarits, simulateur

COMMUNE_SANS_ARRONDISSEMENT = {"region": "Tambacounda", "departement": "Tambacounda", "nom": "Tambacounda",
                               "arrondissement": None}

FORMULAIRE = {
    "numeroActe": "1" * 19, "anneeRegistreLettres": "Deux mille vingt-six", "anneeRegistreChiffres": "2026",
    "numeroRegistreLettres": "Douze", "numeroRegistreChiffres": "12",
    "dateNaissanceLettres": "Premier septembre deux mille vingt-six",
    "prenomEnfant": "Awa", "nomFamilleEnfant": "Diallo", "prenomMere": "Mariama", "nomFamilleMere": "Ba",
    "officierEtatCivil": "Moussa Sow",
}
DOSSIER = {"slots": {"date_naissance_enfant": "2026-09-01", "commune_naissance": "Tambacounda",
                     "sexe_enfant": "feminin"}}


class TestArrondissementFacultatif:
    def test_son_absence_n_empeche_plus_la_generation(self):
        _valeurs, erreurs = gen.resoudre_template(DOSSIER, COMMUNE_SANS_ARRONDISSEMENT, FORMULAIRE, False)
        assert not any("arrondissement" in e for e in erreurs)

    def test_le_document_sans_arrondissement_est_conforme_au_xsd(self):
        valeurs, erreurs = gen.resoudre_template(DOSSIER, COMMUNE_SANS_ARRONDISSEMENT, FORMULAIRE, False)
        assert erreurs == []
        assert gen._valider_xsd(gen._construire_instance_xsd(valeurs, False)) == []

    def test_le_document_n_imprime_pas_un_arrondissement_vide(self):
        valeurs, _ = gen.resoudre_template(DOSSIER, COMMUNE_SANS_ARRONDISSEMENT, FORMULAIRE, False)
        assert "Arrondissement de" not in gen._rendre_html(valeurs, False, "S-1")

    def test_il_reste_imprime_quand_la_commune_en_a_un(self):
        commune = {**COMMUNE_SANS_ARRONDISSEMENT, "arrondissement": "Makacolibantang"}
        valeurs, _ = gen.resoudre_template(DOSSIER, commune, FORMULAIRE, False)
        assert "Arrondissement de Makacolibantang" in gen._rendre_html(valeurs, False, "S-1")
        assert gen._valider_xsd(gen._construire_instance_xsd(valeurs, False)) == []


class TestSexe:
    @pytest.mark.parametrize("saisi, attendu", [
        ("M", "M"), ("m", "M"), ("masculin", "M"), ("Garçon", "M"),
        ("F", "F"), ("feminin", "F"), ("Féminin", "F"), ("fille", "F"),
    ])
    def test_toutes_les_ecritures_donnent_m_ou_f(self, saisi, attendu):
        assert gen.normaliser_sexe(saisi) == attendu

    def test_une_valeur_inconnue_n_est_pas_devinee(self):
        # La validation XSD la refusera : mieux qu'un acte au mauvais sexe.
        assert gen.normaliser_sexe("inconnu") == "inconnu"

    def test_s_imprime_en_toutes_lettres(self):
        valeurs, _ = gen.resoudre_template(DOSSIER, COMMUNE_SANS_ARRONDISSEMENT, FORMULAIRE, False)
        html = gen._rendre_html(valeurs, False, "S-1")
        assert "FÉMININ" in html
        assert "(M ou F)" not in html

    def test_reste_m_ou_f_dans_le_xml(self):
        valeurs, _ = gen.resoudre_template(DOSSIER, COMMUNE_SANS_ARRONDISSEMENT, FORMULAIRE, False)
        assert valeurs["sexe"] == "F"

    def test_la_saisie_du_consultant_l_emporte_sur_le_dialogue(self):
        valeurs, _ = gen.resoudre_template(
            DOSSIER, COMMUNE_SANS_ARRONDISSEMENT, {**FORMULAIRE, "sexe": "M"}, False)
        assert valeurs["sexe"] == "M"

    def test_la_reponse_du_dialogue_pre_remplit_le_formulaire(self):
        champs = dialogue_engine.construire_champs_formulaire("certificat_naissance", {"sexe_enfant": "feminin"})
        sexe = next(c for c in champs if c["nom"] == "sexe")
        assert (sexe["valeur"], sexe["source"]) == ("feminin", "dialogue")

    def test_sans_aucune_source_le_sexe_manque(self):
        dossier = {"slots": {k: v for k, v in DOSSIER["slots"].items() if k != "sexe_enfant"}}
        _, erreurs = gen.resoudre_template(dossier, COMMUNE_SANS_ARRONDISSEMENT, FORMULAIRE, False)
        assert any(e.startswith("sexe") for e in erreurs)


SEXE = {"nom_champ": "sexe_enfant", "type_valeur": "enum", "question": "Garçon ou fille ?",
        "regle_validation": "masculin|feminin", "relances": ["Garçon ou fille ?"], "ordre": 35}


class TestChampChoix:
    def test_le_modele_ne_peut_repondre_qu_une_valeur_autorisee(self):
        # Sans la liste, il répondait « garçon » là où le champ attend
        # « masculin », et une réponse juste était refusée.
        schema = build_schema_champ_cible("enum", "masculin|feminin")
        assert schema["properties"]["valeur"]["enum"] == ["masculin", "feminin", None]

    def test_le_prompt_donne_les_valeurs(self):
        assert "masculin, feminin" in build_prompt_champ_cible(SEXE, "c'est une fille")

    def test_un_texte_reste_libre(self):
        assert "enum" not in build_schema_champ_cible("texte")["properties"]["valeur"]

    def test_le_pulaar_ne_dit_pas_un_mot_francais(self):
        # Sans libellé relu, pas de pulaar : le français repart au traducteur.
        assert gabarits.rendre("{sexe_enfant}", {"sexe_enfant": "feminin"}, [SEXE], gabarits.PULAAR) is None
        # Avec un libellé relu (phrases_systeme, clé `valeur_feminin`), il est dit.
        assert gabarits.rendre(
            "{sexe_enfant}", {"sexe_enfant": "feminin"}, [SEXE], gabarits.PULAAR,
            libelles_pulaar={"feminin": "debbo"},
        ) == "debbo"

    def test_le_francais_ne_dit_pas_un_code_technique(self):
        # Le code brut ressortait tel quel : « Sexe : feminin », et pire
        # « Régime des biens : separation_des_biens », tiret bas compris, lu à
        # voix haute à un citoyen.
        assert gabarits.rendre("{sexe_enfant}", {"sexe_enfant": "feminin"}, [SEXE]) == "Féminin"

    def test_un_choix_sans_liste_est_bloquant(self):
        problemes = editeur._verifier_champs([{**SEXE, "regle_validation": "masculin"}])
        assert any(p.gravite == editeur.BLOQUANT and "au moins deux" in p.message for p in problemes)

    def test_un_choix_avec_liste_est_accepte(self):
        assert not [p for p in editeur._verifier_champs([SEXE]) if p.gravite == editeur.BLOQUANT]

    def test_le_scenario_type_choisit_une_valeur_autorisee(self, monkeypatch):
        monkeypatch.setattr(simulateur.demarche, "champs", lambda *_a, **_k: [SEXE])
        monkeypatch.setattr(simulateur.demarche, "documents", lambda *_a, **_k: [])
        assert simulateur.scenario_type(aujourdhui=date(2026, 9, 22))["sexe_enfant"] == "masculin"


class TestDemarcheSansModele:
    """
    Étape 5.5 : tant qu'une démarche n'a pas son modèle, on ne génère rien.

    Le moteur ne connaissait qu'un jeu de fichiers, celui de l'extrait de
    naissance. Un dossier de mariage lancé dans la génération fabriquait donc
    un extrait de naissance avec des données de mariage.
    """

    def test_une_demarche_sans_modele_refuse_la_generation(self, monkeypatch):
        # Les trois démarches d'état civil ont leur modèle depuis l'étape 5.5 ;
        # le garde-fou protège celles qu'on publiera ensuite.
        monkeypatch.setattr(gen, "get_dossier",
                            lambda _id: {"id": "d1", "type_demarche": "changement_de_nom"})
        monkeypatch.setattr(gen, "get_commune", lambda _id: pytest.fail("génération lancée"))
        with pytest.raises(gen.DemarcheSansModele, match="changement_de_nom"):
            gen.generer_document("d1")

    def test_une_demarche_inconnue_aussi(self, monkeypatch):
        # Une démarche publiée dans l'atelier sans modèle de document ne doit
        # pas se rabattre en silence sur l'extrait de naissance.
        monkeypatch.setattr(gen, "get_dossier",
                            lambda _id: {"id": "d1", "type_demarche": "changement_de_nom"})
        with pytest.raises(gen.DemarcheSansModele):
            gen.generer_document("d1")

    def test_le_message_dit_quoi_faire(self, monkeypatch):
        monkeypatch.setattr(gen, "get_dossier",
                            lambda _id: {"id": "d1", "type_demarche": "changement_de_nom"})
        with pytest.raises(gen.DemarcheSansModele, match="hors de l'application"):
            gen.generer_document("d1")

    def test_l_extrait_de_naissance_passe_toujours(self, monkeypatch):
        # Le garde-fou ne doit pas bloquer la seule démarche qui marche.
        assert "extrait_naissance" in gen.DEMARCHES_AVEC_MODELE
