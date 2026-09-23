"""
Test manuel — Sprint mobile, Tâche 7.4 (pré-requis backend).
POST /mes-dossiers/{dossier_id}/audio — narration pulaar du statut d'un dossier.

Critères de validation manuelle explicites (FLUTTER_APP_PROMPTS.md, Tâche 7.4) :
  - Narration correcte pour un dossier en_attente_validation_citoyen.
  - Deux dossiers DIFFÉRENTS avec le MÊME statut -> pas de re-synthèse au 2e
    appel (cache par couple (type_demarche, statut), pas par dossier_id).

Aucun mock pour le premier appel (vrai LLM + vrai TTS) ; le 2e appel doit être
quasi instantané (servi depuis le cache disque) — c'est le vrai critère testé.
"""
import os
import time
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient

import main  # noqa: E402
from dossiers_repo import create_dossier
from test_bascule_administratif import TEST_CITOYEN_ID, TEST_COMMUNE

SLOTS_VIDES = {
    "age_enfant": {"valeur": None, "unite": None}, "commune_naissance": None, "nom_enfant": None,
    "date_naissance_enfant": None, "nom_declarant": None, "nom_mere": None,
    "date_naissance_mere": None, "parents_maries": None,
}


def main_test():
    client = TestClient(main.app)
    main.app.dependency_overrides[main.get_current_user] = lambda: {"id": TEST_CITOYEN_ID, "commune": TEST_COMMUNE}

    # Nettoyage préalable du cache pour ce couple, afin de tester réellement la 1ère synthèse.
    cache_path = os.path.join(main.AUDIO_CACHE_DIR, "dossier_extrait_naissance_en_traitement.wav")
    if os.path.exists(cache_path):
        os.remove(cache_path)
        print(f"(cache existant supprimé pour repartir d'un état propre : {cache_path})")

    dossier1 = create_dossier(
        citoyen_id=TEST_CITOYEN_ID, type_demarche="extrait_naissance",
        slots=dict(SLOTS_VIDES), cas_legal="dans_les_delais", commune_id=None, statut="en_traitement",
    )
    dossier2 = create_dossier(
        citoyen_id=TEST_CITOYEN_ID, type_demarche="extrait_naissance",
        slots=dict(SLOTS_VIDES), cas_legal="dans_les_delais", commune_id=None, statut="en_traitement",
    )
    assert dossier1 and dossier2
    print(f"Dossier 1 : {dossier1['id']}\nDossier 2 : {dossier2['id']} (même statut 'en_traitement')\n")

    # --- 1er appel (dossier 1) : vraie synthèse (LLM + TTS) ---
    t0 = time.monotonic()
    r1 = client.post(f"/mes-dossiers/{dossier1['id']}/audio")
    duree1 = time.monotonic() - t0
    print(f"Appel 1 (dossier 1, PAS encore en cache) -> {r1.status_code} en {duree1:.1f}s, {len(r1.content)} octets")
    assert r1.status_code == 200, r1.text
    assert r1.headers["content-type"] == "audio/wav"
    assert len(r1.content) > 0
    assert os.path.exists(cache_path), "le fichier de cache n'a pas été créé"

    # --- 2e appel (dossier 2, statut identique, dossier DIFFÉRENT) : doit venir du cache ---
    t1 = time.monotonic()
    r2 = client.post(f"/mes-dossiers/{dossier2['id']}/audio")
    duree2 = time.monotonic() - t1
    print(f"Appel 2 (dossier 2, MÊME statut, dossier différent) -> {r2.status_code} en {duree2:.1f}s, {len(r2.content)} octets")
    assert r2.status_code == 200
    assert r2.content == r1.content, "le contenu audio devrait être IDENTIQUE (même couple type_demarche/statut)"
    assert duree2 < 2.0, (
        f"le 2e appel a pris {duree2:.1f}s — devrait être quasi instantané (servi depuis le cache), "
        f"pas une resynthèse (le 1er appel a pris {duree1:.1f}s)"
    )
    print(f"\nOK - 2e appel {duree1 / max(duree2, 0.01):.0f}x plus rapide que le 1er : bien servi depuis le cache "
          f"par (type_demarche, statut), pas par dossier_id.")

    # --- Vérification 403 : dossier d'un autre citoyen ---
    main.app.dependency_overrides[main.get_current_user] = lambda: {"id": "00000000-0000-0000-0000-000000000000", "commune": "National"}
    r3 = client.post(f"/mes-dossiers/{dossier1['id']}/audio")
    assert r3.status_code == 403, f"attendu 403 pour un dossier d'un autre citoyen, obtenu {r3.status_code}"
    print("OK - 403 si le dossier n'appartient pas au citoyen connecté.")

    main.app.dependency_overrides.clear()
    print("\nPré-requis backend Tâche 7.4 validé : narration réelle + cache par (type_demarche, statut).")


if __name__ == "__main__":
    main_test()
