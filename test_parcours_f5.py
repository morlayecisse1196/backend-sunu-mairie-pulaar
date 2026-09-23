"""
Test manuel — Sprint F, Tâche F.5. Critère de validation explicite : parcours
complet sur un dossier de test — analyse -> résolution d'un cas particulier
-> génération -> validation -> vérifier en base que le statut passe bien à
`en_attente_validation_citoyen`, PAS `finalise` directement.

Utilise un dossier volontairement INCOMPLET au départ (comme test_document_generator
D.2) pour que la première tentative de génération échoue réellement et
journalise un vrai cas particulier (pas un cas fabriqué à la main) — exactement
le parcours qu'un consultant suivrait en vrai.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient
import main  # noqa: E402
from dossiers_repo import get_dossier, get_or_create_formulaire_acte, update_champ_formulaire, list_document_formulaires
from test_bascule_administratif import TEST_CITOYEN_ID

TOKEN = "override-dependance-pas-de-vrai-jwt-necessaire"
FAUX_JPEG = b"\xff\xd8\xff\xe0" + b"CECI_EST_UNE_FAUSSE_PHOTO_DE_TEST" * 20

client = TestClient(main.app)


def creer_dossier_incomplet():
    """Dossier 'tardif' avec slots dialogue complets, mais formulaire manuel
    (prenomEnfant, nomFamilleEnfant, sexe, prenomPere, prenomMere,
    nomFamilleMere...) volontairement VIDE -> la génération va échouer."""
    commune_id = main.resoudre_commune_id("Ross-Béthio")
    slots = dict(main.SLOTS_VIDES_EXTRAIT_NAISSANCE)
    slots.update({
        "age_enfant": {"valeur": 3, "unite": "mois"},
        "commune_naissance": "Ross-Béthio", "nom_enfant": "Marya Ndoye",
        "date_naissance_enfant": "1967-10-14", "nom_declarant": "Babacar Diop",
        "nom_mere": "Salimata Diop", "date_naissance_mere": "1940-01-01", "parents_maries": True,
    })
    dossier = main.create_dossier(
        citoyen_id=TEST_CITOYEN_ID, type_demarche="extrait_naissance",
        slots=slots, cas_legal="tardif", commune_id=commune_id, statut="en_traitement",
    )
    assert dossier
    dossier_id = dossier["id"]

    main.app.dependency_overrides[main.get_current_user] = lambda: {"id": TEST_CITOYEN_ID, "commune": "Ross-Béthio"}
    r = client.post(
        f"/dossiers/{dossier_id}/documents",
        data={"type": "certificat_naissance"},
        files={"fichier": ("certificat.jpg", FAUX_JPEG, "image/jpeg")},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert r.status_code == 200, r.text
    del main.app.dependency_overrides[main.get_current_user]

    # Déclenche l'auto-création du document_formulaire (endpoint C.3, celui
    # que le frontend F.3 appelle en ouvrant l'écran) — sans cet appel, aucun
    # formulaire n'existe encore pour le document uploadé ci-dessus.
    main.app.dependency_overrides[main.get_current_consultant] = lambda: {"id": "consultant-test", "commune": "Ross-Béthio"}
    r_form = client.get(f"/consultant/dossiers/{dossier_id}/formulaires")
    assert r_form.status_code == 200, r_form.text

    return dossier_id


def main_test():
    main.app.dependency_overrides[main.get_current_consultant] = lambda: {"id": "consultant-test", "commune": "Ross-Béthio"}

    dossier_id = creer_dossier_incomplet()
    print(f"📁 Dossier de test (parcours F.5) : {dossier_id}")

    # --- 1. Analyse ------------------------------------------------------------
    print("\n=== 1. POST /analyser ===")
    r_analyse = client.post(f"/consultant/dossiers/{dossier_id}/analyser")
    assert r_analyse.status_code == 200, r_analyse.text
    print("✅ Analyse effectuée, complet =", r_analyse.json()["completude"]["complet"])

    # --- 2. Première génération : DOIT échouer (champs manquants) --------------
    print("\n=== 2. POST /generer (attendu : 422, champs manquants) ===")
    r_gen1 = client.post(f"/consultant/dossiers/{dossier_id}/generer")
    assert r_gen1.status_code == 422, r_gen1.text
    print("✅ Génération bloquée comme attendu :", r_gen1.json()["detail"]["message"])

    # --- 3. Un cas particulier a dû être journalisé automatiquement ------------
    print("\n=== 3. GET /cas-particuliers (doit contenir le cas auto-créé) ===")
    r_cas = client.get(f"/consultant/dossiers/{dossier_id}/cas-particuliers")
    assert r_cas.status_code == 200
    cas_liste = r_cas.json()["cas_particuliers"]
    assert cas_liste, "Aucun cas particulier journalisé alors que la génération a échoué !"
    cas = cas_liste[0]
    assert cas["resolu_le"] is None
    print(f"✅ Cas particulier trouvé : type_incident={cas['type_incident']!r}")

    # --- 4. Résolution du cas particulier (le consultant choisit une option) ---
    print("\n=== 4. Résolution du cas particulier ===")
    decision = cas["options_proposees"][0]
    r_resoudre = client.post(
        f"/consultant/dossiers/{dossier_id}/cas-particuliers/{cas['id']}/resoudre",
        json={"decision_consultant": decision},
    )
    assert r_resoudre.status_code == 200, r_resoudre.text
    assert r_resoudre.json()["resolu_le"] is not None
    print(f"✅ Cas particulier résolu : décision = {decision!r}")

    # --- 5. Le consultant complète effectivement les champs manquants ----------
    print("\n=== 5. Complétion des champs manquants (via PATCH, comme F.3) ===")
    formulaires = list_document_formulaires(dossier_id)
    formulaire_certificat = next(f for f in formulaires if f["type_document"] == "certificat_naissance")
    for nom, valeur in {
        "prenomEnfant": "Marya", "nomFamilleEnfant": "Ndoye", "sexe": "F",
        "prenomPere": "Babacar", "prenomMere": "Salimata", "nomFamilleMere": "Diop",
        "dateNaissanceLettres": "quatorze octobre mille neuf cent soixante sept",
    }.items():
        r_patch = client.patch(
            f"/consultant/dossiers/{dossier_id}/formulaires/{formulaire_certificat['id']}",
            json={"nom": nom, "valeur": valeur},
        )
        assert r_patch.status_code == 200, r_patch.text
    formulaire_acte = get_or_create_formulaire_acte(dossier_id)
    for nom, valeur in {
        "numeroActe": "0000000000000000194", "anneeRegistreLettres": "Mille neuf cent soixante sept",
        "anneeRegistreChiffres": "1967", "numeroRegistreLettres": "Cent quatre vingt quatorze",
        "numeroRegistreChiffres": "194", "officierEtatCivil": "Gorgui Mbodji",
    }.items():
        formulaire_acte = update_champ_formulaire(formulaire_acte, nom, valeur=valeur)
    print("✅ Champs complétés.")

    # --- 6. Seconde génération : doit réussir cette fois ------------------------
    print("\n=== 6. POST /generer (attendu : 200) ===")
    r_gen2 = client.post(f"/consultant/dossiers/{dossier_id}/generer")
    assert r_gen2.status_code == 200, r_gen2.text
    print(f"✅ Document généré (version {r_gen2.json()['version']}).")

    dossier_apres_generation = get_dossier(dossier_id)
    assert dossier_apres_generation["statut"] == "genere", dossier_apres_generation["statut"]
    print(f"✅ Statut du dossier en base après génération : {dossier_apres_generation['statut']!r}")

    # --- 7. Validation (envoi au citoyen) ---------------------------------------
    print("\n=== 7. POST /valider ===")
    r_valider = client.post(f"/consultant/dossiers/{dossier_id}/valider")
    assert r_valider.status_code == 200, r_valider.text
    print("Réponse :", r_valider.json())

    # --- 8. VÉRIFICATION EN BASE (critère de validation explicite) -------------
    dossier_final = get_dossier(dossier_id)
    print(f"\n📋 Statut final EN BASE : {dossier_final['statut']!r}")
    assert dossier_final["statut"] == "en_attente_validation_citoyen", (
        f"Le dossier devrait être 'en_attente_validation_citoyen', pas {dossier_final['statut']!r} !"
    )
    assert dossier_final["statut"] != "finalise", "Le dossier a été finalisé directement — INTERDIT (Flux §2.7) !"
    print("✅ Statut en base = 'en_attente_validation_citoyen', PAS 'finalise' — critère de validation respecté.")

    # --- 9. Une 2e validation sans nouvelle génération doit être refusée --------
    print("\n=== 9. POST /valider une 2e fois (attendu : 400, déjà envoyé) ===")
    r_valider2 = client.post(f"/consultant/dossiers/{dossier_id}/valider")
    assert r_valider2.status_code == 400, r_valider2.text
    print("✅ Double validation sans nouvelle génération correctement refusée :", r_valider2.json()["detail"])

    print("\n✅ Tâche F.5 : parcours complet (analyse -> cas particulier -> génération -> validation) — OK")


if __name__ == "__main__":
    main_test()
