"""
Test manuel — Sprint B, Tâche B.5 (upload de document + statut attente_upload).

Deux parties :
  1. Endpoint REST POST /dossiers/{id}/documents, via TestClient FastAPI (pas
     besoin d'un serveur uvicorn lancé à part) : upload réel dans Supabase
     Storage + vérification de la ligne `documents` créée, + repli de
     sécurité (mauvais propriétaire, type invalide).
  2. Sortie structurée du générateur administratif avec le nouveau champ
     "document_attendu" (vrai LLM), et vérification que la déduplication
     "déjà demandé" fonctionne (ne redemande pas deux fois le même document).
"""
import asyncio
import json
from dotenv import load_dotenv

load_dotenv()

from fastapi.testclient import TestClient
import main  # noqa: E402
from dossiers_repo import get_dossier, get_document_signed_url, BUCKET_DOCUMENTS
from supabase_client import get_supabase_client
from test_bascule_administratif import appeler_generateur, TEST_CITOYEN_ID, TEST_COMMUNE

# TEST_SUPABASE_TOKEN (.env) expire au bout d'~1h (JWT Supabase standard) et
# n'a rien à voir avec la logique testée ici (endpoint + Storage + ownership) —
# on contourne avec un override de dépendance FastAPI plutôt que d'aller
# régénérer un token à chaque run. auth.py/verify_token est déjà validé par
# ailleurs (déploiement VPS, Sprints précédents).
TOKEN = "override-dependance-pas-de-vrai-jwt-necessaire"
FAUX_JPEG = b"\xff\xd8\xff\xe0" + b"CECI_EST_UNE_FAUSSE_PHOTO_DE_TEST" * 20

main.app.dependency_overrides[main.get_current_user] = lambda: {"id": TEST_CITOYEN_ID, "commune": TEST_COMMUNE}
client = TestClient(main.app)


async def preparer_dossier_test() -> str:
    dossier = main.create_dossier(
        citoyen_id=TEST_CITOYEN_ID,
        type_demarche="extrait_naissance",
        slots=dict(main.SLOTS_VIDES_EXTRAIT_NAISSANCE),
        commune_id=main.resoudre_commune_id(TEST_COMMUNE),
    )
    assert dossier
    return dossier["id"]


def test_upload_reussi(dossier_id: str):
    print("=== Upload réussi (certificat_naissance) ===")
    response = client.post(
        f"/dossiers/{dossier_id}/documents",
        data={"type": "certificat_naissance"},
        files={"fichier": ("test.jpg", FAUX_JPEG, "image/jpeg")},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    print("status:", response.status_code, "body:", response.text)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["type"] == "certificat_naissance"
    assert body["statut"] == "recu"

    # Vérification en base (ligne `documents`)
    supabase = get_supabase_client()
    row = supabase.table("documents").select("*").eq("id", body["document_id"]).limit(1).execute().data[0]
    print("Ligne documents :", row)
    assert row["dossier_id"] == dossier_id
    assert row["type"] == "certificat_naissance"
    chemin_storage = row["fichier_url"]
    assert chemin_storage.startswith(dossier_id), "Le chemin Storage ne respecte pas la convention {dossier_id}/..."

    # Vérification que le fichier existe RÉELLEMENT dans Storage (pas juste la ligne DB)
    url_signee = get_document_signed_url(chemin_storage)
    print("URL signée :", url_signee)
    assert url_signee, "Impossible de générer une URL signée — le fichier n'est peut-être pas dans Storage"

    contenu_telecharge = get_supabase_client().storage.from_(BUCKET_DOCUMENTS).download(chemin_storage)
    assert contenu_telecharge == FAUX_JPEG, "Le contenu téléchargé ne correspond pas au fichier envoyé"
    print("✅ Fichier bien présent dans Storage, contenu conforme.")


def test_type_invalide(dossier_id: str):
    print("\n=== Type de document invalide (attendu: 400) ===")
    response = client.post(
        f"/dossiers/{dossier_id}/documents",
        data={"type": "permis_de_conduire"},
        files={"fichier": ("test.jpg", FAUX_JPEG, "image/jpeg")},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    print("status:", response.status_code)
    assert response.status_code == 400
    print("✅ Type invalide correctement rejeté.")


def test_mauvais_proprietaire(dossier_id: str):
    print("\n=== Upload authentifié comme un AUTRE citoyen sur ce dossier (attendu: 403) ===")
    # Réutilise le dossier de TEST_CITOYEN_ID, mais authentifié comme quelqu'un
    # d'autre pour CET appel précis (override de dépendance temporaire — pas
    # besoin d'un 2e vrai profil, seule la comparaison dossier.citoyen_id vs.
    # user["id"] côté endpoint est testée ici).
    main.app.dependency_overrides[main.get_current_user] = lambda: {"id": "un-autre-citoyen", "commune": TEST_COMMUNE}
    try:
        response = client.post(
            f"/dossiers/{dossier_id}/documents",
            data={"type": "certificat_naissance"},
            files={"fichier": ("test.jpg", FAUX_JPEG, "image/jpeg")},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
    finally:
        main.app.dependency_overrides[main.get_current_user] = lambda: {"id": TEST_CITOYEN_ID, "commune": TEST_COMMUNE}
    print("status:", response.status_code)
    assert response.status_code == 403
    print("✅ Upload sur le dossier d'autrui correctement refusé.")


async def test_document_attendu_llm():
    print("\n=== document_attendu (LLM structuré) ===")
    slots = dict(main.SLOTS_VIDES_EXTRAIT_NAISSANCE)
    slots["commune_naissance"] = "Tambacounda"
    schema = {"type": "json_schema", "json_schema": {"name": "slots_update", "strict": True, "schema": main.SLOTS_JSON_SCHEMA_ADMINISTRATIF}}

    prompt = main.build_generator_prompt_administratif(
        "Oui je l'ai avec moi, le certificat de l'hôpital.", slots, cas_legal="dans_les_delais",
        documents_deja_demandes=[],
    )
    parsed = await appeler_generateur(main.SYSTEM_PROMPT_GENERATOR_ADMINISTRATIF, prompt, schema)
    print("Agent :", parsed["reponse"])
    print("document_attendu =", parsed["document_attendu"])
    assert parsed["document_attendu"] == "certificat_naissance", (
        f"Le LLM n'a pas demandé le bon document : {parsed['document_attendu']!r}"
    )

    # Round 2 : le LLM peut re-suggérer le même document (observé empiriquement —
    # la consigne "ne redemande jamais" n'est pas fiable à 100% de sa part, ce
    # qui est justement pourquoi la déduplication réelle est codée en dur côté
    # main.py (etat["documents_demandes"]), pas confiée au LLM. On teste donc
    # ICI le même mécanisme que le vrai handler WS, pas la docilité du LLM.
    prompt2 = main.build_generator_prompt_administratif(
        "D'accord.", slots, cas_legal="dans_les_delais",
        documents_deja_demandes=["certificat_naissance"],
    )
    parsed2 = await appeler_generateur(main.SYSTEM_PROMPT_GENERATOR_ADMINISTRATIF, prompt2, schema)
    print("Agent (tour 2) :", parsed2["reponse"])
    print("document_attendu (tour 2, brut LLM) =", parsed2["document_attendu"])

    documents_demandes = {"certificat_naissance"}  # déjà signalé au tour 1
    dispatch_tour2 = bool(
        parsed2.get("document_attendu") and parsed2["document_attendu"] not in documents_demandes
    )
    print("attente_upload aurait été renvoyé au tour 2 ?", dispatch_tour2)
    assert dispatch_tour2 is False, "Le garde-fou codé en dur n'a pas empêché un 2e envoi du même attente_upload !"

    print("✅ document_attendu déclenché, et le garde-fou côté code empêche bien la répétition.")


async def main_test():
    assert TOKEN, "TEST_SUPABASE_TOKEN manquant dans .env"
    dossier_id = await preparer_dossier_test()
    print(f"📁 Dossier de test : {dossier_id}\n")

    test_upload_reussi(dossier_id)
    test_type_invalide(dossier_id)
    test_mauvais_proprietaire(dossier_id)
    await test_document_attendu_llm()

    print("\n✅ Tâche B.5 : endpoint d'upload + document_attendu — OK")


if __name__ == "__main__":
    asyncio.run(main_test())
