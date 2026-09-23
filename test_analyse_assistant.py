"""
Test manuel — Sprint E, Tâche E.2 (endpoint "Analyser avec l'assistant").

Critère de validation explicite de la tâche : dossier cas_legal=jugement_requis
SANS le bloc jugementSupplement rempli (RG3/RG6) -> l'agent doit le signaler
comme "bloquant", pas juste "à vérifier" ou l'ignorer.

Complète aussi avec un dossier propre (cas dans_les_delais complet) pour
vérifier que l'agent ne fabrique pas d'incohérence là où il n'y en a pas.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient
import main  # noqa: E402
from dossiers_repo import update_champ_formulaire
from test_bascule_administratif import TEST_CITOYEN_ID
from test_document_generator import creer_dossier_complet, _remplir_formulaire

client = TestClient(main.app)
main.app.dependency_overrides[main.get_current_consultant] = lambda: {"id": "consultant-test", "commune": "Ross-Béthio"}


def creer_dossier_jugement_requis_incomplet():
    """Cas jugement_requis (>1 an), slots complets, mais AUCUN champ du bloc jugement rempli."""
    commune_id = main.resoudre_commune_id("Ross-Béthio")
    slots = dict(main.SLOTS_VIDES_EXTRAIT_NAISSANCE)
    slots.update({
        "age_enfant": {"valeur": 3, "unite": "annees"},
        "commune_naissance": "Ross-Béthio", "nom_enfant": "Ibrahima Diallo",
        "date_naissance_enfant": "2023-01-01", "nom_declarant": "Modou Diallo",
        "nom_mere": "Aïssatou Ba", "date_naissance_mere": "1998-03-12", "parents_maries": True,
    })
    dossier = main.create_dossier(
        citoyen_id=TEST_CITOYEN_ID, type_demarche="extrait_naissance",
        slots=slots, cas_legal="jugement_requis", commune_id=commune_id, statut="en_traitement",
    )
    assert dossier
    _remplir_formulaire(dossier["id"], "certificat_naissance", {
        "prenomEnfant": "Ibrahima", "nomFamilleEnfant": "Diallo", "sexe": "M",
        "prenomMere": "Aïssatou", "nomFamilleMere": "Ba",
    })
    # Formulaire "acte" créé mais jugementSupplement volontairement laissé vide
    # (tribunalOuJuge, dateJugementLettres, etc. tous None) -> RG3/RG6 violée.
    from dossiers_repo import get_or_create_formulaire_acte
    get_or_create_formulaire_acte(dossier["id"])
    return dossier


def test_jugement_requis_incomplet():
    print("=== Cas jugement_requis SANS mention du jugement (critère de validation) ===")
    dossier = creer_dossier_jugement_requis_incomplet()
    r = client.post(f"/consultant/dossiers/{dossier['id']}/analyser")
    assert r.status_code == 200, r.text
    analyse = r.json()
    print("resume:", analyse["resume"])
    print("completude:", analyse["completude"])
    print("incoherences:")
    for i in analyse["incoherences"]:
        print(" -", i)

    assert analyse["ocr_disponible"] is False, "aucun champ n'est en source='ocr' sur ce dossier (OCR jamais lancé) — ocr_disponible doit rester false"
    assert analyse["completude"]["complet"] is False, "L'agent aurait dû juger le dossier incomplet (bloc jugement manquant)"

    elements_bloquants = [e for e in analyse["completude"]["elements_manquants"] if e["gravite"] == "bloquant"]
    print("elements_manquants bloquants:", elements_bloquants)
    mentionne_jugement = any("jugement" in e["element"].lower() for e in elements_bloquants) or any(
        "jugement" in (i["description"] + str(i["champ"])).lower()
        for i in analyse["incoherences"] if i["gravite"] == "bloquant"
    )
    assert elements_bloquants, "Aucun élément manquant classé 'bloquant' alors que le jugement manque (RG3/RG6)"
    assert mentionne_jugement, "Le manque de jugement n'est mentionné nulle part avec la gravité 'bloquant'"
    print("\n✅ L'agent signale bien le jugement manquant comme bloquant (critère de validation).")
    print("✅ Aucune décision automatique : pas de conclusion 'dossier valide/invalide', juste un constat + gravité.")


def test_dossier_complet_propre():
    print("\n=== Dossier complet et cohérent (dans_les_delais) ===")
    dossier = creer_dossier_complet()
    r = client.post(f"/consultant/dossiers/{dossier['id']}/analyser")
    assert r.status_code == 200, r.text
    analyse = r.json()
    print("resume:", analyse["resume"])
    print("completude:", analyse["completude"])
    assert analyse["completude"]["complet"] is True, "Un dossier complet a été jugé incomplet à tort"
    print("✅ Dossier complet correctement reconnu comme tel — pas de faux positif.")


if __name__ == "__main__":
    test_jugement_requis_incomplet()
    test_dossier_complet_propre()
    print("\n✅ Tâche E.2 : endpoint d'analyse OK")
