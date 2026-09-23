import pytest

from services import notifications, push_fcm
from services.evenements import Transition


def _transition(statut, acteur_type="consultant", acteur_id="agent-1", **dossier):
    return Transition(
        dossier_id="d-1", statut_avant=None, statut_apres=statut, acteur_type=acteur_type, acteur_id=acteur_id,
        libelle="x", dossier={"citoyen_id": "citoyen-1", "commune_id": "commune-1", "numero_suivi": "SM-2026-000452", **dossier},
    )


@pytest.mark.parametrize(
    "statut, acteur, roles_attendus",
    [
        ("recu", "citoyen", ["consultant"]),
        ("en_traitement", "consultant", ["citoyen"]),
        ("en_traitement", "admin", ["consultant"]),
        ("en_attente_validation_citoyen", "consultant", ["citoyen"]),
        ("corrections_demandees", "citoyen", ["consultant"]),
        ("finalise", "citoyen", ["consultant"]),
        ("bloque", "systeme", ["admin", "consultant", "citoyen"]),
        ("genere", "consultant", []),
    ],
)
def test_politique_de_notification(statut, acteur, roles_attendus):
    annonces = notifications.annonces_pour_transition(_transition(statut, acteur_type=acteur))
    assert [a.role for a in annonces] == roles_attendus


def test_numero_de_suivi_dans_le_titre_agent():
    annonce = notifications.annonces_pour_transition(_transition("recu", acteur_type="citoyen"))[0]
    assert "SM-2026-000452" in annonce.titre


async def test_sur_transition_cible_les_bons_destinataires_sans_notifier_l_auteur(monkeypatch):
    envois = []

    async def faux_notifier(destinataires, annonce, dossier_id):
        envois.append((annonce.role, sorted(destinataires)))
        return len(destinataires)

    monkeypatch.setattr(notifications, "notifier", faux_notifier)
    monkeypatch.setattr(notifications, "_consultants_de_la_commune_sync", lambda commune_id: ["agent-1", "agent-2"])
    monkeypatch.setattr(notifications, "_administrateurs_sync", lambda: ["admin-1"])

    await notifications.sur_transition(_transition("bloque", acteur_type="systeme", acteur_id=None))
    assert envois == [("admin", ["admin-1"]), ("consultant", ["agent-1", "agent-2"]), ("citoyen", ["citoyen-1"])]

    envois.clear()
    await notifications.sur_transition(_transition("corrections_demandees", acteur_type="citoyen", acteur_id="citoyen-1"))
    assert envois == [("consultant", ["agent-1", "agent-2"])]


def test_liens_par_role():
    assert notifications.lien("consultant", "d-1") == "/consultant/dossiers/d-1"
    assert notifications.lien("admin", "d-1") == "/admin/dossiers/d-1"
    assert notifications.lien("citoyen", "d-1") == "/mes-dossiers/d-1"


async def test_push_sans_configuration_ne_fait_rien(monkeypatch):
    monkeypatch.delenv("FCM_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("FCM_SERVICE_ACCOUNT_FILE", raising=False)
    push_fcm.reinitialiser()
    assert push_fcm.est_configure() is False
    assert await push_fcm.envoyer(["jeton"], "titre", "corps", {}) == []
    push_fcm.reinitialiser()


def test_message_fcm_donnees_en_chaines():
    message = push_fcm.construire_message("jeton", "Votre document est prêt", "Écoutez-le", {"dossier_id": "d-1", "version": 2, "vide": None})
    assert message["message"]["data"] == {"dossier_id": "d-1", "version": "2"}
    assert message["message"]["android"]["priority"] == "high"
