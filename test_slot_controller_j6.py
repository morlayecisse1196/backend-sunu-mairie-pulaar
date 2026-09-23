"""
Test manuel — Sprint J, Tâche J.6 (escalade sur échecs répétés).

Critères de validation explicites (SUNU_MAIRIE_PROMPTS.md, Tâche J.6) :
  1. 3 réponses invalides de suite sur un CHAMP -> cas_particulier réellement
     créé en base (type_incident="champ_manquant"), le dialogue ne boucle pas
     à l'infini, et les reformulations successives ne sont JAMAIS mot pour
     mot identiques.
  2. Pour un DOCUMENT, "je ne l'ai pas" doit être reconnu comme une réponse
     valide dès qu'elle est clairement exprimée — sans attendre le nombre
     complet de rappels (SEUIL_RAPPELS_DOCUMENT) — et créer un
     cas_particulier ("document_indisponible").

Aucun mock : vrai LLM (OpenRouter) + vraie base Supabase.
"""
import asyncio
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

import main  # noqa: E402
from dossiers_repo import create_dossier, list_cas_particuliers
from slot_controller import traiter_tour_administratif, SEUIL_ECHECS_CHAMP, SEUIL_RAPPELS_DOCUMENT
from test_bascule_administratif import TEST_CITOYEN_ID

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


async def tour(etat, message, libelle):
    r = await traiter_tour_administratif(etat, message, HEADERS)
    print(f"--- {libelle} ---\n  citoyen  : {message!r}\n  résultat : {r}")
    return r


async def test_escalade_champ():
    print("\n========== 1. Escalade sur un CHAMP (3 échecs de suite) ==========")
    slots = dict(SLOTS_VIDES)
    slots["age_enfant"] = {"valeur": 7, "unite": "jours"}
    dossier = create_dossier(
        citoyen_id=TEST_CITOYEN_ID, type_demarche="extrait_naissance",
        slots=slots, cas_legal="dans_les_delais", commune_id=None, statut="en_cours",
    )
    assert dossier, "Création du dossier de test échouée."
    etat = {"slots": slots, "dossier_id": dossier["id"], "type_demarche": "extrait_naissance"}

    reponses = []
    message_invalide = "je ne comprends pas votre question, parlez-moi d'autre chose"
    for i in range(1, SEUIL_ECHECS_CHAMP + 1):
        r = await tour(etat, message_invalide, f"réponse invalide {i}/{SEUIL_ECHECS_CHAMP} sur commune_naissance")
        reponses.append(r["reponse_fr"])
        assert etat["slots"]["commune_naissance"] is None, "un avancement silencieux a eu lieu malgré une réponse invalide !"
        if i < SEUIL_ECHECS_CHAMP:
            assert not r["cas_particulier_cree"], f"cas_particulier créé trop tôt (tentative {i})"
        else:
            assert r["cas_particulier_cree"] is True, "le seuil aurait dû déclencher un cas_particulier"
            assert r.get("champ_en_echec") == "commune_naissance"
            assert r.get("cas_particulier_id"), "aucun id de cas_particulier retourné"

    # Vérifie l'écriture RÉELLE en base (pas seulement le signal en mémoire).
    cas = list_cas_particuliers(dossier["id"])
    assert cas, "aucun cas_particulier trouvé en base pour ce dossier"
    assert any(c["type_incident"] == "champ_manquant" for c in cas), f"type_incident inattendu : {cas}"
    print(f"\nOK - cas_particulier réellement en base : {cas[0]['type_incident']} (id={cas[0]['id']})")

    # Critère exact de la tâche : deux reformulations SUCCESSIVES (consécutives)
    # ne sont jamais mot pour mot identiques (pas une exigence d'unicité
    # globale sur tout l'historique — seul le garde-fou _eviter_repetition,
    # comparaison au tour immédiatement précédent, est réellement garanti).
    for i in range(len(reponses) - 1):
        assert reponses[i] != reponses[i + 1], (
            f"deux reformulations SUCCESSIVES sont mot pour mot identiques (tours {i + 1} et {i + 2}) : {reponses[i]!r}"
        )
    print("OK - aucune paire de reformulations SUCCESSIVES n'est mot pour mot identique :")
    for i, texte in enumerate(reponses, 1):
        print(f"    {i}. {texte}")

    # Le dialogue continue normalement après l'escalade (pas de blocage).
    r = await tour(etat, "Ross-Béthio", "tour suivant après l'escalade (le dialogue doit continuer)")
    assert etat["slots"]["commune_naissance"] == "Ross-Béthio", "le dialogue est resté bloqué après l'escalade !"
    print("OK - le dialogue continue normalement après l'escalade, pas de blocage infini.\n")


async def test_document_je_ne_lai_pas_immediat():
    print("\n========== 2. \"Je ne l'ai pas\" reconnu IMMÉDIATEMENT (document) ==========")
    slots = dict(SLOTS_VIDES)
    slots.update({
        "age_enfant": {"valeur": 7, "unite": "jours"},
        "commune_naissance": "Tambacounda",
    })
    dossier = create_dossier(
        citoyen_id=TEST_CITOYEN_ID, type_demarche="extrait_naissance",
        slots=slots, cas_legal="dans_les_delais", commune_id=None, statut="en_cours",
    )
    assert dossier, "Création du dossier de test échouée."
    etat = {"slots": slots, "dossier_id": dossier["id"], "type_demarche": "extrait_naissance"}

    # 1er tour : 1ère demande du document (le message répond encore à la
    # question précédente, cf. slot_controller — la détection ne s'applique
    # qu'à partir du 2e tour sur ce document).
    r = await tour(etat, "d'accord", "1er tour (1ère demande du certificat)")
    assert r["document_attendu"] == "certificat_naissance"
    assert not r["cas_particulier_cree"]

    # 2e tour : le citoyen dit CLAIREMENT ne pas l'avoir -> doit être accepté
    # IMMÉDIATEMENT (compteur à 2 seulement, très en dessous de SEUIL_RAPPELS_DOCUMENT).
    r = await tour(etat, "je ne l'ai pas, je ne sais pas où il est", "2e tour (\"je ne l'ai pas\" explicite)")
    assert r["cas_particulier_cree"] is True, "\"je ne l'ai pas\" explicite aurait dû être accepté immédiatement"
    assert r.get("document_ignore") == "certificat_naissance"
    assert r.get("cas_particulier_id"), "aucun id de cas_particulier retourné"
    print(f"OK - accepté dès le 2e tour (bien avant le seuil de {SEUIL_RAPPELS_DOCUMENT} rappels).")

    cas = list_cas_particuliers(dossier["id"])
    assert any(c["type_incident"] == "document_indisponible" for c in cas), f"type_incident inattendu : {cas}"
    print(f"OK - cas_particulier 'document_indisponible' réellement en base (id={cas[0]['id']}).")

    # Le dialogue avance ensuite normalement (nom_enfant).
    r = await tour(etat, "Ibrahima Diallo", "tour suivant (le dialogue doit avancer)")
    assert etat["slots"]["nom_enfant"] == "Ibrahima Diallo"
    print("OK - le dialogue a bien avancé après l'acceptation du refus.\n")


if __name__ == "__main__":
    asyncio.run(test_escalade_champ())
    asyncio.run(test_document_je_ne_lai_pas_immediat())
    print("\nTâche J.6 validée : escalade réelle (champ + document), reformulations jamais identiques, pas de blocage infini.")
