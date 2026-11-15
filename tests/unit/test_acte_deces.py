"""
L'acte de décès délivré par la mairie (étape 5.5).

⚠️ Le modèle a été construit d'après une copie intégrale FRANÇAISE (mairie de
Ris-Orangis, Essonne) donnée comme exemple : ses mentions sont des hypothèses
de forme, à confirmer par un officier d'état civil sénégalais. Ce que ces
tests verrouillent, ce n'est donc pas « la loi », c'est que le document dise
exactement ce que le dossier contient — et rien d'autre.

Le test le plus important de ce fichier est le dernier :
`TestAucuneDonneeDeSante`. L'application ne collecte, ne stocke et n'imprime
JAMAIS la cause d'un décès. Le certificat médical la porte ; l'acte de la
mairie non — le modèle réel le confirme, il n'en dit pas un mot.
"""
import document_generator as gen
from services import libelles_document as libelles

COMMUNE = {"nom": "Touba", "region": "Diourbel", "departement": "Mbacké",
           "arrondissement": None}

# Ce que le dialogue vocal collecte (migration 028).
SLOTS = {
    "prenoms_defunt": "Seynabou", "nom_defunt": "Thiouck", "sexe_defunt": "feminin",
    "date_naissance_defunt": "1997-08-19", "lieu_naissance_defunt": "Touba",
    "profession_defunt": "Commerçante", "domicile_defunt": "Touba, quartier Darou",
    "nationalite_defunt": "Sénégalaise", "situation_matrimoniale_defunt": "marie",
    "nom_pere_defunt": "Modou Thiouck", "nom_mere_defunt": "Adja Thiouck",
    "date_deces": "2023-05-07", "heure_deces": "onze heures",
    "lieu_deces": "Hôpital Ndamatou", "commune_deces": "Touba",
    "nom_declarant": "Cheikh Thiouck", "lien_avec_defunt": "frère",
    "piece_declarant": "1234567890123",
    "certificat_medical_existe": True, "obstacle_medico_legal": False,
}

# Ce que le consultant recopie du registre et du certificat médical.
FORMULAIRE = {
    "numeroActe": "543",
    "dateNaissanceDefuntLettres": "dix-neuf août mille neuf cent quatre-vingt-dix-sept",
    "dateDecesLettres": "sept mai deux mille vingt-trois",
    "heureDecesLettres": "onze heures",
    "dateDressageLettres": "neuf mai deux mille vingt-trois",
    "officierEtatCivil": "Oumou SY",
}

DOSSIER = {"id": "d1", "type_demarche": "declaration_deces",
           "numero_suivi": "S-2023-543", "slots": SLOTS}

MODELE = None  # rempli au premier appel


def _resoudre(dossier=None, commune=None, formulaire=None):
    return gen.resoudre_template(dossier or DOSSIER, commune or COMMUNE,
                                 formulaire if formulaire is not None else FORMULAIRE,
                                 False)


def _modele():
    return gen.MODELES["declaration_deces"]


def _html(valeurs=None):
    if valeurs is None:
        valeurs, _ = _resoudre()
    return gen._rendre_html(valeurs, False, "S-2023-543", _modele())


class TestLeModele:
    def test_le_deces_a_desormais_un_modele(self):
        assert "declaration_deces" in gen.DEMARCHES_AVEC_MODELE

    def test_un_dossier_de_deces_lit_le_bon_template(self):
        valeurs, _ = _resoudre()
        assert "prenomEnfant" not in valeurs and "epouxPrenoms" not in valeurs
        assert valeurs["defuntNomFamille"] == "Thiouck"

    def test_un_dossier_complet_ne_manque_de_rien(self):
        _, erreurs = _resoudre()
        assert erreurs == []

    def test_sans_les_mentions_du_registre_la_generation_est_bloquee(self):
        _, erreurs = _resoudre(formulaire={})
        manquants = {e.split(" ")[0] for e in erreurs}
        assert {"numeroActe", "dateDressageLettres", "officierEtatCivil"} <= manquants

    def test_les_dates_en_lettres_sont_ecrites_automatiquement(self):
        valeurs, erreurs = _resoudre(formulaire={})
        manquants = {e.split(" ")[0] for e in erreurs}
        assert "dateDecesLettres" not in manquants
        assert valeurs["dateDecesLettres"] == "sept mai deux mille vingt-trois"
        assert valeurs["defuntDateNaissanceLettres"] == \
            "dix-neuf août mille neuf cent quatre-vingt-dix-sept"

    def test_la_saisie_du_consultant_passe_avant(self):
        valeurs, _ = _resoudre(formulaire=dict(FORMULAIRE, dateDecesLettres="sept mai deux mil vingt-trois"))
        assert valeurs["dateDecesLettres"] == "sept mai deux mil vingt-trois"


class TestLaValidationXsd:
    def _instance(self, valeurs):
        return gen._construire_instance_xsd(valeurs, False, _modele())

    def test_un_dossier_complet_produit_une_instance_valide(self):
        valeurs, _ = _resoudre()
        assert gen._valider_xsd(self._instance(valeurs), _modele()) == []

    def test_une_situation_matrimoniale_inventee_est_refusee(self):
        valeurs, _ = _resoudre(dossier=dict(
            DOSSIER, slots=dict(SLOTS, situation_matrimoniale_defunt="concubinage")))
        assert gen._valider_xsd(self._instance(valeurs), _modele())

    def test_une_date_de_deces_mal_formee_est_refusee(self):
        valeurs, _ = _resoudre(dossier=dict(DOSSIER, slots=dict(SLOTS, date_deces="07/05/2023")))
        assert gen._valider_xsd(self._instance(valeurs), _modele())

    def test_un_numero_d_acte_non_numerique_est_refuse(self):
        valeurs, _ = _resoudre(formulaire=dict(FORMULAIRE, numeroActe="cinq cent quarante-trois"))
        assert gen._valider_xsd(self._instance(valeurs), _modele())

    def test_le_conjoint_absent_ne_bloque_rien(self):
        # Le dialogue ne demande pas le nom du conjoint : la mention est
        # simplement absente, jamais devinée.
        valeurs, erreurs = _resoudre()
        assert erreurs == []
        assert not self._instance(valeurs).findall(".//{*}conjoint")


class TestLesAccordsDuDocument:
    """
    « est décédé » pour une femme n'est pas une coquille sur un acte d'état
    civil : c'est une erreur sur la personne, et la famille la verra.
    """

    def test_une_femme_est_decedee(self):
        html = _html()
        assert "est décédée" in html
        assert "est décédé " not in html

    def test_un_homme_est_decede(self):
        valeurs, _ = _resoudre(dossier=dict(DOSSIER, slots=dict(SLOTS, sexe_defunt="masculin")))
        assert "est décédé " in _html(valeurs)

    def test_la_filiation_suit_le_sexe(self):
        assert "fille de" in _html()
        valeurs, _ = _resoudre(dossier=dict(DOSSIER, slots=dict(SLOTS, sexe_defunt="masculin")))
        assert "fils de" in _html(valeurs)

    def test_la_situation_matrimoniale_suit_le_sexe(self):
        assert "épouse" in _html()
        valeurs, _ = _resoudre(dossier=dict(DOSSIER, slots=dict(SLOTS, sexe_defunt="masculin")))
        assert "époux" in _html(valeurs)

    def test_une_veuve_n_est_pas_un_veuf(self):
        valeurs, _ = _resoudre(dossier=dict(
            DOSSIER, slots=dict(SLOTS, situation_matrimoniale_defunt="veuf")))
        html = _html(valeurs)
        assert "veuve" in html

    def test_les_participes_de_la_phrase_s_accordent_aussi(self):
        # « née le », « domiciliée à » : les accords du corps de l'acte, pas
        # seulement celui du verbe principal.
        html = _html()
        assert "née le" in html and "domiciliée à" in html

        valeurs, _ = _resoudre(dossier=dict(DOSSIER, slots=dict(SLOTS, sexe_defunt="masculin")))
        masculin = _html(valeurs)
        assert "né le" in masculin and "née le" not in masculin
        assert "domicilié à" in masculin and "domiciliée à" not in masculin

    def test_le_sexe_n_est_pas_imprime_tel_quel(self):
        # Le modèle réel ne porte pas de case « sexe » : il se lit dans les
        # accords. Imprimer « feminin » ferait une mention qui n'existe pas.
        assert "feminin" not in _html()


class TestLeDocumentImprime:
    def test_le_titre_et_le_numero(self):
        html = _html()
        assert "ACTE DE DÉCÈS" in html
        assert "543" in html

    def test_le_bandeau_brouillon_est_present(self):
        assert "BROUILLON OFFICIEL" in _html()

    def test_le_defunt_et_le_declarant_sont_nommes(self):
        html = _html()
        assert "Seynabou" in html and "Thiouck" in html
        assert "Cheikh Thiouck" in html

    def test_les_mentions_absentes_ne_laissent_pas_de_phrase_bancale(self):
        # Âge, métier et adresse du déclarant figurent sur le modèle français
        # mais ne sont pas demandés à l'oral : la phrase doit tenir sans eux.
        html = _html()
        assert "âgé de  ans" not in html
        assert ", ," not in html


class TestLaRelectureEtLaNarration:
    def test_le_deces_a_ses_propres_champs_a_relire(self):
        ordre = libelles.ordre_lecture("declaration_deces")
        assert ordre and ordre != libelles.ORDRE_LECTURE

    def test_chaque_champ_relu_existe_dans_le_document(self):
        valeurs, _ = _resoudre()
        for cle in libelles.ordre_lecture("declaration_deces"):
            assert cle in valeurs, f"clé relue absente du document : {cle}"

    def test_chaque_champ_relu_a_un_libelle_francais(self):
        for cle in libelles.ordre_lecture("declaration_deces"):
            assert libelles.libelle(cle) != cle, f"libellé manquant : {cle}"

    def test_la_phrase_dite_nomme_le_defunt_et_accorde(self):
        valeurs, _ = _resoudre()
        phrase = gen.construire_resume_document_genere(valeurs, "declaration_deces")
        assert "Seynabou Thiouck" in phrase
        assert "décédée" in phrase

    def test_la_phrase_ne_retombe_pas_sur_un_autre_document(self):
        valeurs, _ = _resoudre()
        phrase = gen.construire_resume_document_genere(valeurs, "declaration_deces")
        assert "extrait de naissance" not in phrase
        assert "certificat de mariage" not in phrase

    def test_un_document_incomplet_ne_produit_pas_de_phrase_bancale(self):
        assert gen.construire_resume_document_genere({}, "declaration_deces") \
            == "Ceci est un acte de décès."


class TestAucuneDonneeDeSante:
    """
    Règle posée au départ du projet, et confirmée par les deux documents
    réels : la cause du décès appartient au certificat médical, qui est
    confidentiel et détruit après usage statistique. Elle n'entre jamais dans
    cette application — ni en base, ni dans le document, ni à l'oral.
    """

    MOTS_INTERDITS = ("cause", "maladie", "autopsie", "médico-légal", "medico-legal",
                      "patholog", "diagnostic")

    def test_le_contrat_de_donnees_ne_prevoit_aucune_cause(self):
        xsd = open(_modele().chemin_xsd, encoding="utf-8").read().lower()
        # Le mot apparaît dans l'avertissement en tête du fichier ; ce qui est
        # interdit, c'est un ÉLÉMENT qui en porterait une.
        import re
        elements = set(re.findall(r'name="([A-Za-z]+)"', xsd))
        assert not [e for e in elements if any(m in e.lower() for m in self.MOTS_INTERDITS)]

    def test_le_template_ne_resout_aucune_cause(self):
        sources = [e.get("source") for e in _modele().arbre().iter() if e.get("source")]
        assert not [s for s in sources if any(m in s.lower() for m in self.MOTS_INTERDITS)]

    def test_le_document_imprime_n_en_porte_aucune_trace(self):
        # Sans les commentaires du template, qui expliquent justement pourquoi
        # aucune cause n'y figure — ils ne sont pas imprimés sur le papier.
        import re
        html = re.sub(r"<!--.*?-->", "", _html(), flags=re.DOTALL).lower()
        assert "cause" not in html
        assert "autopsie" not in html

    def test_la_phrase_dite_a_la_famille_n_en_dit_rien(self):
        valeurs, _ = _resoudre()
        phrase = gen.construire_resume_document_genere(valeurs, "declaration_deces").lower()
        assert not [m for m in self.MOTS_INTERDITS if m in phrase]

    def test_les_champs_relus_n_en_portent_aucun(self):
        for cle in libelles.ordre_lecture("declaration_deces"):
            assert not [m for m in self.MOTS_INTERDITS if m in cle.lower()]
