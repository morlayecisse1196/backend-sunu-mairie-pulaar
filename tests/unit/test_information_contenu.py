"""
Contenu du mode information (plan maître, étape 5.6).

Avant toute démarche, l'agent RÉPOND : quels papiers, quelles conditions,
combien, en combien de temps, où. Ces informations existaient en base — coût,
délai, lieu, conditions, alertes — mais seuls le nom et trois documents
arrivaient au modèle. À la question « combien ça coûte ? », il n'avait donc
rien de fiable à dire.

Ce qui est verrouillé ici :

  * tout ce qui sert à répondre est transmis ;
  * une information absente est annoncée comme absente, jamais comblée ;
  * l'agent ne propose de commencer que les démarches qu'il sait mener ;
  * un administrateur peut corriger un tarif, mais pas renommer une fiche
    sans quoi la recherche ne la retrouverait plus.
"""
from __future__ import annotations

import pytest

from prompts import (
    SCHEMA_REPONSE_INFORMATION,
    SYSTEM_PROMPT_GENERATOR,
    build_generator_prompt,
)
from services import informations, rag

FICHE = {
    "nom_demarche": "Constatation de mariage",
    "categorie": "État Civil",
    "documents_requis": ["Cartes d'identité des époux", "Actes de naissance", "Cartes des témoins"],
    "conditions": ["Cérémonie de moins de six mois", "Deux témoins majeurs"],
    "cout": "2 000 FCFA",
    "delai": "Dans la journée",
    "lieu": "Centre d'état civil du lieu de la cérémonie",
    "alertes": ["Passé six mois, il faut saisir le tribunal"],
}

DEMARCHES = [
    type("D", (), {"type_demarche": "constatation_mariage", "libelle": "Constatation de mariage",
                   "mots_cles": ("constatation de mariage", "mariage")})(),
]


@pytest.fixture(autouse=True)
def demarches_menables(monkeypatch):
    from services import demarche as service_demarche
    monkeypatch.setattr(service_demarche, "demarches_traitables", lambda: DEMARCHES)
    service_demarche.vider_cache()


class TestCeQuiEstTransmis:
    @pytest.mark.parametrize("attendu", [
        "2 000 FCFA", "Dans la journée", "Centre d'état civil", "six mois",
        "Cartes d'identité des époux", "Constatation de mariage",
    ])
    def test_le_modele_recoit_de_quoi_repondre(self, attendu):
        assert attendu in rag.resume_rag([FICHE])

    def test_les_alertes_sont_signalees(self):
        assert "À signaler au citoyen" in rag.resume_rag([FICHE])

    def test_sans_resultat_on_le_dit(self):
        assert "Aucune information officielle" in rag.resume_rag([])

    def test_le_resume_reste_court_pour_l_oral(self):
        enorme = {**FICHE, "conditions": [f"condition numéro {i} " + "x" * 200 for i in range(40)]}
        assert len(rag.resume_rag([enorme])) < 2500

    def test_les_listes_sont_coupees_au_lieu_d_etre_tronquees_en_plein_mot(self):
        # Dix documents courts tiennent sous la limite de caractères : c'est le
        # nombre d'éléments qui doit les arrêter, pour ne pas couper une phrase.
        dix = {**FICHE, "documents_requis": [f"papier {i}" for i in range(10)]}
        resume = rag.resume_rag([dix])
        assert "papier 4" in resume and "papier 5" not in resume


class TestCeQuiEstInconnu:
    @pytest.mark.parametrize("colonne", ["cout", "delai", "lieu"])
    def test_une_information_absente_est_annoncee_comme_absente(self, colonne):
        # Un montant inventé fait venir un citoyen avec la mauvaise somme.
        resume = rag.resume_rag([{**FICHE, colonne: None}])
        assert resume.count(rag.INCONNU) == 1

    def test_une_liste_vide_aussi(self):
        assert rag.INCONNU in rag.resume_rag([{**FICHE, "documents_requis": []}])

    def test_la_consigne_dit_quoi_faire_a_la_place(self):
        assert "mairie" in rag.INCONNU


class TestProposerOuNon:
    def test_une_demarche_menable_est_signalee_avec_son_nom_exact(self):
        resume = rag.resume_rag([FICHE])
        assert "Réalisable maintenant avec toi : OUI" in resume
        assert "nom exact à recopier : Constatation de mariage" in resume

    def test_une_demarche_que_l_agent_ne_sait_pas_mener_est_signalee_aussi(self):
        # Proposer de la commencer enverrait le citoyen dans un dialogue
        # qui n'existe pas.
        resume = rag.resume_rag([{**FICHE, "nom_demarche": "Permis de construire"}])
        assert "Réalisable maintenant avec toi : NON" in resume


class TestCorrectionParLaMairie:
    def test_un_tarif_se_corrige(self, monkeypatch):
        ecrits = {}

        class _Table:
            def update(self, valeurs):
                ecrits["valeurs"] = valeurs
                return self

            def eq(self, *_a):
                return self

            def execute(self):
                return type("R", (), {"data": [{"id": "f1", **ecrits["valeurs"]}]})()

        monkeypatch.setattr(informations, "get_supabase_client",
                            lambda: type("C", (), {"table": staticmethod(lambda _n: _Table())})())
        informations.modifier("f1", {"cout": "  3 000 FCFA  "}, par="admin@mairie.sn")
        assert ecrits["valeurs"] == {"cout": "3 000 FCFA"}

    def test_un_tarif_vide_redevient_inconnu(self, monkeypatch):
        # Mieux vaut « je ne sais pas » qu'un ancien tarif devenu faux.
        ecrits = {}
        monkeypatch.setattr(informations, "get_supabase_client",
                            lambda: _client_espion(ecrits))
        informations.modifier("f1", {"cout": "   "})
        assert ecrits["valeurs"]["cout"] is None

    def test_renommer_une_fiche_est_refuse(self):
        # Le nom sert à la retrouver : le changer sans régénérer les vecteurs
        # la rendrait introuvable, en silence.
        with pytest.raises(informations.ModificationRefusee, match="nom_demarche"):
            informations.modifier("f1", {"nom_demarche": "Autre chose"})

    def test_une_demande_vide_est_refusee(self, monkeypatch):
        # Sans client simulé, ce test touchait la VRAIE base et passait pour
        # une autre raison (« fiche introuvable ») — trouvé par mutation.
        ecrits = {}
        monkeypatch.setattr(informations, "get_supabase_client", lambda: _client_espion(ecrits))
        with pytest.raises(informations.ModificationRefusee, match="Aucune modification"):
            informations.modifier("f1", {})
        assert ecrits == {}

    def test_une_liste_est_nettoyee(self, monkeypatch):
        ecrits = {}
        monkeypatch.setattr(informations, "get_supabase_client", lambda: _client_espion(ecrits))
        informations.modifier("f1", {"conditions": ["  premier  ", "", "   ", "second"]})
        assert ecrits["valeurs"]["conditions"] == ["premier", "second"]

    def test_un_texte_demesure_est_refuse(self, monkeypatch):
        ecrits = {}
        monkeypatch.setattr(informations, "get_supabase_client", lambda: _client_espion(ecrits))
        with pytest.raises(informations.ModificationRefusee, match="dépasse"):
            informations.modifier("f1", {"cout": "x" * 3000})
        assert ecrits == {}

    def test_une_entree_de_liste_demesuree_est_refusee(self, monkeypatch):
        ecrits = {}
        monkeypatch.setattr(informations, "get_supabase_client", lambda: _client_espion(ecrits))
        with pytest.raises(informations.ModificationRefusee, match="dépasse"):
            informations.modifier("f1", {"conditions": ["court", "y" * 3000]})
        assert ecrits == {}


def _client_espion(ecrits: dict):
    class _Table:
        def update(self, valeurs):
            ecrits["valeurs"] = valeurs
            return self

        def eq(self, *_a):
            return self

        def execute(self):
            return type("R", (), {"data": [{"id": "f1", **ecrits["valeurs"]}]})()

    return type("C", (), {"table": staticmethod(lambda _n: _Table())})()


class TestRechercheDegradee:
    """
    La recherche sémantique tombe EN SILENCE : le dialogue continue avec une
    recherche par mots-clés, moins précise, et personne ne le sait. C'est ce
    qui est arrivé ici quand le mot de passe de la base a changé sans que le
    `.env` suive.
    """

    def test_quand_elle_repond_le_diagnostic_est_vert(self, monkeypatch):
        # Elle doit RÉPONDRE et TROUVER : une table de vecteurs vide répond
        # sans rien trouver, et ce n'est pas un état sain (cf. plus bas).
        import sys
        faux = type(sys)("search2")
        faux.search_demarches = lambda *_a, **_k: [FICHE]
        monkeypatch.setitem(sys.modules, "search2", faux)
        assert rag.diagnostic()["semantique"] is True

    def test_une_panne_est_expliquee_et_dit_quoi_verifier(self, monkeypatch):
        import sys
        faux = type(sys)("search2")

        def en_panne(*_a, **_k):
            raise ConnectionError("password authentication failed")

        faux.search_demarches = en_panne
        monkeypatch.setitem(sys.modules, "search2", faux)
        etat = rag.diagnostic()
        assert etat["semantique"] is False
        assert "DATABASE_URL" in etat["detail"] and "mots-clés" in etat["detail"]

    def test_le_diagnostic_ne_recopie_jamais_l_url(self, monkeypatch):
        # L'URL porte le mot de passe de la base : elle n'a rien à faire dans
        # une réponse d'API, même réservée aux administrateurs.
        import sys
        faux = type(sys)("search2")

        def en_panne(*_a, **_k):
            raise ConnectionError("postgresql://postgres:motdepasse@db.exemple.co:5432/postgres")

        faux.search_demarches = en_panne
        monkeypatch.setitem(sys.modules, "search2", faux)
        assert "motdepasse" not in rag.diagnostic()["detail"]

    def test_un_diagnostic_ne_fait_jamais_tomber_l_ecran(self, monkeypatch):
        import sys
        monkeypatch.setitem(sys.modules, "search2", None)
        assert rag.diagnostic()["semantique"] is False


class TestRechercheVide:
    """
    Zéro résultat n'est pas une réponse.

    La table des vecteurs était VIDE : la recherche sémantique répondait
    « rien trouvé » sans lever d'erreur, le repli par mots-clés n'était donc
    jamais tenté, et l'agent se retrouvait sans aucune information officielle
    — sans le moindre signe de panne.
    """

    def _moteurs(self, monkeypatch, semantique, mot_cle):
        import sys
        for nom, fonction in (("search2", semantique), ("search", mot_cle)):
            module = type(sys)(nom)
            module.search_demarches = fonction
            monkeypatch.setitem(sys.modules, nom, module)

    def test_sans_resultat_semantique_on_essaie_les_mots_cles(self, monkeypatch):
        self._moteurs(monkeypatch, lambda *_a, **_k: [], lambda *_a, **_k: [FICHE])
        assert rag._rechercher_sync("mariage", None, 3) == [FICHE]

    def test_le_semantique_reste_prioritaire_quand_il_trouve(self, monkeypatch):
        autre = {**FICHE, "nom_demarche": "Trouvé par vecteurs"}
        self._moteurs(monkeypatch, lambda *_a, **_k: [autre],
                      lambda *_a, **_k: pytest.fail("repli inutile"))
        assert rag._rechercher_sync("mariage", None, 3) == [autre]

    def test_le_diagnostic_signale_des_vecteurs_manquants(self, monkeypatch):
        # Le message doit nommer le script : sans lui, l'administrateur voit
        # « dégradé » sans savoir quoi faire.
        import sys
        module = type(sys)("search2")
        module.search_demarches = lambda *_a, **_k: []
        monkeypatch.setitem(sys.modules, "search2", module)
        etat = rag.diagnostic()
        assert etat["semantique"] is False and "seed_embeddings" in etat["detail"]


class TestConfianceDeLaCorrespondance:
    """
    La recherche rend TOUJOURS sa plus proche voisine, pertinente ou non.

    Mesuré sur le modèle d'embeddings du projet : « Bonjour » accroche
    « Extrait de naissance » à 0,493 et « Jaam waali mbadda » à 0,431, quand
    une vraie demande est à 0,749 — sur quinze salutations testées, douze
    franchissent le seuil de 0,35. Sans l'indication de confiance, le modèle
    recevait une fiche de démarche et ne pouvait pas savoir que personne ne
    l'avait demandée : il l'exposait.
    """

    def test_une_correspondance_franche_est_annoncee_fiable(self):
        resume = rag.resume_rag([{**FICHE, "similarite": 0.91}])
        assert "fiable" in resume
        assert "INCERTAINE" not in resume

    def test_une_correspondance_faible_est_annoncee_incertaine(self):
        resume = rag.resume_rag([{**FICHE, "similarite": 0.43}])
        assert "INCERTAINE" in resume
        assert "0.43" in resume

    def test_une_correspondance_incertaine_dit_quoi_faire(self):
        # Signaler le doute sans dire quoi en faire ne changerait rien :
        # l'instruction doit accompagner le chiffre.
        resume = rag.resume_rag([{**FICHE, "similarite": 0.43}])
        assert "SANS RAPPORT" in resume
        assert "demande-lui ce qu'il veut faire" in resume

    @pytest.mark.parametrize("similarite", [None, "", "inconnue"])
    def test_sans_similarite_la_correspondance_est_tenue_pour_fiable(self, similarite):
        # Le repli mot-clé (`search.py`) n'en produit pas : il ne se déclenche
        # que sur des mots réellement prononcés.
        resume = rag.resume_rag([{**FICHE, "similarite": similarite}])
        assert "fiable" in resume
        assert "INCERTAINE" not in resume

    def test_une_correspondance_incertaine_retire_l_invitation_a_proposer(self):
        # « OUI — nom exact à recopier » est un ORDRE : il suffisait à faire
        # proposer une démarche que personne n avait demandée, en contournant
        # l avertissement de la ligne de confiance. Le fait reste transmis,
        # l impératif disparaît.
        resume = rag.resume_rag([{**FICHE, "similarite": 0.43}])
        assert "nom exact à recopier" not in resume
        assert "ne la propose PAS" in resume

    def test_une_correspondance_fiable_garde_l_invitation(self):
        resume = rag.resume_rag([{**FICHE, "similarite": 0.91}])
        assert "nom exact à recopier" in resume

    def test_le_seuil_separe_bien_les_deux_bandes_mesurees(self):
        # Salutations mesurées : 0,43 à 0,49. Vraies demandes : 0,75 et plus.
        assert 0.50 <= rag.SEUIL_CONFIANCE <= 0.70

    def test_les_informations_restent_transmises_meme_incertaines(self):
        # On informe le modèle, on ne lui cache rien : s'il s'avère que le
        # citoyen demandait bien cette démarche, la fiche doit être là.
        resume = rag.resume_rag([{**FICHE, "similarite": 0.43}])
        assert "2 000 FCFA" in resume
        assert "Cartes d'identité des époux" in resume


class TestLePromptNImposePasLaForme:
    """
    Le prompt utilisateur portait « RÉPONSE (structurée : documents,
    conditions, actions - max 4 phrases) : » en DERNIÈRE ligne. Cette consigne
    contredisait la règle 0 du prompt système — qui demande de classer la
    question et de répondre librement à une salutation — et gagnait à tous les
    coups : tour utilisateur plutôt que système, dernière position, à plus de
    mille tokens de la règle qu'elle contredisait.

    Symptôme : « Jaam waali mbadda » (une salutation) recevait la fiche
    complète de l'extrait de naissance.
    """

    def test_le_prompt_ne_prescrit_plus_la_structure(self):
        prompt = build_generator_prompt("Jaam waali mbadda", rag.resume_rag([FICHE]))
        assert "structurée" not in prompt
        assert "documents, conditions, actions" not in prompt

    def test_le_prompt_se_termine_par_une_consigne_neutre(self):
        # La dernière ligne est la position la plus forte : elle ne doit rien
        # imposer que la règle 0 vient de conditionner.
        prompt = build_generator_prompt("Jaam waali mbadda", rag.resume_rag([FICHE]))
        assert prompt.rstrip().endswith("RÉPONSE :")

    def test_la_fiche_est_presentee_comme_la_plus_proche_pas_comme_la_bonne(self):
        prompt = build_generator_prompt("Jaam waali mbadda", rag.resume_rag([FICHE]))
        assert "LA PLUS PROCHE" in prompt

    def test_les_informations_officielles_sont_toujours_transmises(self):
        prompt = build_generator_prompt("Je veux constater un mariage", rag.resume_rag([FICHE]))
        assert "2 000 FCFA" in prompt
        assert "Constatation de mariage" in prompt

    def test_sans_resultat_le_prompt_le_dit_sans_prescrire_de_forme(self):
        prompt = build_generator_prompt("Jaam waali mbadda", rag.resume_rag([]))
        assert "structurée" not in prompt
        assert prompt.rstrip().endswith("RÉPONSE :")

    def test_le_schema_ne_redit_pas_la_structure(self):
        # Troisième renfort de la consigne contradictoire, présent à chaque
        # tour y compris pour une salutation.
        description = SCHEMA_REPONSE_INFORMATION["properties"]["reponse"]["description"]
        assert "documents/conditions/actions" not in description

    def test_la_regle_0_previent_que_la_fiche_peut_etre_hors_sujet(self):
        # Sans cet avertissement, la simple présence d'informations officielles
        # se lit comme « le citoyen demande cette démarche ».
        assert "Correspondance" in SYSTEM_PROMPT_GENERATOR
        assert "INCERTAINE" in SYSTEM_PROMPT_GENERATOR
