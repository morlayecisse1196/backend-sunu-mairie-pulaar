import json

from temps_reel.etat import ajouter_historique, deserialiser, instantane_client, nouvel_etat, serialiser, HISTORIQUE_MAX_ENTREES


def _etat():
    return nouvel_etat(session_id="s-1", cle_client="cle-app", citoyen_id="c-1", commune_profil="Ross-Béthio")


def test_aller_retour_base_sans_perte():
    etat = _etat()
    etat.update(mode="administratif", phase="relecture_en_cours", dossier_id="d-1", numero_suivi=None)
    etat["slots"]["nom_enfant"] = "Ibrahima Diallo"
    etat["documents_demandes"].update({"cni_declarant_recto", "certificat_naissance"})
    etat["documents_ignores"].add("livret_famille")
    etat["compteurs_echecs"]["nom_mere"] = 2

    ligne = serialiser(etat)
    json.dumps(ligne)  # doit être du JSON pur (aucun set)
    assert ligne["mode"] == "administratif" and ligne["dossier_id"] == "d-1"
    assert ligne["etat"]["documents_demandes"] == ["certificat_naissance", "cni_declarant_recto"]

    relu = deserialiser(json.loads(json.dumps(ligne)))
    assert relu["documents_demandes"] == {"certificat_naissance", "cni_declarant_recto"}
    assert relu["documents_ignores"] == {"livret_famille"}
    assert relu["slots"]["nom_enfant"] == "Ibrahima Diallo"
    assert relu["compteurs_echecs"] == {"nom_mere": 2}
    assert relu["phase"] == "relecture_en_cours"


def test_etat_ancien_complete_par_defaut():
    ligne = {"id": "s-2", "citoyen_id": "c-1", "cle_client": "k", "mode": "information", "phase": "collecte", "etat": {}}
    etat = deserialiser(ligne)
    assert etat["documents_demandes"] == set()
    assert etat["slots"]["age_enfant"] == {"valeur": None, "unite": None}
    assert etat["nb_iterations_correction"] == 0


def test_valeurs_invalides_ramenees_a_un_etat_sur():
    ligne = {"id": "s-3", "citoyen_id": "c-1", "cle_client": "k", "mode": "pirate", "phase": "??", "etat": {}}
    etat = deserialiser(ligne)
    assert etat["mode"] == "information" and etat["phase"] == "collecte"


def test_historique_borne():
    etat = _etat()
    for i in range(30):
        ajouter_historique(etat, "user", f"message {i}")
    assert len(etat["historique"]) == HISTORIQUE_MAX_ENTREES
    assert etat["historique"][-1]["content"] == "message 29"


def test_instantane_client_n_expose_pas_les_slots():
    etat = _etat()
    etat["slots"]["nom_mere"] = "Aïssatou Ba"
    instantane = instantane_client(etat)
    assert "slots" not in instantane and "historique" not in instantane
    assert instantane["session_id"] == "s-1"
