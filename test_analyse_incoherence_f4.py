"""
Test manuel — Sprint F, Tâche F.4 : prépare un dossier de test avec une
INCOHÉRENCE VOLONTAIRE (nomFamilleMere du formulaire certificat_naissance =
"Sow", saisi manuellement, alors que le dialogue vocal a enregistré
nom_mere = "Salimata Diop" — donc famille "Diop"), en suivant le VRAI flux
(upload de document réel -> auto-création du formulaire via l'endpoint C.3
-> correction manuelle, exactement ce que fait l'écran F.3/F.4), appelle le
vrai endpoint /analyser (E.2), vérifie que l'assistant la signale avec une
valeur_suggeree exploitable, puis simule le clic « Accepter la suggestion »
via l'endpoint PATCH existant (C.3) et vérifie que le bon champ est modifié.

Ne teste PAS le rendu React (pas de navigateur ici) — valide la chaîne
backend dont dépend entièrement le bouton "Accepter la suggestion" du F.4.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient
import main  # noqa: E402
from test_bascule_administratif import TEST_CITOYEN_ID

TOKEN = "override-dependance-pas-de-vrai-jwt-necessaire"
FAUX_JPEG = b"\xff\xd8\xff\xe0" + b"CECI_EST_UNE_FAUSSE_PHOTO_DE_TEST" * 20

client = TestClient(main.app)


def creer_dossier_avec_incoherence():
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

    # 1. Upload réel (comme le ferait le citoyen/consultant) -> crée la ligne `documents`.
    main.app.dependency_overrides[main.get_current_user] = lambda: {"id": TEST_CITOYEN_ID, "commune": "Ross-Béthio"}
    r_upload = client.post(
        f"/dossiers/{dossier_id}/documents",
        data={"type": "certificat_naissance"},
        files={"fichier": ("certificat.jpg", FAUX_JPEG, "image/jpeg")},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert r_upload.status_code == 200, r_upload.text
    del main.app.dependency_overrides[main.get_current_user]

    # 2. Auto-création du formulaire via le VRAI endpoint C.3 (celui que le
    #    frontend F.3/F.4 appelle), pré-rempli depuis les slots.
    main.app.dependency_overrides[main.get_current_consultant] = lambda: {"id": "consultant-test", "commune": "Ross-Béthio"}
    r_formulaires = client.get(f"/consultant/dossiers/{dossier_id}/formulaires")
    assert r_formulaires.status_code == 200, r_formulaires.text
    formulaire = next(f for f in r_formulaires.json()["formulaires"] if f["type_document"] == "certificat_naissance")

    # 3. Complète les champs manuels + INTRODUIT l'incohérence volontaire :
    #    dialogue dit la mère "Diop", le consultant tape "Sow" par erreur.
    for nom, valeur in {
        "prenomEnfant": "Marya", "nomFamilleEnfant": "Ndoye", "sexe": "F",
        "prenomPere": "Babacar", "prenomMere": "Salimata",
        "nomFamilleMere": "Sow",  # <-- incohérence volontaire (attendu: "Diop")
    }.items():
        r_patch = client.patch(
            f"/consultant/dossiers/{dossier_id}/formulaires/{formulaire['id']}",
            json={"nom": nom, "valeur": valeur},
        )
        assert r_patch.status_code == 200, r_patch.text

    return dossier_id


def main_test():
    dossier_id = creer_dossier_avec_incoherence()
    print(f"📁 Dossier de test (incohérence volontaire) : {dossier_id}")

    print("\n=== POST /consultant/dossiers/{id}/analyser ===")
    r = client.post(f"/consultant/dossiers/{dossier_id}/analyser")
    assert r.status_code == 200, r.text
    analyse = r.json()
    print("Résumé :", analyse["resume"])
    print("\nIncohérences détectées :")
    for i in analyse["incoherences"]:
        print(f"  - champ={i['champ']!r} gravite={i['gravite']!r} valeur_suggeree={i.get('valeur_suggeree')!r}")
        print(f"    description: {i['description']}")
        print(f"    options: {i['options_proposees']}")

    incoherence_mere = next(
        (i for i in analyse["incoherences"] if i.get("champ") == "nomFamilleMere"), None
    )
    assert incoherence_mere, (
        "L'assistant n'a PAS détecté l'incohérence volontaire sur nomFamilleMere "
        "(dialogue: 'Diop' vs formulaire manuel: 'Sow')."
    )
    print(f"\n✅ Incohérence sur 'nomFamilleMere' bien détectée (gravité: {incoherence_mere['gravite']}).")

    valeur_suggeree = incoherence_mere.get("valeur_suggeree")
    assert valeur_suggeree, "valeur_suggeree est vide — le bouton « Accepter la suggestion » n'aurait rien à appliquer."
    print(f"✅ valeur_suggeree exploitable présente : {valeur_suggeree!r}")

    # --- Simule le clic "Accepter la suggestion" (ce que fera le bouton React) ---
    formulaires = client.get(f"/consultant/dossiers/{dossier_id}/formulaires").json()["formulaires"]
    formulaire_cible = next(f for f in formulaires if any(c["nom"] == "nomFamilleMere" for c in f["champs"]))

    print(f"\n=== PATCH (« Accepter la suggestion ») : nomFamilleMere -> {valeur_suggeree!r} ===")
    r_patch = client.patch(
        f"/consultant/dossiers/{dossier_id}/formulaires/{formulaire_cible['id']}",
        json={"nom": "nomFamilleMere", "valeur": valeur_suggeree},
    )
    assert r_patch.status_code == 200, r_patch.text
    resultat = r_patch.json()
    champ_maj = next(c for c in resultat["champs"] if c["nom"] == "nomFamilleMere")
    print("Champ après acceptation :", champ_maj)
    assert champ_maj["valeur"] == valeur_suggeree, "Le bon champ n'a pas été modifié avec la bonne valeur !"
    assert champ_maj["source"] == "manuel", "La source doit rester 'manuel' (jamais une source 'llm', cf. critère F.4)."

    # Vérifie aussi qu'AUCUN AUTRE champ n'a été touché par erreur (ex. prenomMere).
    autre_champ = next(c for c in resultat["champs"] if c["nom"] == "prenomMere")
    assert autre_champ["valeur"] == "Salimata", "Un autre champ a été modifié par erreur !"

    print("✅ « Accepter la suggestion » modifie bien LE BON champ (et lui seul), source reste 'manuel' (pas 'llm').")

    print("\n✅ Tâche F.4 (chaîne backend) : incohérence détectée + acceptation fonctionnelle — OK")


if __name__ == "__main__":
    main_test()
