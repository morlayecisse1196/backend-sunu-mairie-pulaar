"""
Refus de la partie confidentielle du certificat de décès (étape 5.4).

La partie basse du formulaire porte la cause médicale du décès. Le formulaire
indique lui-même qu'elle ne peut être communiquée ni en original ni en copie,
et qu'elle sera détruite. Une photo de cette partie enregistrée dans le
stockage d'une mairie serait une donnée de santé versée à un dossier d'état
civil, lisible par des agents administratifs, sauvegardée, irrattrapable.

Ce qui est verrouillé ici :

  * la partie basse est reconnue et refusée AVANT tout enregistrement ;
  * la partie haute, elle, passe : refuser une photo valide renverrait le
    citoyen photographier un document qu'il a bien envoyé ;
  * quand la lecture est impossible, on refuse au lieu d'enregistrer sans
    savoir ;
  * rien de ce qui est lu sur la photo ne ressort de la fonction.
"""
from __future__ import annotations

import logging

import pytest

from services import partie_confidentielle as pc

# Mentions IMPRIMÉES sur le formulaire officiel — aucune donnée d'une personne
# réelle n'apparaît dans ce fichier, volontairement.
PARTIE_BASSE = (
    "CERTIFICAT DE CAUSES DE DECES  A remplir et à clore par le médecin  "
    "Renseignements confidentiels et anonymes sur les causes du décès  "
    "I. CAUSES DU DECES  a. Cause immédiate  b. Cause initiale"
)
PARTIE_HAUTE = (
    "CERTIFICAT DE DECES  A remplir et à clore par le médecin ou le personnel de santé  "
    "Commune de décès  Nom  Prénom  Date de naissance  Sexe  Adresse de domicile  "
    "Existence d'un obstacle médico-légal : Oui Non  RESERVE A LA MAIRIE  "
    "N° d'ordre du décès  Partie à détacher et à conserver dans les mairies"
)


def _lecteur(texte):
    return lambda _octets: texte


class TestRefus:
    @pytest.mark.parametrize("extrait", [
        PARTIE_BASSE,
        "certificat de causes de deces",
        "RENSEIGNEMENTS CONFIDENTIELS ET ANONYMES",
        "Une autopsie a-t-elle été pratiquée ?",
        "Ce document ne peut être communiqué ni en original ni en copie",
    ])
    def test_la_partie_basse_est_refusee(self, extrait):
        code, message = pc.examiner(b"photo", lire_texte=_lecteur(extrait))
        assert code == pc.CONFIDENTIELLE
        assert "partie du haut" in message

    def test_la_reconnaissance_survit_aux_accents_et_aux_majuscules(self):
        # L'OCR rend un texte approximatif : accents perdus, casse variable.
        code, _ = pc.examiner(b"photo", lire_texte=_lecteur("CERTIFICAT DE CAUSES DE DÉCÈS"))
        assert code == pc.CONFIDENTIELLE

    def test_le_message_explique_quoi_faire(self):
        _, message = pc.examiner(b"photo", lire_texte=_lecteur(PARTIE_BASSE))
        assert "détachez" in message.lower() and "certificat de décès" in message.lower()


class TestAcceptation:
    def test_la_partie_haute_passe(self):
        assert pc.examiner(b"photo", lire_texte=_lecteur(PARTIE_HAUTE)) == (None, None)

    def test_l_obstacle_medico_legal_ne_declenche_pas_le_refus(self):
        # Cette mention est sur la partie HAUTE : la confondre bloquerait la
        # démarche pour tout le monde.
        assert pc.examiner(b"photo", lire_texte=_lecteur(
            "Existence d'un obstacle médico-légal : Oui Non")) == (None, None)

    def test_une_carte_d_identite_passe(self):
        assert pc.examiner(b"photo", lire_texte=_lecteur(
            "REPUBLIQUE DU SENEGAL CARTE NATIONALE D'IDENTITE")) == (None, None)


class TestLectureImpossible:
    def test_sans_lecture_possible_on_refuse(self, monkeypatch):
        # Enregistrer sans avoir vérifié, c'est prendre le risque de stocker
        # une donnée de santé. La photo, elle, se reprend.
        monkeypatch.setattr(pc, "REFUSER_SI_VERIFICATION_IMPOSSIBLE", True)

        def en_panne(_octets):
            raise RuntimeError("moteur absent")

        code, message = pc.examiner(b"photo", lire_texte=en_panne)
        assert code == pc.VERIFICATION_IMPOSSIBLE and "confidentielle" in message

    def test_le_choix_inverse_reste_possible_mais_n_est_pas_le_defaut(self, monkeypatch):
        monkeypatch.setattr(pc, "REFUSER_SI_VERIFICATION_IMPOSSIBLE", False)

        def en_panne(_octets):
            raise RuntimeError("moteur absent")

        assert pc.examiner(b"photo", lire_texte=en_panne) == (None, None)


class TestConfidentialite:
    def test_rien_de_ce_qui_est_lu_ne_ressort(self):
        # Ni la cause, ni le nom du défunt ne doivent se retrouver dans une
        # réponse d'API ou un journal.
        texte = PARTIE_BASSE + " commotion cerebrale Thiouck Seynabou"
        code, message = pc.examiner(b"photo", lire_texte=_lecteur(texte))
        assert code == pc.CONFIDENTIELLE
        for secret in ("commotion", "cerebrale", "thiouck", "seynabou"):
            assert secret not in message.lower()

    def test_le_journal_ne_porte_que_la_mention_du_formulaire(self):
        # Le journal du projet ne remonte pas au logger racine (propagate =
        # False, services/journal.py) : on écoute directement le sien.
        lignes: list[str] = []
        ecouteur = logging.Handler()
        ecouteur.emit = lambda enregistrement: lignes.append(enregistrement.getMessage())
        journal_module = logging.getLogger("sunu.partie_confidentielle")
        journal_module.addHandler(ecouteur)
        try:
            pc.examiner(b"photo", lire_texte=_lecteur(PARTIE_BASSE + " commotion cerebrale"))
        finally:
            journal_module.removeHandler(ecouteur)
        journal = " ".join(lignes).lower()
        assert "causes de deces" in journal
        assert "commotion" not in journal
