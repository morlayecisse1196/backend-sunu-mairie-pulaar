"""
Le certificat de mariage constaté (étape 5.5).

Construit à partir d'un modèle réel fourni par le porteur du projet : commune
d'arrondissement de Fann - Point E - Amitié, centre secondaire ex-Grand Dakar,
registre n° 307. Les données utilisées ici sont inventées — jamais celles des
personnes du document réel.

Avant cette étape, un dossier de mariage complet ne produisait aucun document :
le moteur ne connaissait qu'un jeu de fichiers, celui de l'extrait de
naissance, et refusait (à juste titre) de fabriquer un acte de naissance avec
des données de mariage.
"""
import document_generator as gen
from services import libelles_document as libelles

COMMUNE = {
    "nom": "Fann - Point E - Amitié",
    "region": "Dakar",
    "departement": "Dakar",
    "arrondissement": None,
}

# Ce que le dialogue vocal collecte (migration 027).
SLOTS = {
    "prenoms_epoux": "Amadou", "nom_epoux": "Diallo",
    "date_naissance_epoux": "1984-05-31", "lieu_naissance_epoux": "Thiès",
    "profession_epoux": "Commerçant", "domicile_epoux": "Dakar",
    "nom_pere_epoux": "Samba Diallo", "nom_mere_epoux": "Awa Diallo",
    "prenoms_epouse": "Maty", "nom_epouse": "Sene",
    "date_naissance_epouse": "1993-02-12", "lieu_naissance_epouse": "Dakar",
    "profession_epouse": "Commerçante", "domicile_epouse": "Dakar",
    "nom_pere_epouse": "Ousmane Sene", "nom_mere_epouse": "Tilda Sene",
    "date_celebration": "2020-09-11", "lieu_celebration": "Dakar",
    "option_matrimoniale": "monogamie",
    "regime_matrimonial": "separation_des_biens",
    # Collectés par le dialogue, absents du certificat imprimé.
    "nom_temoin_1": "Ibrahima Fall", "piece_temoin_1": "1234567890123",
    "nom_temoin_2": "Fatou Ndiaye", "piece_temoin_2": "9876543210987",
}

# Ce que le consultant recopie du registre papier.
FORMULAIRE = {
    "numeroRegistreChiffres": "307",
    "anneeRegistreLettres": "deux mille vingt",
    "moisRegistreLettres": "Septembre",
    "heureRegistreLettres": "dix-sept",
    "minuteRegistreLettres": "trente",
    "dateNaissanceEpouxLettres": "Trente et un Mai mille neuf cent quatre-vingt-quatre",
    "dateNaissanceEpouseLettres": "Douze Février mille neuf cent quatre-vingt-treize",
    "dateCelebrationLettres": "Onze Septembre l'an deux mille vingt",
    "dateEnregistrementLettres": "Onze Septembre l'an deux mille vingt",
    "officierEtatCivil": "Oumou SY",
    "typeCentre": "Centre secondaire",
}

DOSSIER = {"id": "d1", "type_demarche": "constatation_mariage",
           "numero_suivi": "S-2020-307", "slots": SLOTS}


def _resoudre(dossier=None, commune=None, formulaire=None):
    return gen.resoudre_template(dossier or DOSSIER, commune or COMMUNE,
                                 formulaire if formulaire is not None else FORMULAIRE,
                                 False)


class TestLeModeleEstChoisiParLaDemarche:
    def test_le_mariage_a_desormais_un_modele(self):
        assert "constatation_mariage" in gen.DEMARCHES_AVEC_MODELE

    def test_un_dossier_de_mariage_lit_le_template_du_mariage(self):
        valeurs, _ = _resoudre()
        # Un champ qui n'existe que dans l'extrait de naissance : s'il
        # apparaissait, c'est le mauvais modèle qui aurait été ouvert.
        assert "prenomEnfant" not in valeurs
        assert valeurs["epouxNomFamille"] == "Diallo"

    def test_une_demarche_sans_modele_ne_resout_rien(self):
        # Les trois démarches d'état civil ont leur modèle ; une démarche
        # publiée plus tard dans l'atelier n'en aura pas tout de suite.
        valeurs, erreurs = gen.resoudre_template(
            {"type_demarche": "changement_de_nom", "slots": SLOTS}, COMMUNE, FORMULAIRE, False)
        # Ni valeurs inventées, ni fausse erreur : c'est `generer_document` qui
        # refuse, avec un message qui dit quoi faire.
        assert (valeurs, erreurs) == ({}, [])


class TestLesDeuxEpouxNeSeMelangentPas:
    """
    Le mari et l'épouse portent les MÊMES noms d'éléments dans le XSD
    (`prenoms`, `nomFamille`, ...). Sans clé distincte, la seconde personne
    écrase la première : le certificat sortirait avec deux fois le même nom,
    sans la moindre erreur. C'est le défaut le plus dangereux de ce modèle,
    parce qu'il produit un document d'apparence parfaite.
    """

    def test_chacun_garde_son_nom(self):
        valeurs, _ = _resoudre()
        assert valeurs["epouxPrenoms"] == "Amadou"
        assert valeurs["epousePrenoms"] == "Maty"

    def test_chacun_garde_sa_date_de_naissance(self):
        valeurs, _ = _resoudre()
        assert valeurs["epouxDateNaissance"] == "1984-05-31"
        assert valeurs["epouseDateNaissance"] == "1993-02-12"

    def test_chacun_garde_ses_parents(self):
        valeurs, _ = _resoudre()
        assert valeurs["epouxNomPere"] == "Samba Diallo"
        assert valeurs["epouseNomPere"] == "Ousmane Sene"

    def test_le_document_imprime_bien_deux_personnes_differentes(self):
        valeurs, _ = _resoudre()
        html = gen._rendre_html(valeurs, False, "S-1", gen.MODELES["constatation_mariage"])
        assert "Amadou Diallo" in html
        assert "Maty Sene" in html


class TestCeQueLeConsultantDoitEncoreSaisir:
    def test_un_dossier_complet_cote_dialogue_ne_suffit_pas(self):
        # Le numéro du registre et le nom du signataire viennent du registre
        # papier : personne ne peut les deviner.
        _, erreurs = _resoudre(formulaire={})
        manquants = {e.split(" ")[0] for e in erreurs}
        assert "numeroRegistreChiffres" in manquants
        assert "officierEtatCivil" in manquants

    def test_les_dates_en_lettres_n_ont_plus_besoin_du_consultant(self):
        # Écrites depuis la date du dialogue : c'est une dizaine de mentions
        # en moins à recopier par dossier, et une occasion de moins d'écrire
        # une date différente de celle qui a été dite.
        valeurs, erreurs = _resoudre(formulaire={})
        manquants = {e.split(" ")[0] for e in erreurs}
        assert "dateCelebrationLettres" not in manquants
        assert valeurs["dateCelebrationLettres"] == "onze septembre deux mille vingt"
        assert valeurs["epouxDateNaissanceLettres"] == \
            "trente et un mai mille neuf cent quatre-vingt-quatre"
        assert valeurs["epouseDateNaissanceLettres"] == \
            "douze février mille neuf cent quatre-vingt-treize"

    def test_la_saisie_du_consultant_passe_avant(self):
        # Il a le registre papier sous les yeux ; sa version fait foi.
        valeurs, _ = _resoudre(formulaire=dict(
            FORMULAIRE, dateCelebrationLettres="Onze Septembre l'an deux mil vingt"))
        assert valeurs["dateCelebrationLettres"] == "Onze Septembre l'an deux mil vingt"

    def test_une_date_illisible_ne_produit_pas_de_mention_inventee(self):
        # Mieux vaut un champ manquant, qui bloque et se voit, qu'une date
        # fausse sur un acte signé.
        _, erreurs = _resoudre(
            dossier=dict(DOSSIER, slots=dict(SLOTS, date_celebration="11/09/2020")),
            formulaire={})
        assert any(e.startswith("dateCelebrationLettres") for e in erreurs)

    def test_rien_ne_manque_quand_tout_est_saisi(self):
        _, erreurs = _resoudre()
        assert erreurs == []

    def test_l_heure_du_registre_reste_facultative(self):
        sans_heure = {k: v for k, v in FORMULAIRE.items()
                      if k not in ("heureRegistreLettres", "minuteRegistreLettres")}
        _, erreurs = _resoudre(formulaire=sans_heure)
        assert erreurs == []

    def test_un_champ_du_dialogue_manquant_est_signale(self):
        dossier = dict(DOSSIER, slots={k: v for k, v in SLOTS.items() if k != "nom_epouse"})
        _, erreurs = _resoudre(dossier=dossier)
        assert any(e.startswith("epouseNomFamille") for e in erreurs)


class TestLaValidationXsd:
    def _instance(self, valeurs):
        return gen._construire_instance_xsd(valeurs, False, gen.MODELES["constatation_mariage"])

    def test_un_dossier_complet_produit_une_instance_valide(self):
        valeurs, _ = _resoudre()
        assert gen._valider_xsd(self._instance(valeurs), gen.MODELES["constatation_mariage"]) == []

    def test_une_option_matrimoniale_inventee_est_refusee(self):
        valeurs, _ = _resoudre(dossier=dict(DOSSIER, slots=dict(SLOTS, option_matrimoniale="polygamie_7")))
        erreurs = gen._valider_xsd(self._instance(valeurs), gen.MODELES["constatation_mariage"])
        assert erreurs, "le XSD doit refuser une option hors du Code de la famille"

    def test_un_numero_de_registre_non_numerique_est_refuse(self):
        valeurs, _ = _resoudre(formulaire=dict(FORMULAIRE, numeroRegistreChiffres="trois cent sept"))
        assert gen._valider_xsd(self._instance(valeurs), gen.MODELES["constatation_mariage"])

    def test_une_date_de_celebration_mal_formee_est_refusee(self):
        valeurs, _ = _resoudre(dossier=dict(DOSSIER, slots=dict(SLOTS, date_celebration="11/09/2020")))
        assert gen._valider_xsd(self._instance(valeurs), gen.MODELES["constatation_mariage"])

    def test_un_champ_facultatif_vide_est_absent_et_non_vide(self):
        # Un élément vide ferait échouer le XSD ET dirait « renseigné, mais
        # rien » — ce qui n'est pas la même chose qu'un champ non rempli.
        valeurs, _ = _resoudre(commune=dict(COMMUNE, arrondissement=None))
        instance = self._instance(valeurs)
        assert not instance.findall(".//{*}arrondissement")
        assert gen._valider_xsd(instance, gen.MODELES["constatation_mariage"]) == []


class TestLeDocumentImprime:
    def _html(self, valeurs=None):
        if valeurs is None:
            valeurs, _ = _resoudre()
        return gen._rendre_html(valeurs, False, "S-2020-307", gen.MODELES["constatation_mariage"])

    def test_le_titre_du_modele_reel(self):
        assert "CERTIFICAT DE MARIAGE CONSTATÉ" in self._html()

    def test_le_bandeau_brouillon_est_present(self):
        # §5.4 : aucun document généré n'a de valeur légale en V1.
        assert "BROUILLON OFFICIEL" in self._html()

    def test_l_option_est_ecrite_en_toutes_lettres(self):
        # Le dossier stocke « monogamie » ; le certificat imprime « Monogamie ».
        html = self._html()
        assert "Monogamie" in html
        assert "Séparation des biens" in html

    def test_la_polygamie_est_ecrite_avec_son_nombre_d_epouses(self):
        valeurs, _ = _resoudre(dossier=dict(DOSSIER, slots=dict(SLOTS, option_matrimoniale="polygamie_4")))
        assert "Polygamie limitée à quatre épouses" in self._html(valeurs)

    def test_les_temoins_ne_sont_pas_imprimes(self):
        # Le modèle réel ne les porte pas : leur inventer une place sur le
        # document serait une falsification de forme. On cherche le MOT, pas
        # les noms : un bloc « Témoins » ajouté au modèle sortirait vide (les
        # témoins ne sont pas des valeurs résolues) et passerait inaperçu si on
        # ne testait que les noms.
        html = self._html().lower()
        assert "témoin" not in html
        assert "ibrahima fall" not in html
        assert "1234567890123" not in html

    def test_les_dates_du_registre_sont_celles_saisies(self):
        # L'apostrophe ressort échappée (`&#39;`) : le rendu échappe TOUT le
        # texte injecté, parce qu'il vient de saisies humaines — dictée
        # transcrite, frappe du consultant. C'est voulu ; la comparaison passe
        # donc par la même transformation plutôt que de la contourner.
        from markupsafe import escape
        html = self._html()
        assert str(escape("Onze Septembre l'an deux mille vingt")) in html
        assert "307" in html


class TestLaRelectureParLeCitoyen:
    """
    Le citoyen relit son document champ par champ, à l'oral, avant de le
    valider. La liste des champs à lire ne connaissait que l'extrait de
    naissance : un certificat de mariage se serait relu en SILENCE, aucune clé
    ne correspondant — un écran vide, sans erreur, devant une validation qui
    engage les époux.
    """

    def test_le_mariage_a_ses_propres_champs_a_relire(self):
        assert libelles.ordre_lecture("constatation_mariage")
        assert libelles.ordre_lecture("constatation_mariage") != libelles.ORDRE_LECTURE

    def test_chaque_champ_relu_existe_vraiment_dans_le_document(self):
        # Le vrai risque : une faute de frappe dans une clé, qui ferait
        # disparaître la ligne sans rien signaler.
        valeurs, _ = _resoudre()
        for cle in libelles.ordre_lecture("constatation_mariage"):
            assert cle in valeurs, f"clé relue absente du document : {cle}"

    def test_chaque_champ_relu_a_un_libelle_francais(self):
        for cle in libelles.ordre_lecture("constatation_mariage"):
            assert libelles.libelle(cle) != cle, f"libellé manquant : {cle}"

    def test_les_deux_epoux_sont_relus(self):
        ordre = libelles.ordre_lecture("constatation_mariage")
        assert "epouxPrenoms" in ordre and "epousePrenoms" in ordre

    def test_une_demarche_sans_document_ne_relit_rien(self):
        # Plutôt que la liste d'un autre document.
        assert libelles.ordre_lecture("changement_de_nom") == []

    def test_le_code_du_regime_n_est_pas_lu_tel_quel(self):
        # « Régime des biens : separation_des_biens » ne veut rien dire à
        # l'oral pour quelqu'un qui ne lit pas.
        phrase = libelles.phrase_lecture("regimeMatrimonial", "separation_des_biens")
        assert phrase == "Régime des biens : Séparation des biens."

    def test_l_option_polygame_est_lue_avec_son_nombre(self):
        phrase = libelles.phrase_lecture("optionMatrimoniale", "polygamie_2")
        assert phrase == "Option souscrite : Polygamie limitée à deux épouses."


class TestLaPhraseDiteAuCitoyen:
    """
    Narration audio du document généré (tâche 7.5 mobile). Elle est lue à voix
    haute : une phrase d'extrait de naissance sur un dossier de mariage
    donnerait « Ceci est un extrait de naissance pour l'enfant » — du charabia
    annoncé avec aplomb.
    """

    def _phrase(self, valeurs=None):
        if valeurs is None:
            valeurs, _ = _resoudre()
        return gen.construire_resume_document_genere(valeurs, "constatation_mariage")

    def test_elle_nomme_les_deux_epoux(self):
        phrase = self._phrase()
        assert "Amadou Diallo" in phrase and "Maty Sene" in phrase

    def test_elle_dit_de_quel_document_il_s_agit(self):
        assert "certificat de mariage" in self._phrase()
        assert "extrait de naissance" not in self._phrase()

    def test_elle_dit_l_option_souscrite(self):
        # Mention qui engage les époux : elle est dite, pas laissée au PDF.
        assert "monogamie" in self._phrase().lower()

    def test_elle_dit_la_date_et_le_lieu(self):
        phrase = self._phrase()
        assert "Onze Septembre l'an deux mille vingt" in phrase
        assert "Dakar" in phrase

    def test_un_document_incomplet_ne_produit_pas_de_phrase_bancale(self):
        assert self._phrase({}) == "Ceci est un certificat de mariage."

    def test_la_phrase_de_naissance_reste_intacte(self):
        # Le même appel, sans type de démarche, doit continuer à produire la
        # phrase de l'extrait de naissance.
        phrase = gen.construire_resume_document_genere(
            {"prenomEnfant": "Awa", "nomFamilleEnfant": "Ba", "sexe": "F"})
        assert phrase.startswith("Ceci est un extrait de naissance pour Awa Ba, née")
