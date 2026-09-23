"""
Test manuel — Sprint G, Tâche G.3 (déclenchement du statut 'bloque' + écran
de supervision). Critère de validation explicite : un dossier de test poussé
à 3 itérations de correction (cf. B.4) apparaît bien dans la liste des
dossiers bloqués de GET /admin/supervision.

Même limite que test_relecture_confirmation.py (B.4) : le WS réel
(main.py websocket_endpoint) n'accepte que de l'audio (transcrit via l'API
ASR externe), "pas de micro disponible ici" — donc ce test reproduit fidèlement
la logique de la boucle WS (mode administratif) en Python pur, comme le fait
déjà tour_administratif() de B.4, plutôt que d'ouvrir une vraie connexion WS.
La logique reproduite ici (compteur, seuil, passage à 'bloque') est une copie
fidèle de main.py (bloc "elif etat['mode'] == 'administratif':", Tâche G.3),
pas une réimplémentation indépendante qui pourrait diverger silencieusement.
"""
import asyncio
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient
import main  # noqa: E402
from dossiers_repo import get_dossier
from test_bascule_administratif import appeler_generateur, TEST_CITOYEN_ID, TEST_COMMUNE
from test_relecture_confirmation import tour_administratif  # reproduction fidèle de B.4, réutilisée telle quelle

client = TestClient(main.app)
main.app.dependency_overrides[main.get_current_admin] = lambda: {"id": "admin-test", "commune": "National"}

SESSION_ID = "test_g3_session"


async def tour_correction(etat, message: str):
    """
    Reproduit EXACTEMENT le nouveau bloc de main.py (Tâche G.3) : une relecture
    rouverte par une correction (pas un "oui") incrémente nb_iterations_correction,
    et au 3e coup (SEUIL_ITERATIONS_CORRECTION_BLOQUE), le dossier passe à 'bloque'.
    """
    assert not main.est_reponse_affirmative(message)
    assert etat["phase"] == "relecture_en_cours"

    etat["phase"] = "collecte"
    etat["nb_iterations_correction"] += 1

    if etat["nb_iterations_correction"] >= main.SEUIL_ITERATIONS_CORRECTION_BLOQUE:
        etat["phase"] = "bloque"
        main.update_dossier(
            etat["dossier_id"],
            nb_iterations_correction=etat["nb_iterations_correction"],
            statut="bloque",
        )
        return "Je rencontre des difficultés... (message d'escalade)"

    main.update_dossier(etat["dossier_id"], nb_iterations_correction=etat["nb_iterations_correction"])
    # Sinon, retour à la collecte normale -> reproduit un tour administratif
    # standard (comme B.4) pour revenir à relecture_en_cours au tour suivant.
    return await tour_administratif(etat, message)


async def main_test():
    etat = main.etat_dossier_session(SESSION_ID)
    etat["cas_legal"] = "dans_les_delais"
    etat["slots"]["age_enfant"] = {"valeur": 1, "unite": "semaine"}
    etat["nb_iterations_correction"] = 0

    commune_id = main.resoudre_commune_id(TEST_COMMUNE)
    dossier = main.create_dossier(
        citoyen_id=TEST_CITOYEN_ID, type_demarche="extrait_naissance",
        slots=etat["slots"], cas_legal=etat["cas_legal"], commune_id=commune_id,
    )
    assert dossier
    etat["dossier_id"] = dossier["id"]
    print(f"📁 Dossier de test : {dossier['id']} (commune {TEST_COMMUNE})")

    # --- Remplit tous les slots pour atteindre relecture_en_cours -------------
    tours_remplissage = [
        "il est né à Ross-Béthio", "il s'appelle Ibrahima Diallo", "le 9 août 2026",
        "moi je m'appelle Modou Diallo", "sa mère c'est Aïssatou Ba, née le 12 mars 1998",
        "oui on est mariés",
    ]
    for message in tours_remplissage:
        await tour_administratif(etat, message)
        if etat["phase"] == "relecture_en_cours":
            break
    assert etat["phase"] == "relecture_en_cours"
    print("✅ Relecture déclenchée (comme B.4).")

    # --- 3 corrections successives (jamais un "oui") ---------------------------
    corrections = [
        "non, en fait il est né le 10 août, pas le 9",
        "attends, le nom de la mère c'est Aïcha, pas Aïssatou",
        "non, il manque encore une information sur le lieu de naissance",
    ]
    for i, message in enumerate(corrections, start=1):
        print(f"\n=== Correction {i}/3 : {message!r} ===")
        reponse = await tour_correction(etat, message)
        print(f"Agent : {reponse}")
        print(f"nb_iterations_correction = {etat['nb_iterations_correction']}, phase = {etat['phase']}")

    assert etat["nb_iterations_correction"] == 3
    assert etat["phase"] == "bloque"
    print("\n✅ 3 corrections envoyées, phase locale = 'bloque'.")

    # --- Vérifie EN BASE ---------------------------------------------------------
    dossier_relu = get_dossier(dossier["id"])
    print(f"\nEn base : statut={dossier_relu['statut']!r}, nb_iterations_correction={dossier_relu['nb_iterations_correction']}")
    assert dossier_relu["statut"] == "bloque"
    assert dossier_relu["nb_iterations_correction"] == 3
    print("✅ Dossier bien passé au statut 'bloque' EN BASE, avec le compteur exact.")

    # --- CRITÈRE DE VALIDATION : apparaît dans GET /admin/supervision -----------
    print("\n=== GET /admin/supervision ===")
    r = client.get("/admin/supervision")
    assert r.status_code == 200, r.text
    supervision = r.json()
    print("volumes_par_statut :", supervision["volumes_par_statut"])
    assert supervision["volumes_par_statut"].get("bloque", 0) >= 1

    ids_bloques = [d["id"] for d in supervision["dossiers_bloques"]]
    assert dossier["id"] in ids_bloques, "Le dossier de test n'apparaît PAS dans dossiers_bloques !"
    dossier_dans_supervision = next(d for d in supervision["dossiers_bloques"] if d["id"] == dossier["id"])
    print("Entrée trouvée :", dossier_dans_supervision)
    assert dossier_dans_supervision["commune_nom"] == TEST_COMMUNE
    print(f"✅ Le dossier de test apparaît bien dans dossiers_bloques, commune résolue = {dossier_dans_supervision['commune_nom']!r}.")

    print("\n✅ Tâche G.3 : 3 itérations de correction -> 'bloque' -> visible dans /admin/supervision — OK")


if __name__ == "__main__":
    asyncio.run(main_test())
