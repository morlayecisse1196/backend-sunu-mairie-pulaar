"""
Test manuel — Tâche 7.5 mobile (backend) : POST /mes-dossiers/{id}/document/audio,
narration pulaar du CONTENU du document généré (pas son statut, Tâche 7.4).

weasyprint est bloqué en local (cf. avertissement document_generator.py, pas de
Pango/Cairo sous Windows) — comme test_document_generator.py, ce test insère
directement une ligne `documents_generes` (create_document_genere) plutôt que
d'appeler le vrai generer_document() : suffisant ici, l'endpoint ne lit QUE
cette ligne pour savoir qu'un document existe, puis reconstruit la phrase
depuis resoudre_template() (dossier + formulaires), indépendant de weasyprint.

Réutilise creer_dossier_complet() de test_document_generator.py (mêmes
valeurs connues : Marya Ndoye, née le 14/10/1967 à Ross-Béthio, fille de
Babacar et Salimata Diop) pour vérifier RÉELLEMENT que la phrase résumée
contient les bonnes informations, pas juste que l'endpoint répond 200.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient

import main  # noqa: E402
from dossiers_repo import get_commune, list_document_formulaires, get_or_create_formulaire_acte, create_document_genere
from document_generator import resoudre_template, construire_resume_document_genere
from test_bascule_administratif import TEST_CITOYEN_ID, TEST_COMMUNE
from test_document_generator import creer_dossier_complet

client = TestClient(main.app)


def main_test():
    print("=== 1. Sans document généré -> 404 explicite ===")
    dossier_vide = main.create_dossier(
        citoyen_id=TEST_CITOYEN_ID, type_demarche="extrait_naissance",
        slots=dict(main.SLOTS_VIDES_EXTRAIT_NAISSANCE), cas_legal="dans_les_delais",
        commune_id=main.resoudre_commune_id(TEST_COMMUNE), statut="en_traitement",
    )
    assert dossier_vide
    main.app.dependency_overrides[main.get_current_user] = lambda: {"id": TEST_CITOYEN_ID, "commune": TEST_COMMUNE}
    r_404 = client.post(f"/mes-dossiers/{dossier_vide['id']}/document/audio")
    assert r_404.status_code == 404, r_404.text
    print(f"OK - 404 explicite : {r_404.json()['detail']}\n")

    print("=== 2. Vérifie d'abord la phrase FR construite (unitaire, sans réseau) ===")
    dossier = creer_dossier_complet()
    commune = get_commune(dossier["commune_id"])
    formulaires = list_document_formulaires(dossier["id"])
    formulaire_acte = get_or_create_formulaire_acte(dossier["id"])
    if formulaire_acte and not any(f["id"] == formulaire_acte["id"] for f in formulaires):
        formulaires.append(formulaire_acte)
    champs_formulaire = {}
    for f in formulaires:
        for champ in f["champs"]:
            if champ["valeur"] is not None:
                champs_formulaire[champ["nom"]] = champ["valeur"]
    valeurs, erreurs = resoudre_template(dossier, commune, champs_formulaire, jugement_requis=False)
    assert not erreurs, f"resoudre_template a échoué, phrase impossible à tester : {erreurs}"
    phrase_fr = construire_resume_document_genere(valeurs)
    print("Phrase FR construite :", phrase_fr)
    assert "Marya Ndoye" in phrase_fr
    assert "née" in phrase_fr  # sexe=F
    assert "quatorze octobre mille neuf cent soixante sept" in phrase_fr
    assert "Ross-Béthio" in phrase_fr
    assert "Babacar" in phrase_fr and "Salimata Diop" in phrase_fr
    print("OK - la phrase contient bien toutes les informations réelles du dossier.\n")

    print("=== 3. Endpoint réel POST /mes-dossiers/{id}/document/audio ===")
    document_genere = create_document_genere(
        dossier["id"], template_utilise="extrait_naissance_v1", version=1,
        contenu_url=f"{dossier['id']}/v1.pdf", statut="genere",
    )
    assert document_genere, "création de documents_generes échouée (fixture de test)"

    r = client.post(f"/mes-dossiers/{dossier['id']}/document/audio")
    assert r.status_code == 200, r.text
    assert len(r.content) > 1000, f"audio suspicieusement petit ({len(r.content)} octets)"
    assert r.headers.get("content-type") == "audio/wav"
    print(f"OK - audio réel généré : {len(r.content)} octets.\n")

    print("=== 4. Second appel -> servi depuis le cache disque (par document_genere_id) ===")
    import os
    cache_path = os.path.join(main.AUDIO_CACHE_DIR, f"document_genere_{document_genere['id']}.wav")
    assert os.path.exists(cache_path), "le fichier de cache n'a pas été écrit"
    r2 = client.post(f"/mes-dossiers/{dossier['id']}/document/audio")
    assert r2.status_code == 200
    assert r2.content == r.content, "le contenu du 2e appel diffère du 1er alors que le cache existe"
    print("OK - cache disque confirmé (contenu identique, réponse instantanée).\n")

    print("=== 5. Isolation : un autre citoyen ne peut pas narrer ce dossier ===")
    main.app.dependency_overrides[main.get_current_user] = lambda: {"id": "un-autre-citoyen-uuid", "commune": TEST_COMMUNE}
    r_interdit = client.post(f"/mes-dossiers/{dossier['id']}/document/audio")
    assert r_interdit.status_code == 403, r_interdit.text
    print(f"OK - 403 pour un autre citoyen : {r_interdit.json()['detail']}")

    main.app.dependency_overrides.clear()
    print("\n✅ Tâche 7.5 (backend) validée : phrase fidèle au contenu réel, audio réel, cache par document, isolation par citoyen.")


if __name__ == "__main__":
    main_test()
