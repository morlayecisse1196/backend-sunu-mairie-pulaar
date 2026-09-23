"""
Test manuel — Sprint J, Tâche J.7 (relecture RG7 générique) + adaptation
CNI recto/verso demandée en marge (migration 009).

Critère de validation explicite (SUNU_MAIRIE_PROMPTS.md, Tâche J.7) : la
relecture RG7 fonctionne aussi pour une démarche de TEST à 2 champs fictifs
insérés dans `demarche_champs`, pas seulement pour `extrait_naissance`.

Complété par un test réel (LLM + Supabase) de l'adaptation recto/verso :
la CNI du déclarant doit désormais être demandée en DEUX photos séquentielles
(pas un groupe alternatif comme livret_famille/certificat_mariage), les deux
obligatoires, avant de pouvoir avancer vers la mère.
"""
import asyncio
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from supabase_client import get_supabase_client
from dialogue_engine import construire_recapitulatif
from slot_controller import charger_definition_demarche, traiter_tour_administratif
from dossiers_repo import create_dossier, upload_document
from test_bascule_administratif import TEST_CITOYEN_ID
import main  # noqa: E402

TYPE_DEMARCHE_FICTIF = "test_j7_fictif"

SLOTS_VIDES = {
    "age_enfant": {"valeur": None, "unite": None},
    "commune_naissance": None,
    "nom_enfant": None,
    "date_naissance_enfant": None,
    "nom_declarant": None,
    "nom_mere": None,
    "date_naissance_mere": None,
    "parents_maries": None,
}

HEADERS = {"Authorization": f"Bearer {main.OPENROUTER_API_KEY}", "Content-Type": "application/json"}


def test_recapitulatif_generique_demarche_fictive():
    print("========== 1. construire_recapitulatif() générique (démarche fictive à 2 champs) ==========")
    supabase = get_supabase_client()

    # Nettoyage préalable (au cas où un run précédent aurait échoué avant le nettoyage final).
    supabase.table("demarche_champs").delete().eq("type_demarche", TYPE_DEMARCHE_FICTIF).execute()

    supabase.table("demarche_champs").insert([
        {
            "type_demarche": TYPE_DEMARCHE_FICTIF, "ordre": 10, "nom_champ": "nom_test",
            "type_valeur": "texte", "question": "Quel est le nom du dossier de test ?",
            "regle_validation": None, "obligatoire": True,
        },
        {
            "type_demarche": TYPE_DEMARCHE_FICTIF, "ordre": 20, "nom_champ": "date_test",
            "type_valeur": "date", "question": "Quelle est la date du test ?",
            "regle_validation": "passee", "obligatoire": True,
        },
    ]).execute()

    try:
        definition = charger_definition_demarche(TYPE_DEMARCHE_FICTIF)
        assert len(definition) == 2, f"attendu 2 champs fictifs, obtenu {len(definition)}"
        assert [c["nom_champ"] for c in definition] == ["nom_test", "date_test"], "ordre incorrect"

        slots_fictifs = {"nom_test": "Dossier Exemple J7", "date_test": "2020-01-01"}
        recap = construire_recapitulatif(slots_fictifs, definition)
        print("Récapitulatif généré :", recap)

        assert "Dossier Exemple J7" in recap, "la valeur de nom_test devrait apparaître dans le récap"
        assert "2020-01-01" in recap, "la valeur de date_test devrait apparaître dans le récap"
        assert recap.strip().endswith("Est-ce que tout est exact ?"), "la question de confirmation finale manque"
        print("OK - le récapitulatif générique fonctionne pour une démarche fictive à 2 champs.\n")

        # Non-régression : SANS definition_champs, le gabarit historique (narratif,
        # extrait_naissance) reste EXACTEMENT inchangé (test_relecture_confirmation.py
        # en dépend implicitement).
        slots_naissance = {
            "nom_enfant": "Ibrahima Diallo", "date_naissance_enfant": "2020-08-09",
            "commune_naissance": "Ross-Béthio", "nom_declarant": "Modou Diallo",
            "nom_mere": "Aïssatou Ba", "date_naissance_mere": "1998-03-12", "parents_maries": True,
        }
        recap_historique = construire_recapitulatif(slots_naissance)
        assert "Ibrahima Diallo, né(e) le 2020-08-09 à Ross-Béthio" in recap_historique, (
            "le gabarit historique (narratif) a changé alors qu'aucun definition_champs n'est fourni !"
        )
        print("OK - sans definition_champs, le gabarit narratif historique est inchangé (non-régression).")
        print("Récap historique :", recap_historique, "\n")
    finally:
        supabase.table("demarche_champs").delete().eq("type_demarche", TYPE_DEMARCHE_FICTIF).execute()
        print("(nettoyage : champs fictifs retirés de demarche_champs)\n")


async def tour(etat, message, libelle):
    r = await traiter_tour_administratif(etat, message, HEADERS)
    print(f"--- {libelle} ---\n  citoyen  : {message!r}\n  résultat : {r}")
    return r


async def test_cni_recto_verso_sequentiel():
    print("========== 2. CNI recto/verso réellement séquentiel (pas alternatif) ==========")
    slots = dict(SLOTS_VIDES)
    slots.update({
        "age_enfant": {"valeur": 7, "unite": "jours"},
        "commune_naissance": "Tambacounda",
        "nom_enfant": "Ibrahima Diallo",
        "date_naissance_enfant": "2020-08-09",
        "nom_declarant": "Modou Diallo",
    })
    dossier = create_dossier(
        citoyen_id=TEST_CITOYEN_ID, type_demarche="extrait_naissance",
        slots=slots, cas_legal="dans_les_delais", commune_id=None, statut="en_cours",
    )
    assert dossier, "Création du dossier de test échouée."
    dossier_id = dossier["id"]
    # Le certificat de naissance est déjà là (pas l'objet de ce test).
    assert upload_document(dossier_id, "certificat_naissance", b"\x89PNG\r\n\x1a\n" + b"0" * 50, "image/png", "png")
    etat = {"slots": dict(slots), "dossier_id": dossier_id, "type_demarche": "extrait_naissance"}

    r = await tour(etat, "d'accord", "1er tour : doit demander le RECTO")
    assert r["document_attendu"] == "cni_declarant_recto", f"attendu recto en premier : {r}"

    r = await tour(etat, "je regarde", "2e tour (recto pas envoyé) : doit RE-demander le recto, pas le verso")
    assert r["document_attendu"] == "cni_declarant_recto", "aurait dû redemander le recto, pas avancer au verso"

    assert upload_document(dossier_id, "cni_declarant_recto", b"\x89PNG\r\n\x1a\n" + b"1" * 50, "image/png", "png")

    r = await tour(etat, "voilà le recto", "3e tour (recto envoyé) : doit maintenant demander le VERSO")
    assert r["document_attendu"] == "cni_declarant_verso", f"attendu verso après le recto : {r}"
    print("OK - le verso n'est demandé qu'APRÈS réception réelle du recto (séquentiel, pas alternatif).")

    r = await tour(etat, "je regarde encore", "4e tour (verso pas envoyé) : doit RE-demander le verso")
    assert r["document_attendu"] == "cni_declarant_verso"
    assert etat["slots"]["nom_mere"] is None, "n'aurait jamais dû avancer à nom_mere avant le verso"

    assert upload_document(dossier_id, "cni_declarant_verso", b"\x89PNG\r\n\x1a\n" + b"2" * 50, "image/png", "png")

    r = await tour(etat, "Aïssatou Ba", "5e tour (verso envoyé) : doit avancer vers nom_mere")
    assert etat["slots"]["nom_mere"] == "Aïssatou Ba", "le verso reçu aurait dû débloquer nom_mere"
    print("OK - les deux faces réellement reçues -> le dialogue avance enfin vers nom_mere.\n")


if __name__ == "__main__":
    test_recapitulatif_generique_demarche_fictive()
    asyncio.run(test_cni_recto_verso_sequentiel())
    print("Tâche J.7 validée : relecture RG7 générique (démarche fictive) + CNI recto/verso réellement séquentiel.")
