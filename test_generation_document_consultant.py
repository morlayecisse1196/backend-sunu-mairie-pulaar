"""
Test manuel — Sprint D, Tâche D.3 (endpoint consultant : déclencher la génération).

  1. Dossier complet -> POST .../generer réussit, documents_generes créé
     (version=1, statut="genere"), dossier.statut passe à "genere", le PDF
     est réellement dans Storage (URL signée valide, contenu re-téléchargé).
  2. Rappel du même endpoint sur le même dossier -> version=2 (pas d'écrasement).
  3. Dossier volontairement incomplet (retire un champ obligatoire déjà
     rempli, cf. énoncé de la tâche) -> 422, message clair, AUCUNE ligne
     documents_generes créée pour cet essai.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient
import main  # noqa: E402
from dossiers_repo import get_document_formulaire, get_supabase_client
from test_document_generator import creer_dossier_complet

client = TestClient(main.app)
main.app.dependency_overrides[main.get_current_consultant] = lambda: {"id": "consultant-test", "commune": "Ross-Béthio"}


def main_test():
    dossier = creer_dossier_complet()
    print(f"📁 Dossier de test : {dossier['id']}")

    # --- 1. Génération réussie -------------------------------------------------
    r1 = client.post(f"/consultant/dossiers/{dossier['id']}/generer")
    assert r1.status_code == 200, r1.text
    corps1 = r1.json()
    print("\n=== 1. Génération (dossier complet) ===")
    print(corps1)
    assert corps1["version"] == 1
    assert corps1["statut"] == "genere"
    assert corps1["url_signee"]

    supabase = get_supabase_client()
    contenu = supabase.storage.from_("documents-generes").download(f"{dossier['id']}/v1.pdf")
    assert contenu.startswith(b"%PDF"), "Le fichier stocké dans Storage n'est pas un PDF valide"
    print(f"✅ PDF réellement présent dans Storage ({len(contenu)} octets).")

    dossier_relu = main.get_dossier(dossier["id"])
    assert dossier_relu["statut"] == "genere"
    print("✅ dossiers.statut passé à 'genere'.")

    # --- 2. Régénération -> version incrémentée, pas d'écrasement -------------
    r2 = client.post(f"/consultant/dossiers/{dossier['id']}/generer")
    assert r2.status_code == 200, r2.text
    print("\n=== 2. Régénération ===")
    print(r2.json())
    assert r2.json()["version"] == 2
    lignes = supabase.table("documents_generes").select("version").eq("dossier_id", dossier["id"]).execute().data
    assert sorted(v["version"] for v in lignes) == [1, 2]
    print("✅ version=2 créée, v1 toujours présente (historique conservé, pas d'écrasement).")

    # --- 3. Dossier volontairement incomplet -----------------------------------
    dossier2 = creer_dossier_complet()
    formulaires = main.list_document_formulaires(dossier2["id"])
    formulaire_acte = next(f for f in formulaires if f["type_document"] == "extrait_naissance")
    # Retire un champ obligatoire déjà rempli (numeroActe), cf. énoncé de la tâche.
    # update_champ_formulaire(..., valeur=None) est un no-op par conception (ne
    # jamais effacer un champ via une simple absence de valeur) -> on modifie
    # directement le JSONB pour ce test, qui a précisément besoin de "revenir en arrière".
    formulaire_acte_reset = get_document_formulaire(formulaire_acte["id"])
    champs = formulaire_acte_reset["champs"]
    for champ in champs:
        if champ["nom"] == "numeroActe":
            champ["valeur"] = None
            champ["source"] = "manuel"
    supabase.table("document_formulaires").update({"champs": champs}).eq("id", formulaire_acte["id"]).execute()

    r3 = client.post(f"/consultant/dossiers/{dossier2['id']}/generer")
    print("\n=== 3. Dossier volontairement incomplet ===")
    print("status:", r3.status_code, "body:", r3.json())
    assert r3.status_code == 422
    assert any("numeroActe" in champ for champ in r3.json()["detail"]["champs_en_erreur"])

    nb_documents_generes = (
        supabase.table("documents_generes").select("id").eq("dossier_id", dossier2["id"]).execute().data
    )
    assert nb_documents_generes == [], "Un document_genere a été créé malgré l'échec !"
    dossier2_relu = main.get_dossier(dossier2["id"])
    assert dossier2_relu["statut"] != "genere", "Le statut du dossier a été mis à jour malgré l'échec !"
    print("✅ 422 avec le champ en erreur listé, aucun documents_generes créé, statut du dossier inchangé.")

    print("\n✅ Tâche D.3 : endpoint de génération OK")


if __name__ == "__main__":
    main_test()
