"""
Test manuel — Sprint J, Tâche J.4 (orchestrateur traiter_tour_administratif).

Critères de validation explicites (SUNU_MAIRIE_PROMPTS.md, Tâche J.4) :
  1. Un dossier extrait de naissance complété de BOUT EN BOUT, champ par champ,
     en CONDITIONS RÉELLES (vrai LLM, vraie base Supabase, vrai Storage).
  2. Une réponse invalide déclenche bien une reformulation (PAS un avancement
     silencieux) — testé sur une date de mère postérieure à celle de l'enfant.
  3. Le dialogue attend réellement l'arrivée du document en base avant de
     passer au champ suivant — testé en rappelant l'orchestrateur AVANT puis
     APRÈS un vrai upload Storage/`documents`.

Aucun mock : appels réseau réels (OpenRouter + Supabase), comme les autres
tests "bout en bout" du projet (cf. test_bascule_administratif.py).
"""
import asyncio
import io
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from PIL import Image, ImageDraw

import main  # noqa: E402 — charge OPENROUTER_API_KEY etc., même pattern que les autres tests
from dossiers_repo import create_dossier, get_dossier, upload_document
from slot_controller import traiter_tour_administratif

TEST_CITOYEN_ID = "eeeabbec-a424-4acf-95cf-bb7611b1f275"  # profil réel existant (réutilisé des autres tests)

HEADERS = {
    "Authorization": f"Bearer {main.OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
}

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


def generer_photo_bidon() -> bytes:
    img = Image.new("RGB", (200, 200), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((10, 90), "PIECE TEST J.4", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def tour(etat: dict, message: str, libelle: str) -> dict:
    resultat = await traiter_tour_administratif(etat, message, HEADERS)
    print(f"--- {libelle} ---")
    print(f"  citoyen  : {message!r}")
    print(f"  résultat : {resultat}")
    print(f"  slots    : {etat['slots']}")
    return resultat


async def main_test():
    dossier = create_dossier(
        citoyen_id=TEST_CITOYEN_ID, type_demarche="extrait_naissance",
        slots=dict(SLOTS_VIDES), cas_legal=None, commune_id=None, statut="en_cours",
    )
    assert dossier, "Création du dossier de test échouée — vérifier la connexion Supabase."
    dossier_id = dossier["id"]
    print(f"Dossier de test créé : {dossier_id}\n")

    etat = {"slots": dict(SLOTS_VIDES), "dossier_id": dossier_id, "type_demarche": "extrait_naissance"}

    # 1. age_enfant
    r = await tour(etat, "Il a 7 jours.", "1. age_enfant")
    assert r["phase_suivante"] == "collecte" and not r["cas_particulier_cree"]
    assert etat["slots"]["age_enfant"]["valeur"] == 7 and etat["slots"]["age_enfant"]["unite"] == "jours"

    # 2. commune_naissance -> enchaîne ensuite sur le document certificat_naissance
    r = await tour(etat, "À Tambacounda.", "2. commune_naissance")
    assert etat["slots"]["commune_naissance"] == "Tambacounda"
    assert r["document_attendu"] == "certificat_naissance", f"attendu certificat_naissance, obtenu {r}"

    # 3. Document PAS ENCORE envoyé : rappeler doit REDEMANDER, jamais avancer.
    r = await tour(etat, "peu importe, pas encore de document", "3. certificat_naissance (pas envoyé)")
    assert r["document_attendu"] == "certificat_naissance", "aurait dû redemander le document, pas avancer"
    assert etat["slots"]["nom_enfant"] is None, "nom_enfant n'aurait jamais dû être traité avant le document"
    print("OK - document non reçu -> re-demandé, PAS d'avancement silencieux.\n")

    # Upload RÉEL (Storage + table documents) -> le document existe maintenant en base.
    doc = upload_document(dossier_id, "certificat_naissance", generer_photo_bidon(), "image/png", "png")
    assert doc, "Upload réel du certificat_naissance échoué."
    print(f"Document certificat_naissance réellement inséré : {doc['id']}\n")

    # 4. Nouveau tour : le document est maintenant reçu -> avance vers nom_enfant.
    r = await tour(etat, "Ibrahima Diallo.", "4. nom_enfant (après upload réel)")
    assert etat["slots"]["nom_enfant"] == "Ibrahima Diallo", "le document reçu aurait dû débloquer nom_enfant"
    print("OK - document réellement reçu en base -> passage au champ suivant confirmé.\n")

    # 5. date_naissance_enfant
    r = await tour(etat, "Le 9 août 2020.", "5. date_naissance_enfant")
    assert etat["slots"]["date_naissance_enfant"] == "2020-08-09"

    # 6. nom_declarant -> enchaîne sur le document cni_declarant
    r = await tour(etat, "Modou Diallo.", "6. nom_declarant")
    assert etat["slots"]["nom_declarant"] == "Modou Diallo"
    assert r["document_attendu"] == "cni_declarant"

    doc2 = upload_document(dossier_id, "cni_declarant", generer_photo_bidon(), "image/png", "png")
    assert doc2, "Upload réel de cni_declarant échoué."

    # 7. nom_mere (après upload réel de la CNI)
    r = await tour(etat, "Aïssatou Ba.", "7. nom_mere")
    assert etat["slots"]["nom_mere"] == "Aïssatou Ba"

    # 8. date_naissance_mere — RÉPONSE INVALIDE D'ABORD (postérieure à l'enfant, 2020-08-09)
    r = await tour(etat, "Le 1er septembre 2021.", "8a. date_naissance_mere (INVALIDE, postérieure à l'enfant)")
    assert etat["slots"]["date_naissance_mere"] is None, "une date incohérente n'aurait JAMAIS dû être enregistrée"
    assert r["phase_suivante"] == "collecte" and not r["cas_particulier_cree"]
    assert r["reponse_fr"], "une reformulation était attendue, pas une réponse vide"
    print("OK - date de mère postérieure à l'enfant REJETÉE, reformulation renvoyée, PAS enregistrée.\n")

    # 8b. Cette fois une date cohérente.
    r = await tour(etat, "Le 12 mars 1998.", "8b. date_naissance_mere (valide)")
    assert etat["slots"]["date_naissance_mere"] == "1998-03-12"

    # 9. parents_maries -> enchaîne sur le groupe alternatif livret_famille/certificat_mariage
    r = await tour(etat, "Oui, on est mariés.", "9. parents_maries")
    assert etat["slots"]["parents_maries"] is True
    assert r["document_attendu"] in ("livret_famille", "certificat_mariage")
    print(f"Groupe alternatif document demandé : {r['document_attendu']}\n")

    # 10. Upload du certificat_mariage (l'AUTRE membre du groupe) -> doit suffire à satisfaire le groupe.
    doc3 = upload_document(dossier_id, "certificat_mariage", generer_photo_bidon(), "image/png", "png")
    assert doc3, "Upload réel de certificat_mariage échoué."

    r = await tour(etat, "peu importe", "10. après upload certificat_mariage (alternative au livret)")
    assert r["phase_suivante"] == "complet", (
        f"le dossier aurait dû être marqué complet (groupe alternatif satisfait par l'AUTRE type) : {r}"
    )
    assert r["reponse_fr"] is None, "phase 'complet' : reponse_fr doit être None (RG7 géré par l'appelant)"
    print("OK - certificat_mariage (alternative au livret) a bien satisfait le groupe -> dossier COMPLET.\n")

    # Vérification finale : tous les slots requis sont bien remplis.
    manquants = [k for k, v in etat["slots"].items() if k != "age_enfant" and v is None]
    assert not manquants, f"slots encore vides après complétion : {manquants}"
    print("Slots finaux :", etat["slots"])

    print("\nTâche J.4 validée : dossier complété de bout en bout, champ par champ, en conditions réelles.")
    print(f"(dossier de test : {dossier_id} — laissé en base, statut 'en_cours', pas de nettoyage automatique)")


async def test_garde_fou_document_jamais_envoye():
    """
    Garde-fou anti-blocage infini (plan §5) : un document JAMAIS envoyé ne
    doit jamais faire boucler le dialogue indéfiniment — au-delà de
    SEUIL_RAPPELS_DOCUMENT rappels, le groupe doit être marqué "ignoré" et le
    dialogue doit PASSER À LA SUITE au rappel suivant (bug réel trouvé et
    corrigé en préparant la Tâche J.5 : sans `documents_ignores`, la même
    étape revenait indéfiniment malgré le message "on continue" déjà envoyé).
    """
    from slot_controller import SEUIL_RAPPELS_DOCUMENT

    slots_presque_complets = dict(SLOTS_VIDES)
    slots_presque_complets.update({
        "age_enfant": {"valeur": 7, "unite": "jours"},
        "commune_naissance": "Tambacounda",
        "nom_enfant": "Ibrahima Diallo",
        "date_naissance_enfant": "2020-08-09",
        "nom_declarant": "Modou Diallo",
        "nom_mere": "Aïssatou Ba",
        "date_naissance_mere": "1998-03-12",
        "parents_maries": True,  # seul le document livret/certificat manque désormais
    })
    dossier = create_dossier(
        citoyen_id=TEST_CITOYEN_ID, type_demarche="extrait_naissance",
        slots=slots_presque_complets, cas_legal="dans_les_delais", commune_id=None, statut="en_cours",
    )
    assert dossier, "Création du dossier de test (garde-fou) échouée."
    dossier_id = dossier["id"]
    # Les 2 documents obligatoires (certificat_naissance, cni_declarant) sont
    # déjà uploadés réellement ici — seul le groupe alternatif optionnel
    # (livret_famille/certificat_mariage) doit rester à tester ci-dessous.
    assert upload_document(dossier_id, "certificat_naissance", generer_photo_bidon(), "image/png", "png")
    assert upload_document(dossier_id, "cni_declarant", generer_photo_bidon(), "image/png", "png")
    etat = {"slots": dict(slots_presque_complets), "dossier_id": dossier_id, "type_demarche": "extrait_naissance"}

    print(f"\n=== Garde-fou document jamais envoyé (dossier {dossier_id}) ===")
    for i in range(1, SEUIL_RAPPELS_DOCUMENT + 1):
        r = await tour(etat, "je regarde...", f"rappel {i}/{SEUIL_RAPPELS_DOCUMENT}")
        assert r["document_attendu"] in ("livret_famille", "certificat_mariage")
        assert not r["cas_particulier_cree"]

    # Rappel suivant : seuil dépassé -> cas_particulier signalé, document ignoré.
    r = await tour(etat, "je ne l'ai vraiment pas", f"rappel {SEUIL_RAPPELS_DOCUMENT + 1} (seuil dépassé)")
    assert r["cas_particulier_cree"] is True, "le seuil de rappels aurait dû déclencher le garde-fou"
    assert r.get("document_ignore") in ("livret_famille", "certificat_mariage")
    print("OK - garde-fou déclenché, document marqué ignoré.")

    # Tour SUIVANT : le dialogue doit avoir avancé (dossier complet), PAS
    # redemander le même document une fois de plus.
    r = await tour(etat, "peu importe", "tour suivant (ne doit PAS redemander le document)")
    assert r["document_attendu"] is None, "le document ignoré a été redemandé -> le correctif n'a pas fonctionné !"
    assert r["phase_suivante"] == "complet", f"le dossier aurait dû être complet après l'ignore : {r}"
    print("OK - le tour suivant n'a PAS redemandé le document ignoré -> dossier complet. Correctif validé.\n")


if __name__ == "__main__":
    asyncio.run(main_test())
    asyncio.run(test_garde_fou_document_jamais_envoye())
