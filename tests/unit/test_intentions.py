import pytest

from temps_reel.intentions import classer_confirmation, est_reponse_affirmative


@pytest.mark.parametrize(
    "phrase",
    [
        "Oui",
        "oui oui",
        "Oui, c'est bon",
        "C’est exact",
        "D'accord",
        "ok",
        "C'est correct",
        "Pas de problème, c'est bon",
        "Tout est juste",
        "Eyyi",
    ],
)
def test_confirmations_nettes(phrase):
    assert classer_confirmation(phrase) == "oui"
    assert est_reponse_affirmative(phrase) is True


@pytest.mark.parametrize(
    "phrase",
    [
        # Cas réels qui étaient lus comme « oui » par l'ancienne implémentation.
        "Non, ce n'est pas correct",
        "Non ce n'est pas exact, la date est fausse",
        "Je ne suis pas d'accord",
        "Oui mais le nom du père est faux",
        "Pas ok du tout",
        "Non",
        "c'est incorrect",
        "Attendez, il faut corriger la date",
        "alaa",
    ],
)
def test_refus_et_reserves(phrase):
    assert classer_confirmation(phrase) == "non"
    assert est_reponse_affirmative(phrase) is False


@pytest.mark.parametrize("phrase", ["", "   ", None, "euh", "Ibrahima Diallo", "recommençons"])
def test_incertain_jamais_confirme(phrase):
    assert classer_confirmation(phrase) == "incertain"
    assert est_reponse_affirmative(phrase) is False


def test_mot_affirmatif_a_l_interieur_d_un_autre_mot_ne_compte_pas():
    # « correct » dans « incorrect », « commençons » dans « recommençons ».
    assert classer_confirmation("incorrect") == "non"
    assert classer_confirmation("recommençons") == "incertain"
