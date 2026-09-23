"""
Script manuel — Sprint I, Tâches I.1 et I.2 : parcours bout-en-bout réel, sur
les trois fronts (mobile, backend, web), AVANT déploiement VPS.

Limite honnête (comme tous les tests de ce projet, cf. test_parcours_f5.py,
test_slot_controller_j7.py, test_dossier_bloque_g3.py) : aucun téléphone/
émulateur Flutter n'est disponible dans cet environnement CLI. Ce script
reproduit donc fidèlement le PROTOCOLE réel (WebSocket/REST) que l'app mobile
utilise — vrai LLM (slot_controller.traiter_tour_administratif, Tâche J.4/J.5,
le mécanisme RÉELLEMENT câblé dans main.py aujourd'hui, pas l'ancien système
B.2), vraie base Supabase, vrais uploads de documents (dont les 2 VRAIES
photos de CNI de l'utilisateur, model_OCR/image_cni-exmple/, déjà validées
Sprint K) — puis le vrai web consultant (TestClient sur main.app), puis retour
au canal citoyen (REST /mes-dossiers/...) pour la validation finale (H.3).
Valide le CONTRAT que l'app mobile réelle doit respecter, pas le rendu Flutter
lui-même.

I.1 : rejoue l'Exemple 2.1 (README-MISE-A-JOUR-APP/Exemples_Dialogues_Agent_
SUNU-MAIRIE.md) intégralement, cas "dans les délais" -> vérifie que CHAQUE
étape du statut est traversée dans le bon ordre en base :
  en_cours -> recu -> en_traitement -> genere -> en_attente_validation_citoyen
  -> finalise
(les deux dernières transitions sont celles ajoutées/corrigées pour cette
tâche : GET /consultant/dossiers/{id} bascule 'recu'->'en_traitement' à la
première ouverture, cf. main.py:consultant_detail_dossier).

I.2 : construit un dossier jusqu'à 'en_attente_validation_citoyen', provoque
une VRAIE incohérence (nom différent dialogue vs OCR CNI — déjà observée
réellement lors de la validation K.6), puis appelle 3 fois de suite
POST /mes-dossiers/{id}/demander-corrections -> vérifie l'escalade à 'bloque'
au 3e appel (nb_iterations_correction réutilisé, cf. correctif de cette
tâche dans main.py:demander_corrections).
"""
import asyncio
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import httpx
from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient

import main  # noqa: E402
from dossiers_repo import (
    create_dossier, upload_document, update_dossier, get_dossier,
    list_document_formulaires, get_or_create_formulaire_acte, update_champ_formulaire,
    resoudre_commune_id, generer_numero_suivi,
)
from slot_controller import traiter_tour_administratif
from dialogue_engine import determiner_cas_legal, normaliser_age, dossier_complet, construire_recapitulatif
from test_bascule_administratif import TEST_CITOYEN_ID

TEST_COMMUNE = "Ross-Béthio"  # seule commune réellement seedée avec métadonnées (seed_communes.py) — "Tambacounda" (Exemple 2.1) n'existe pas en base ici
HEADERS = {"Authorization": f"Bearer {main.OPENROUTER_API_KEY}", "Content-Type": "application/json"}
client = TestClient(main.app)

CHEMIN_CNI_RECTO = "model_OCR/image_cni-exmple/retro.jpeg"
CHEMIN_CNI_VERSO = "model_OCR/image_cni-exmple/verso.jpeg"
FAUX_CERTIFICAT = b"\x89PNG\r\n\x1a\n" + b"CERTIFICAT_DE_TEST" * 20


def est_affirmatif(message: str) -> bool:
    return main.est_reponse_affirmative(message)


async def tour(etat: dict, message: str, libelle: str) -> dict:
    """
    Reproduit fidèlement le "glue" de main.py (bloc mode==administratif) :
    RG7 (relecture/confirmation/bloque, inchangé depuis B.4/G.3) autour de
    l'orchestrateur RÉEL slot_controller.traiter_tour_administratif (J.4/J.5).
    """
    if etat["phase"] == "relecture_en_cours" and est_affirmatif(message):
        numero_suivi = generer_numero_suivi()
        update_dossier(etat["dossier_id"], statut="recu", numero_suivi=numero_suivi)
        etat["phase"] = "termine"
        etat["numero_suivi"] = numero_suivi
        print(f"--- {libelle} ---\n  citoyen : {message!r}\n  -> CONFIRMÉ, numero_suivi={numero_suivi}")
        return {"reponse_fr": f"Numéro de suivi : {numero_suivi}", "document_attendu": None}

    if etat["phase"] == "relecture_en_cours":  # correction, pas une confirmation
        etat["phase"] = "collecte"
        # (I.1 ne teste pas la boucle de correction PRÉ-génération — I.2 teste
        # la boucle POST-génération, mécanisme différent, cf. docstring module.)

    resultat = await traiter_tour_administratif(etat, message, HEADERS)
    document_attendu = resultat.get("document_attendu")
    if document_attendu and document_attendu not in etat["documents_demandes"]:
        etat["documents_demandes"].add(document_attendu)

    age = etat["slots"].get("age_enfant") or {}
    if age.get("valeur") is not None and age.get("unite"):
        etat["cas_legal"] = determiner_cas_legal(normaliser_age(age["valeur"], age["unite"]))

    reponse = resultat.get("reponse_fr") or ""
    if resultat["phase_suivante"] == "complet" and dossier_complet(etat["slots"]):
        reponse = construire_recapitulatif(etat["slots"])
        etat["phase"] = "relecture_en_cours"

    maj = {"slots": etat["slots"]}
    if etat["cas_legal"]:
        maj["cas_legal"] = etat["cas_legal"]
    commune_naissance = etat["slots"].get("commune_naissance")
    if commune_naissance and not etat["commune_id_resolue"]:
        commune_id = resoudre_commune_id(commune_naissance)
        if commune_id:
            maj["commune_id"] = commune_id
            etat["commune_id_resolue"] = True
    update_dossier(etat["dossier_id"], **maj)

    print(f"--- {libelle} ---\n  citoyen : {message!r}\n  agent   : {reponse!r}\n  document_attendu={document_attendu}  phase={etat['phase']}")
    return resultat


async def construire_dossier_jusqu_a_recu(citoyen_nom_declarant: str = "Modou Diallo") -> str:
    """
    Rejoue l'Exemple 2.1 en entier (mode administratif réel, J.4/J.5) jusqu'au
    statut 'recu'. Réutilisé par I.1 et I.2. `citoyen_nom_declarant` permet à
    I.2 de garder le nom du dialogue DIFFÉRENT de celui de la vraie CNI
    (Morlaye Cisse) pour provoquer une vraie incohérence détectable par OCR.
    """
    etat = {
        "slots": dict(main.SLOTS_VIDES_EXTRAIT_NAISSANCE),
        "dossier_id": None, "cas_legal": None, "type_demarche": "extrait_naissance",
        "phase": "collecte", "documents_demandes": set(), "commune_id_resolue": False,
    }
    etat["slots"]["age_enfant"] = {"valeur": 7, "unite": "jours"}  # connu avant la bascule (Tâche B.3)
    etat["cas_legal"] = determiner_cas_legal(normaliser_age(7, "jours"))
    assert etat["cas_legal"] == "dans_les_delais"

    dossier = create_dossier(
        citoyen_id=TEST_CITOYEN_ID, type_demarche="extrait_naissance",
        slots=etat["slots"], cas_legal=etat["cas_legal"], commune_id=None,
    )
    assert dossier, "création du dossier échouée"
    etat["dossier_id"] = dossier["id"]
    print(f"\n📁 Dossier créé : {dossier['id']} (statut initial = {dossier['statut']!r})\n")
    assert dossier["statut"] == "en_cours"

    await tour(etat, f"À {TEST_COMMUNE}.", "1. commune_naissance")
    assert upload_document(etat["dossier_id"], "certificat_naissance", FAUX_CERTIFICAT, "image/png", "png")
    print("  [upload réel : certificat_naissance]")

    await tour(etat, "Ibrahima Diallo.", "2. nom_enfant (après upload certificat)")
    await tour(etat, "Le 9 août 2026.", "3. date_naissance_enfant")
    await tour(etat, citoyen_nom_declarant, "4. nom_declarant")

    with open(CHEMIN_CNI_RECTO, "rb") as f:
        assert upload_document(etat["dossier_id"], "cni_declarant_recto", f.read(), "image/jpeg", "jpeg")
    print("  [upload réel : cni_declarant_recto — vraie photo utilisateur]")

    await tour(etat, "Voilà le recto.", "5. (recto reçu -> demande verso)")
    with open(CHEMIN_CNI_VERSO, "rb") as f:
        assert upload_document(etat["dossier_id"], "cni_declarant_verso", f.read(), "image/jpeg", "jpeg")
    print("  [upload réel : cni_declarant_verso — vraie photo utilisateur]")

    await tour(etat, "Voilà l'autre côté.", "6. (verso reçu -> nom_mere)")
    await tour(etat, "Aïssatou Ba", "7. nom_mere")
    await tour(etat, "Le 12 mars 1998.", "8. date_naissance_mere")
    r = await tour(etat, "Oui, à la mairie l'année dernière.", "9. parents_maries")

    # Livret de famille : "je ne l'ai pas" (Exemple 2.1 exact) -> exerce le
    # vrai chemin J.6 _citoyen_dit_ne_pas_avoir plutôt que de le sauter.
    assert r["document_attendu"] in ("livret_famille", "certificat_mariage"), r
    await tour(etat, "je regarde", "10. (1er rappel livret, pas encore de refus)")
    r = await tour(etat, "Je ne l'ai pas avec moi aujourd'hui.", "11. livret -> 'je ne l'ai pas'")
    assert r.get("cas_particulier_cree") and r.get("document_ignore"), r
    print("  OK - refus explicite détecté (J.6), document marqué ignoré.")

    # Le tour qui ignore le document ne recalcule pas encore l'étape suivante
    # (slot_controller.traiter_tour_administratif retourne immédiatement dans
    # la branche "document ignoré") — il faut UN tour de plus pour que le code
    # constate que documents_ignores couvre désormais le dernier groupe
    # restant et déclenche enfin le signal "complet".
    await tour(etat, "d'accord", "12. (tour suivant -> complet détecté -> relecture)")

    assert etat["phase"] == "relecture_en_cours", f"relecture non déclenchée, phase={etat['phase']}"
    dossier_avant_confirmation = get_dossier(etat["dossier_id"])
    assert dossier_avant_confirmation["statut"] == "en_cours"
    print("\n✅ Relecture (RG7) bien déclenchée avant tout envoi.")

    await tour(etat, "Oui, c'est bon.", "12. confirmation RG7")
    dossier_recu = get_dossier(etat["dossier_id"])
    assert dossier_recu["statut"] == "recu"
    assert dossier_recu["numero_suivi"]
    print(f"✅ Dossier 'recu', numero_suivi={dossier_recu['numero_suivi']}")
    return etat["dossier_id"]


def completer_cote_consultant(dossier_id: str, lancer_ocr: bool) -> None:
    """Étapes web consultant réelles (C.2/C.3/D.2/D.3/E.2/K.4) jusqu'à 'genere'."""
    main.app.dependency_overrides[main.get_current_consultant] = lambda: {"id": "consultant-test", "commune": TEST_COMMUNE}

    r = client.get(f"/consultant/dossiers/{dossier_id}")
    assert r.status_code == 200, r.text
    print(f"\n[web] GET dossier -> statut = {r.json()['dossier']['statut']!r}")
    assert r.json()["dossier"]["statut"] == "en_traitement", (
        "la 1ère ouverture consultant aurait dû faire passer 'recu' -> 'en_traitement' "
        "(correctif de cette tâche, main.py:consultant_detail_dossier)"
    )
    print("✅ Transition automatique 'recu' -> 'en_traitement' confirmée EN BASE.")

    r = client.get(f"/consultant/dossiers/{dossier_id}/formulaires")
    assert r.status_code == 200, r.text

    if lancer_ocr:
        print("[web] POST /ocr-cni (peut prendre plusieurs minutes, vraies photos)...")
        r_ocr = client.post(f"/consultant/dossiers/{dossier_id}/ocr-cni")
        assert r_ocr.status_code == 200, r_ocr.text
        print(f"✅ OCR réel exécuté : {len(r_ocr.json()['formulaires'])} formulaire(s) mis à jour.")

    r_analyse = client.post(f"/consultant/dossiers/{dossier_id}/analyser")
    assert r_analyse.status_code == 200, r_analyse.text
    analyse = r_analyse.json()
    print(f"[web] Analyse assistant : ocr_disponible={analyse['ocr_disponible']}, "
          f"{len(analyse['incoherences'])} incohérence(s), champs_a_verifier={analyse['champs_a_verifier']}")

    formulaires = list_document_formulaires(dossier_id)
    formulaire_certificat = next(f for f in formulaires if f["type_document"] == "certificat_naissance")
    for nom, valeur in {
        "prenomEnfant": "Ibrahima", "nomFamilleEnfant": "Diallo", "sexe": "M",
        "prenomPere": "Modou", "prenomMere": "Aïssatou", "nomFamilleMere": "Ba",
        "dateNaissanceLettres": "neuf août deux mille vingt-six",
    }.items():
        rp = client.patch(
            f"/consultant/dossiers/{dossier_id}/formulaires/{formulaire_certificat['id']}",
            json={"nom": nom, "valeur": valeur},
        )
        assert rp.status_code == 200, rp.text

    formulaire_acte = get_or_create_formulaire_acte(dossier_id)
    for nom, valeur in {
        "numeroActe": "0000000000000000452", "anneeRegistreLettres": "Deux mille vingt-six",
        "anneeRegistreChiffres": "2026", "numeroRegistreLettres": "Quatre cent cinquante-deux",
        "numeroRegistreChiffres": "452", "officierEtatCivil": "Gorgui Mbodji",
    }.items():
        formulaire_acte = update_champ_formulaire(formulaire_acte, nom, valeur=valeur)
    print("[web] Champs manuels (certificat + acte) complétés par le consultant.")

    r_gen = client.post(f"/consultant/dossiers/{dossier_id}/generer")
    assert r_gen.status_code == 200, r_gen.text
    print(f"✅ Document généré (version {r_gen.json()['version']}).")
    dossier_genere = get_dossier(dossier_id)
    assert dossier_genere["statut"] == "genere"

    r_valider = client.post(f"/consultant/dossiers/{dossier_id}/valider")
    assert r_valider.status_code == 200, r_valider.text
    dossier_valide = get_dossier(dossier_id)
    assert dossier_valide["statut"] == "en_attente_validation_citoyen"
    print("✅ Dossier -> 'en_attente_validation_citoyen' (envoyé au citoyen).")

    main.app.dependency_overrides.pop(main.get_current_consultant, None)


async def test_i1_parcours_complet():
    print("\n" + "=" * 78 + "\n=== I.1 — Parcours complet, cas « dans les délais » ===\n" + "=" * 78)
    sequence_statuts = []

    dossier_id = await construire_dossier_jusqu_a_recu()
    sequence_statuts.append(get_dossier(dossier_id)["statut"])

    completer_cote_consultant(dossier_id, lancer_ocr=True)
    sequence_statuts.append("en_traitement")  # confirmé dans completer_cote_consultant
    sequence_statuts.append(get_dossier(dossier_id)["statut"])  # 'en_attente_validation_citoyen' (genere traversé entre les deux)

    # --- Retour côté citoyen (mobile) pour la validation finale (H.3) ---
    main.app.dependency_overrides[main.get_current_user] = lambda: {"id": TEST_CITOYEN_ID, "commune": TEST_COMMUNE}

    r_detail = client.get(f"/mes-dossiers/{dossier_id}")
    assert r_detail.status_code == 200, r_detail.text
    document_genere = r_detail.json()["document_genere"]
    assert document_genere and document_genere.get("url_signee"), "aucun document généré visible côté citoyen"
    print(f"\n[mobile] GET mon dossier -> document généré visible, url_signee présente.")

    # Téléchargeable RÉELLEMENT (pas juste une URL qui existe) : critère explicite I.1.
    resp_pdf = httpx.get(document_genere["url_signee"], timeout=15.0)
    assert resp_pdf.status_code == 200 and resp_pdf.content[:4] == b"%PDF", (
        f"le PDF signé n'est pas réellement téléchargeable (statut={resp_pdf.status_code}, "
        f"début={resp_pdf.content[:20]!r})"
    )
    print(f"✅ PDF réellement téléchargeable ({len(resp_pdf.content)} octets, en-tête %PDF confirmé).")

    r_valide = client.post(f"/mes-dossiers/{dossier_id}/valider")
    assert r_valide.status_code == 200, r_valide.text
    dossier_final = get_dossier(dossier_id)
    assert dossier_final["statut"] == "finalise"
    sequence_statuts.append("finalise")
    print(f"✅ Dossier -> 'finalise' (validé par le citoyen, mobile).")

    main.app.dependency_overrides.pop(main.get_current_user, None)

    print(f"\nSéquence de statuts traversée : {sequence_statuts}")
    assert sequence_statuts == ["recu", "en_traitement", "en_attente_validation_citoyen", "finalise"], sequence_statuts
    print("\n✅ Tâche I.1 validée : recu -> en_traitement -> genere -> en_attente_validation_citoyen -> finalise, "
          "PDF généré, validé côté citoyen, réellement téléchargeable.")


async def test_i2_boucle_correction():
    print("\n" + "=" * 78 + "\n=== I.2 — Cas particulier (incohérence réelle) + boucle de correction ===\n" + "=" * 78)

    # Nom du dialogue DÉLIBÉRÉMENT différent du nom réel sur la CNI utilisateur
    # (Morlaye Cisse) -> vraie incohérence détectable par l'OCR (K.6), pas
    # fabriquée à la main.
    # OCR non relancé ici (déjà validé réellement K.2/K.5/K.6, y compris
    # l'incohérence nom dialogue/OCR sur ce même type de dossier) — I.2 ne
    # teste pas l'OCR, juste l'escalade de la boucle de correction, et la
    # vraie détection OCR prend plusieurs minutes, inutile de la relancer ici.
    dossier_id = await construire_dossier_jusqu_a_recu(citoyen_nom_declarant="Modou Diallo")
    completer_cote_consultant(dossier_id, lancer_ocr=False)

    main.app.dependency_overrides[main.get_current_user] = lambda: {"id": TEST_CITOYEN_ID, "commune": TEST_COMMUNE}

    dossier_avant = get_dossier(dossier_id)
    assert dossier_avant.get("nb_iterations_correction", 0) == 0

    for i in range(1, 4):
        r = client.post(f"/mes-dossiers/{dossier_id}/demander-corrections", json={"texte": f"Correction demandée #{i} : merci de vérifier le nom du déclarant."})
        assert r.status_code == 200, r.text
        dossier_apres = r.json()["dossier"]
        print(f"[mobile] demande de correction {i}/3 -> statut={dossier_apres['statut']!r}, "
              f"nb_iterations_correction={dossier_apres['nb_iterations_correction']}")
        assert dossier_apres["nb_iterations_correction"] == i

        if i < 3:
            assert dossier_apres["statut"] == "corrections_demandees", dossier_apres
            # Le consultant régénère (simplifié : renvoie direct en attente de validation
            # comme le ferait un vrai cycle F.5 régénération -> valider).
            main.app.dependency_overrides[main.get_current_consultant] = lambda: {"id": "consultant-test", "commune": TEST_COMMUNE}
            r_gen = client.post(f"/consultant/dossiers/{dossier_id}/generer")
            assert r_gen.status_code == 200, r_gen.text
            r_val = client.post(f"/consultant/dossiers/{dossier_id}/valider")
            assert r_val.status_code == 200, r_val.text
            main.app.dependency_overrides.pop(main.get_current_consultant, None)
        else:
            assert dossier_apres["statut"] == "bloque", (
                f"attendu 'bloque' au 3e appel, obtenu {dossier_apres['statut']!r} — "
                f"le correctif nb_iterations_correction de demander_corrections ne fonctionne pas"
            )
            print("✅ Escalade à 'bloque' confirmée EN BASE au 3e appel.")

    main.app.dependency_overrides.pop(main.get_current_user, None)

    r_supervision = client.get("/admin/supervision", headers={}, )
    # /admin/supervision exige get_current_admin — override le temps de vérifier.
    main.app.dependency_overrides[main.get_current_admin] = lambda: {"id": "admin-test", "commune": "National"}
    r_supervision = client.get("/admin/supervision")
    assert r_supervision.status_code == 200, r_supervision.text
    ids_bloques = [d["id"] for d in r_supervision.json()["dossiers_bloques"]]
    assert dossier_id in ids_bloques, "le dossier bloqué (boucle post-génération) n'apparaît pas dans la supervision (G.3)"
    print("✅ Visible dans /admin/supervision (dossiers_bloques), comme demandé par le critère de validation I.2.")
    main.app.dependency_overrides.pop(main.get_current_admin, None)

    print("\n✅ Tâche I.2 validée : compteur de corrections post-génération incrémenté correctement, "
          "escalade 'bloque' au 3e tour, visible dans la supervision admin.")


async def main_test():
    await test_i1_parcours_complet()
    await test_i2_boucle_correction()
    print("\n" + "=" * 78 + "\n✅✅ Sprint I (I.1 + I.2) validé de bout en bout, prêt pour le déploiement VPS.\n" + "=" * 78)


if __name__ == "__main__":
    asyncio.run(main_test())
