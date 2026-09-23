"""
La définition d'une démarche vient de la base (plan maître, étapes 2.2 et 2.3).

Cinq choses étaient écrites en dur dans le code : les messages de demande de
pièce, les types de documents acceptés, les slots initiaux, la bascule en mode
administratif, et les seuils des cas légaux. Ajouter une démarche demandait
donc de modifier Python à cinq endroits — et d'y penser à chaque fois.

Ce qui est verrouillé ici : elles viennent bien de la donnée, ET le repli
continue de fonctionner quand la base est hors d'atteinte, pour qu'une panne
réseau ne coupe pas un citoyen déjà en ligne.
"""
from __future__ import annotations

import pytest

from services import demarche

CHAMPS = [
    {"type_demarche": "extrait_naissance", "nom_champ": "age_enfant", "type_valeur": "age", "ordre": 5, "obligatoire": True,
     "question": "Quel âge a votre enfant ?", "question_pulaar": "Ɓiɗɗo maa no foti duuɓi?",
     "pulaar_valide": True},
    {"type_demarche": "extrait_naissance", "nom_champ": "nom_enfant", "type_valeur": "texte", "ordre": 30, "obligatoire": True,
     "question": "Quel est le nom complet de votre enfant ?", "question_pulaar": None,
     "pulaar_valide": False},
    {"type_demarche": "extrait_naissance", "nom_champ": "surnom", "type_valeur": "texte", "ordre": 40, "obligatoire": False,
     "question": "Un surnom ?"},
    # Le cas dangereux : une traduction automatique déposée là en attendant la
    # relecture. Elle ne doit PAS être dite tant que personne ne l'a validée.
    {"type_demarche": "extrait_naissance", "nom_champ": "nom_mere", "type_valeur": "texte", "ordre": 70,
     "obligatoire": True, "question": "Quel est le nom de la maman ?",
     "question_pulaar": "TRADUCTION AUTOMATIQUE NON RELUE", "pulaar_valide": False},
]

DOCUMENTS = [
    {"type_demarche": "extrait_naissance", "type_document": "certificat_naissance", "ordre": 20, "obligatoire": True,
     "message_demande": "Envoyez-moi une photo du certificat de naissance.",
     "messages_rappel": ["Toujours pas reçu le certificat.", "Je n'ai rien reçu, envoyez la photo."],
     "message_demande_pulaar": "Neldu fotoo sertifika jibineede.",
     "messages_rappel_pulaar": ["Mi heɓaani tawo sertifika.", "Hay huunde mi heɓaani."],
     "pulaar_valide": True},
]

DEFINITIONS = [
    {"type_demarche": "extrait_naissance", "libelle": "Extrait de naissance", "traitable": True,
     "actif": True, "champ_age": "age_enfant", "version": 3,
     "mots_cles": ["extrait de naissance", "acte de naissance"]},
    {"type_demarche": "certificat_residence", "libelle": "Certificat de résidence", "traitable": False,
     "actif": True, "champ_age": None, "version": 1, "mots_cles": ["certificat de résidence"]},
]

CAS = [
    {"type_demarche": "extrait_naissance", "code": "dans_les_delais", "ordre": 10, "condition": "age_jours(age_enfant) <= 30", "libelle": "Dans les délais"},
    {"type_demarche": "extrait_naissance", "code": "tardif", "ordre": 20, "condition": "age_jours(age_enfant) <= 365", "libelle": "Tardif"},
    {"type_demarche": "extrait_naissance", "code": "jugement_requis", "ordre": 30, "condition": None, "libelle": "Jugement requis"},
]

TYPES_DOCUMENTS = [
    {"type_document": "certificat_naissance", "obsolete": False},
    {"type_document": "cni_declarant_recto", "obsolete": False},
    {"type_document": "cni_declarant", "obsolete": True},
]

TABLES = {
    "demarche_champs": CHAMPS,
    "demarche_documents": DOCUMENTS,
    "demarche_definitions": DEFINITIONS,
    "demarche_cas": CAS,
    "types_document_acceptes": TYPES_DOCUMENTS,
}


@pytest.fixture
def base(monkeypatch):
    """Les tables de configuration, telles qu'elles seront après la migration 018."""
    def lire(nom, **filtres):
        lignes = TABLES.get(nom, [])
        for colonne, valeur in filtres.items():
            lignes = [l for l in lignes if l.get(colonne) == valeur]
        return lignes

    monkeypatch.setattr(demarche, "_table", lire)
    demarche.vider_cache()


class TestSlotsInitiaux:
    def test_deduits_des_champs_declares(self, base):
        assert demarche.slots_vides() == {
            "age_enfant": {"valeur": None, "unite": None},  # forme attendue par normaliser_age
            "nom_enfant": None,
            "surnom": None,
            "nom_mere": None,
        }

    def test_repli_quand_la_base_est_muette(self):
        # Le conftest coupe les tables : on doit retrouver les slots figés,
        # donc le comportement d'avant l'étape 2.3.
        assert set(demarche.slots_vides()) == {
            "age_enfant", "commune_naissance", "nom_enfant", "date_naissance_enfant",
            "nom_declarant", "nom_mere", "date_naissance_mere", "parents_maries",
        }

    def test_le_repli_n_est_jamais_partage(self):
        # Modifier les slots d'une session ne doit pas contaminer la suivante.
        premiers = demarche.slots_vides()
        premiers["age_enfant"]["valeur"] = 7
        assert demarche.slots_vides()["age_enfant"]["valeur"] is None


class TestBascule:
    def test_les_mots_cles_remplacent_la_recherche_du_mot_naissance(self, base):
        assert demarche.reconnaitre_demarche("Extrait de naissance").type_demarche == "extrait_naissance"
        assert demarche.reconnaitre_demarche("Demande d'acte de naissance") is not None

    def test_une_autre_demarche_en_naissance_ne_bascule_plus_a_tort(self, base):
        # Le test historique cherchait « naissance » n'importe où dans le nom :
        # ces deux démarches basculaient vers l'extrait de naissance.
        assert demarche.reconnaitre_demarche("Certificat de naissance") is None
        assert demarche.reconnaitre_demarche("Déclaration de naissance") is None

    def test_une_demarche_non_traitable_ne_bascule_pas(self, base):
        # Elle existe, mais le dialogue guidé ne sait pas la mener :
        # mode information seulement.
        assert demarche.reconnaitre_demarche("Certificat de résidence") is None

    def test_nom_vide(self, base):
        assert demarche.reconnaitre_demarche(None) is None
        assert demarche.reconnaitre_demarche("   ") is None


class TestCasLegaux:
    def test_le_premier_cas_vrai_gagne(self, base):
        assert demarche.determiner_cas({"age_enfant": {"valeur": 10, "unite": "jours"}}) == "dans_les_delais"
        assert demarche.determiner_cas({"age_enfant": {"valeur": 3, "unite": "mois"}}) == "tardif"
        assert demarche.determiner_cas({"age_enfant": {"valeur": 4, "unite": "ans"}}) == "jugement_requis"

    def test_sans_age_aucun_cas_n_est_inscrit(self, base):
        # Surtout pas le cas par défaut : un cas faux sur un dossier vaut
        # moins que pas de cas du tout.
        assert demarche.determiner_cas({}) is None

    def test_les_seuils_viennent_de_la_base(self, monkeypatch, base):
        # Le DSF hésite sur le premier seuil (« jusqu'à 45 jours en zone rurale
        # éloignée selon les sources ») : le corriger ne doit pas demander un
        # redéploiement.
        monkeypatch.setattr(demarche, "_table", lambda nom, **f: (
            [{"type_demarche": "extrait_naissance", "code": "dans_les_delais", "ordre": 10, "condition": "age_jours(age_enfant) <= 45", "libelle": "x"},
             {"type_demarche": "extrait_naissance", "code": "tardif", "ordre": 20, "condition": None, "libelle": "y"}]
            if nom == "demarche_cas" else TABLES.get(nom, [])
        ))
        demarche.vider_cache()
        assert demarche.determiner_cas({"age_enfant": {"valeur": 40, "unite": "jours"}}) == "dans_les_delais"


class TestTypesDeDocuments:
    def test_les_types_obsoletes_restent_acceptes(self, base):
        # D'anciens dossiers en portent : refuser leur relecture serait pire
        # que de les accepter.
        assert "cni_declarant" in demarche.types_documents_acceptes()

    def test_repli_quand_la_table_est_muette(self):
        assert "certificat_naissance" in demarche.types_documents_acceptes()


class TestMessages:
    def test_la_premiere_demande_puis_les_rappels_a_tour_de_role(self, base):
        ligne = DOCUMENTS[0]
        assert demarche.message_document(ligne, 0).francais.startswith("Envoyez-moi")
        assert demarche.message_document(ligne, 1).francais == "Toujours pas reçu le certificat."
        assert demarche.message_document(ligne, 2).francais == "Je n'ai rien reçu, envoyez la photo."
        # On boucle sur les variantes plutôt que de répéter la dernière.
        assert demarche.message_document(ligne, 3).francais == "Toujours pas reçu le certificat."

    def test_un_document_sans_message_a_un_texte_de_secours(self, base):
        secours = demarche.message_document({"type_document": "acte_x"}, 0)
        assert "acte_x" in secours.francais

    def test_le_pulaar_valide_court_circuite_la_traduction(self, base):
        # Étape 3.3 : une phrase dont le pulaar est relu ne repasse plus par
        # le modèle, qui la retraduisait différemment à chaque conversation.
        assert demarche.message_document(DOCUMENTS[0], 0).pulaar_pret() == "Neldu fotoo sertifika jibineede."
        assert demarche.question_champ(CHAMPS[0]).pulaar_pret() == "Ɓiɗɗo maa no foti duuɓi?"

    def test_un_pulaar_non_valide_n_est_jamais_dit(self, base):
        # Le cas qui compte : la colonne pulaar est REMPLIE, mais pas relue.
        # C'est le français qui part au traducteur — jamais une traduction
        # automatique servie comme si elle avait été validée.
        non_relu = CHAMPS[3]
        assert non_relu["question_pulaar"]
        assert demarche.question_champ(non_relu).pulaar_pret() is None, "rien à dire en pulaar : le français repart au traducteur"
        # Et une colonne pulaar vide se comporte pareil.
        assert demarche.question_champ(CHAMPS[1]).pulaar_pret() is None


class TestCache:
    def test_une_modification_est_visible_apres_vidage(self, monkeypatch):
        lectures = []

        def lire(nom, **_f):
            lectures.append(nom)
            return DEFINITIONS if nom == "demarche_definitions" else []

        monkeypatch.setattr(demarche, "_table", lire)
        demarche.vider_cache()

        demarche.definition()
        demarche.definition()
        assert lectures.count("demarche_definitions") == 1, "la deuxième lecture doit venir du cache"

        demarche.vider_cache()
        demarche.definition()
        assert lectures.count("demarche_definitions") == 2
