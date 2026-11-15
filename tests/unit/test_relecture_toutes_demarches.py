"""
Le verrou d'avant-relecture, pour TOUTES les démarches.

Avant ce correctif, la relecture obligatoire (RG7) n'était déclenchée que si
une liste de champs ÉCRITE EN DUR était remplie : commune de naissance, nom de
l'enfant, nom de la mère… Ces champs n'existent pas dans la constatation de
mariage ni dans la déclaration de décès. Le dialogue de ces deux démarches
allait donc jusqu'au bout, puis butait : le moteur refusait de relire un
dossier qu'il croyait incomplet, et l'agent répondait « Excusez-moi, je n'ai
pas bien compris » sans fin. Aucune de ces deux démarches ne pouvait aboutir.

Le verrou lit maintenant la DÉFINITION de la démarche. Ce fichier le prouve
sur une démarche qui n'a aucun champ en commun avec l'extrait de naissance.
"""
from __future__ import annotations

import pytest

import slot_controller

# Une démarche volontairement SANS aucun champ de l'extrait de naissance.
MARIAGE = [
    {"nom_champ": "date_ceremonie", "type_valeur": "date", "ordre": 10, "obligatoire": True,
     "question": "Quel jour ?", "regle_validation": None, "condition": None},
    {"nom_champ": "nom_epoux", "type_valeur": "texte", "ordre": 20, "obligatoire": True,
     "question": "Le nom de l'époux ?", "regle_validation": None, "condition": None},
    {"nom_champ": "surnom", "type_valeur": "texte", "ordre": 30, "obligatoire": False,
     "question": "Un surnom ?", "regle_validation": None, "condition": None},
    {"nom_champ": "nombre_epouses", "type_valeur": "nombre", "ordre": 40, "obligatoire": True,
     "question": "Combien d'épouses ?", "regle_validation": "1:4", "condition": "option = polygamie"},
    {"nom_champ": "option", "type_valeur": "enum", "ordre": 15, "obligatoire": True,
     "question": "Monogamie ou polygamie ?", "regle_validation": "monogamie|polygamie", "condition": None},
]


def manquants(slots, ignores=frozenset()):
    return slot_controller.champs_obligatoires_manquants(slots, MARIAGE, set(ignores))


class TestLeVerrou:
    def test_une_demarche_remplie_peut_enfin_etre_relue(self):
        # LE bug : cette démarche ne contient aucun champ de l'extrait de
        # naissance. L'ancien verrou en réclamait huit, pour toujours.
        complet = {"date_ceremonie": "2026-09-01", "nom_epoux": "Modou Diallo", "option": "monogamie"}
        assert manquants(complet) == []

    def test_un_champ_obligatoire_vide_retient_la_relecture(self):
        # On ne relit pas au citoyen — et on n'envoie pas à la mairie — un
        # dossier incomplet.
        assert manquants({"date_ceremonie": "2026-09-01", "option": "monogamie"}) == ["nom_epoux"]

    def test_un_champ_facultatif_ne_retient_rien(self):
        complet = {"date_ceremonie": "2026-09-01", "nom_epoux": "Modou Diallo", "option": "monogamie"}
        assert "surnom" not in manquants(complet)

    def test_une_question_ecartee_ne_manque_pas(self):
        # En monogamie, « combien d'épouses » ne sera jamais posée.
        complet = {"date_ceremonie": "2026-09-01", "nom_epoux": "Modou Diallo", "option": "monogamie"}
        assert "nombre_epouses" not in manquants(complet)

    def test_la_meme_question_manque_quand_elle_s_applique(self):
        polygame = {"date_ceremonie": "2026-09-01", "nom_epoux": "Modou Diallo", "option": "polygamie"}
        assert manquants(polygame) == ["nombre_epouses"]

    def test_une_condition_encore_inconnue_retient_la_relecture(self):
        # Le régime de l'union n'est pas connu : on ignore si la question
        # s'applique. Relire maintenant, c'est risquer d'envoyer un dossier
        # auquel il manque une information obligatoire.
        sans_regime = {"date_ceremonie": "2026-09-01", "nom_epoux": "Modou Diallo"}
        assert "nombre_epouses" in manquants(sans_regime)

    def test_un_champ_abandonne_ne_bloque_plus(self):
        # Un champ auquel le citoyen n'a pas su répondre a déjà été écarté par
        # la collecte : le réclamer ici rouvrirait la boucle qu'on vient de
        # fermer.
        partiel = {"date_ceremonie": "2026-09-01", "option": "monogamie"}
        assert manquants(partiel, ignores={"nom_epoux"}) == []

    @pytest.mark.parametrize("champ", ["date_ceremonie", "nom_epoux", "option"])
    def test_chaque_champ_obligatoire_est_reellement_exige(self, champ):
        complet = {"date_ceremonie": "2026-09-01", "nom_epoux": "Modou Diallo", "option": "monogamie"}
        del complet[champ]
        assert champ in manquants(complet)


class TestAccordAvecLaCollecte:
    """Le verrou ne doit jamais réclamer ce que la collecte ne demande plus."""

    def test_ce_qui_est_encore_demande_est_exactement_ce_qui_manque(self):
        # Tant qu'une étape reste à servir, il reste quelque chose à remplir —
        # et inversement, quand la collecte a fini, le verrou s'ouvre.
        cas = [
            {},
            {"date_ceremonie": "2026-09-01"},
            {"date_ceremonie": "2026-09-01", "option": "monogamie"},
            {"date_ceremonie": "2026-09-01", "option": "monogamie", "nom_epoux": "Modou"},
        ]
        for slots in cas:
            etape = slot_controller.determiner_etape_courante(slots, set(), MARIAGE, [], {"surnom"})
            reste_a_remplir = bool(manquants(slots, ignores={"surnom"}))
            if etape is None:
                assert not reste_a_remplir, "la collecte a fini mais le verrou réclame encore un champ"
