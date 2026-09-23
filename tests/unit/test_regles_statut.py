import pytest

from services.regles_statut import RefusStatut, verifier_action_consultant

ACTIONS_ECRITURE = ["modifier_formulaire", "ocr", "creer_cas", "resoudre_cas", "generer"]


@pytest.mark.parametrize("statut", ["finalise", "bloque", "en_cours", "en_attente_validation_citoyen"])
@pytest.mark.parametrize("action", ACTIONS_ECRITURE + ["valider"])
def test_ecritures_refusees_hors_traitement(statut, action):
    with pytest.raises(RefusStatut):
        verifier_action_consultant(statut, action)


@pytest.mark.parametrize("statut", ["en_traitement", "corrections_demandees", "genere", "recu"])
@pytest.mark.parametrize("action", ACTIONS_ECRITURE)
def test_ecritures_autorisees_pendant_le_traitement(statut, action):
    verifier_action_consultant(statut, action)


def test_valider_uniquement_depuis_genere():
    verifier_action_consultant("genere", "valider")
    with pytest.raises(RefusStatut) as exc:
        verifier_action_consultant("en_traitement", "valider")
    assert exc.value.code == "validation_impossible"


@pytest.mark.parametrize("statut", ["finalise", "bloque", "en_attente_validation_citoyen", "genere"])
def test_analyser_reste_possible_en_lecture(statut):
    verifier_action_consultant(statut, "analyser")


def test_analyser_refuse_sur_dossier_non_confirme():
    with pytest.raises(RefusStatut):
        verifier_action_consultant("en_cours", "analyser")
