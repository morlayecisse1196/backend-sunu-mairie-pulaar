"""
Test manuel — Sprint C, Tâche C.2 (endpoints consultant : liste + détail).

Deux consultants simulés (override de dépendance FastAPI, cf. Tâche B.5 pour
la même technique — TEST_SUPABASE_TOKEN expiré et de toute façon hors-sujet
ici) de communes DIFFÉRENTES (Ross-Béthio / Dindéfélo, seules communes à
métadonnées confirmées, cf. seed_communes.py) :

  1. Crée des dossiers dans les deux communes, dont un 'en_cours' (ne doit
     JAMAIS apparaître, cf. DSF UC2 post-condition).
  2. Consultant Ross-Béthio ne voit QUE ses dossiers, triés par ancienneté.
  3. Consultant Dindéfélo ne voit QUE les siens — le critère de validation
     explicite de la tâche (isolation stricte inter-communes).
  4. Détail : accessible pour son propre dossier (avec documents + URL
     signée), 403 pour un dossier d'une autre commune.
"""
import asyncio
from dotenv import load_dotenv

load_dotenv()

from fastapi.testclient import TestClient
import main  # noqa: E402
from test_bascule_administratif import TEST_CITOYEN_ID
from test_upload_document import FAUX_JPEG

client = TestClient(main.app)


def consultant(commune: str):
    return lambda: {"id": "consultant-test", "commune": commune}


async def main_test():
    commune_ross_bethio = main.resoudre_commune_id("Ross-Béthio")
    commune_dindefelo = main.resoudre_commune_id("Dindéfélo")
    assert commune_ross_bethio and commune_dindefelo, "Communes de test absentes — seed_communes.py a-t-il été lancé ?"

    def creer(commune_id, statut):
        d = main.create_dossier(
            citoyen_id=TEST_CITOYEN_ID,
            type_demarche="extrait_naissance",
            slots=dict(main.SLOTS_VIDES_EXTRAIT_NAISSANCE),
            cas_legal="dans_les_delais",
            commune_id=commune_id,
            statut=statut,
        )
        assert d
        return d

    d1_rb = creer(commune_ross_bethio, "recu")
    d2_rb = creer(commune_ross_bethio, "en_traitement")
    d3_rb_en_cours = creer(commune_ross_bethio, "en_cours")  # NE DOIT PAS apparaître
    d1_dk = creer(commune_dindefelo, "recu")

    # Un document sur d1_rb, pour vérifier l'URL signée dans le détail
    document = main.upload_document(d1_rb["id"], "certificat_naissance", FAUX_JPEG, "image/jpeg", "jpg")
    assert document

    # --- Consultant de Ross-Béthio -------------------------------------------
    main.app.dependency_overrides[main.get_current_consultant] = consultant("Ross-Béthio")
    r = client.get("/consultant/dossiers")
    assert r.status_code == 200, r.text
    dossiers_rb = r.json()["dossiers"]
    ids_rb = [d["id"] for d in dossiers_rb]
    print("=== Liste vue par le consultant de Ross-Béthio ===")
    for d in dossiers_rb:
        print(f"  {d['id']}  statut={d['statut']}  cas_legal={d['cas_legal']}  created_at={d['created_at']}")

    assert d1_rb["id"] in ids_rb and d2_rb["id"] in ids_rb, "Un dossier attendu de Ross-Béthio est absent"
    assert d3_rb_en_cours["id"] not in ids_rb, "Un dossier encore 'en_cours' est apparu dans la liste consultant !"
    assert d1_dk["id"] not in ids_rb, "FUITE : le consultant de Ross-Béthio voit un dossier de Dindéfélo !"
    # Trié par ancienneté (le plus ancien d'abord) : d1_rb créé avant d2_rb
    assert ids_rb.index(d1_rb["id"]) < ids_rb.index(d2_rb["id"]), "Tri par ancienneté incorrect"
    print("✅ Consultant Ross-Béthio : voit ses dossiers (hors 'en_cours'), pas ceux de Dindéfélo, bien triés.")

    # Détail de son propre dossier
    r_detail = client.get(f"/consultant/dossiers/{d1_rb['id']}")
    assert r_detail.status_code == 200, r_detail.text
    detail = r_detail.json()
    print("\nDétail d1_rb :", {k: detail[k] if k != "dossier" else "..." for k in detail})
    assert len(detail["documents"]) == 1
    assert detail["documents"][0]["url_signee"], "URL signée absente dans le détail"
    assert detail["document_formulaires"] == []
    print("✅ Détail de son propre dossier accessible, avec URL signée pour le document.")

    # 403 sur le dossier de Dindéfélo
    r_interdit = client.get(f"/consultant/dossiers/{d1_dk['id']}")
    print("\nDétail d1_dk (autre commune) :", r_interdit.status_code)
    assert r_interdit.status_code == 403
    print("✅ Détail d'un dossier d'une autre commune correctement refusé (403).")

    # --- Consultant de Dindéfélo -----------------------------------------------
    main.app.dependency_overrides[main.get_current_consultant] = consultant("Dindéfélo")
    r2 = client.get("/consultant/dossiers")
    assert r2.status_code == 200, r2.text
    dossiers_dk = r2.json()["dossiers"]
    ids_dk = [d["id"] for d in dossiers_dk]
    print("\n=== Liste vue par le consultant de Dindéfélo ===")
    for d in dossiers_dk:
        print(f"  {d['id']}  statut={d['statut']}")

    assert d1_dk["id"] in ids_dk
    assert d1_rb["id"] not in ids_dk and d2_rb["id"] not in ids_dk, "FUITE : le consultant de Dindéfélo voit des dossiers de Ross-Béthio !"
    print("✅ Consultant Dindéfélo : isolation stricte confirmée (aucun dossier de Ross-Béthio visible).")

    del main.app.dependency_overrides[main.get_current_consultant]
    print("\n✅ Tâche C.2 : endpoints consultant OK — isolation par commune confirmée dans les deux sens")


if __name__ == "__main__":
    asyncio.run(main_test())
