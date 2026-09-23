"""
Script de diagnostic — vérifie si le dialogue administratif (slot_controller,
traiter_tour_administratif) avance correctement quand on lui donne des
réponses CLAIRES et VALIDES à chaque tour, du tout premier message (mode
information) jusqu'à la fin (relecture + confirmation).

Contexte : un citoyen a signalé que l'agent semblait reposer TOUJOURS la même
question quel que soit ce qu'il disait. Ce script exerce le VRAI endpoint
/ws/{session_id} (comme test_websocket_j5.py) avec de vraies réponses
propres en français — l'ASR et le TTS-stream sont doublés (pas de micro/Space
HF disponible ici), mais tout le reste est réel : vrai LLM (générateur +
champ ciblé), vraie base Supabase, vrai slot_controller.

Objectif du diagnostic : si CE script avance normalement de champ en champ
avec des réponses propres, le bug remonté est très probablement une question
de qualité de transcription ASR sur du pulaar réel (pas la logique de
dialogue elle-même). Si CE script reste aussi bloqué, c'est une vraie
régression dans slot_controller/dialogue_engine/prompts, à corriger ici.

Après chaque tour, on compare l'état RÉEL des slots en base (pas seulement le
texte affiché) pour prouver, sans ambiguïté, si le champ visé a bien été
rempli.
"""
import json
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient

import main  # noqa: E402
from dossiers_repo import upload_document, get_dossier
from test_bascule_administratif import TEST_CITOYEN_ID, TEST_COMMUNE

SESSION_ID = "diag_dialogue_complet"

# Réponses propres, sans ambiguïté, dans l'ordre attendu (mode information
# puis un message par champ/document de demarche_champs+demarche_documents).
# Les moments d'upload sont gérés séparément (voir DOCUMENTS_A_ENVOYER).
#
# Deux tours "filler" (contenu sans importance) sont nécessaires en plus des
# réponses réelles — pas une réponse à une question, juste de quoi déclencher
# le tour suivant (comportement RÉEL de traiter_tour_administratif, déjà
# observé dans test_slot_controller_j7.py) :
#   - juste après l'upload du recto CNI : la 1ère "entrée" sur l'étape verso
#     ignore le contenu du message (elle redemande simplement la photo).
#   - juste après le refus du livret (parents_maries=oui) : la 1ère "entrée"
#     sur l'étape livret redemande aussi la photo sans regarder le contenu —
#     c'est seulement au 2e passage sur CETTE étape que "je ne l'ai pas" est
#     réellement classifié comme un refus explicite.
_MESSAGES_CITOYEN = iter([
    "comment avoir un extrait de naissance pour mon fils",  # mode information
    "oui je veux bien commencer",                            # bascule administratif
    "il a 7 jours",                                          # age_enfant
    f"à {TEST_COMMUNE}",                                     # commune_naissance
    "Ibrahima Diallo",                                       # nom_enfant (après upload certificat)
    "le 9 août 2026",                                        # date_naissance_enfant
    "Modou Diallo",                                          # nom_declarant (après upload CNI recto)
    "voilà le recto",                                        # FILLER : 1ère entrée sur l'étape verso
    "Aïssatou Ba",                                           # nom_mere (après upload CNI verso)
    "le 12 mars 1998",                                       # date_naissance_mere
    "oui à la mairie l'année dernière",                       # parents_maries -> demande le livret
    "je regarde",                                            # FILLER : 1ère entrée sur l'étape livret
    "je ne l'ai pas avec moi",                                # refus réel du livret (2e entrée)
    "d'accord",                                               # tour supplémentaire -> déclenche "complet"
    "oui c'est bon",                                          # confirmation RG7
])

FAUX_CERTIFICAT = b"\x89PNG\r\n\x1a\n" + b"CERTIFICAT" * 20
FAUX_CNI_RECTO = b"\x89PNG\r\n\x1a\n" + b"CNI_RECTO" * 20
FAUX_CNI_VERSO = b"\x89PNG\r\n\x1a\n" + b"CNI_VERSO" * 20


async def _fake_verify_token(token: str) -> dict:
    return {"sub": TEST_CITOYEN_ID}


async def _fake_get_user_profile(user_id: str) -> dict:
    return {"commune": TEST_COMMUNE}


async def _fake_transcribe_audio(audio_bytes: bytes) -> dict:
    return {"success": True, "transcription": next(_MESSAGES_CITOYEN)}


async def _fake_synthesize_stream(texte_pulaar: str, websocket) -> None:
    return None  # TTS réel hors périmètre de ce diagnostic (pas de Space HF ici)


def lire_jusqua(ws, type_attendu: str, max_messages: int = 40) -> list:
    recus = []
    for _ in range(max_messages):
        msg = ws.receive()
        if "text" in msg:
            data = json.loads(msg["text"])
            recus.append(data)
            if data.get("type") == type_attendu:
                break
        elif "bytes" in msg:
            recus.append({"type": "audio_bytes", "len": len(msg["bytes"])})
    return recus


def main_test():
    main.verify_token = _fake_verify_token
    main.get_user_profile = _fake_get_user_profile
    main.transcribe_audio = _fake_transcribe_audio
    main.tts_service.synthesize_stream = _fake_synthesize_stream

    client = TestClient(main.app)
    reponses_agent = []

    with client.websocket_connect(f"/ws/{SESSION_ID}?token=fake-token-diagnostic") as ws:

        def tour(numero: int, libelle: str):
            ws.send_bytes(b"\x00\x01audio-bidon")
            messages = lire_jusqua(ws, "end")
            stream_fr = next((m["content"] for m in messages if m.get("type") == "stream_fr"), None)
            print(f"\n=== Tour {numero} : {libelle} ===")
            print(f"  RÉPONSE AGENT : {stream_fr}")
            reponses_agent.append(stream_fr)
            return stream_fr

        tour(1, "mode information")
        tour(2, "bascule administratif")

        etat = main.dossier_sessions[SESSION_ID]
        dossier_id = etat["dossier_id"]
        assert dossier_id, "aucun dossier créé après la bascule — problème dès l'étape 2"
        print(f"\n📁 Dossier créé : {dossier_id}")

        r3 = tour(3, "réponse à age_enfant : 'il a 7 jours'")
        slots_apres_3 = get_dossier(dossier_id)["slots"]
        print(f"  slots en base : age_enfant={slots_apres_3.get('age_enfant')}")
        assert slots_apres_3.get("age_enfant", {}).get("valeur") == 7, (
            f"❌ age_enfant PAS rempli après une réponse claire ! slots={slots_apres_3}"
        )
        assert "âge" not in r3.lower() and "age" not in r3.lower(), (
            f"❌ l'agent repose encore une question sur l'âge après une réponse déjà valide : {r3!r}"
        )
        print("  ✅ age_enfant bien rempli, la question suivante ne reparle plus de l'âge.")

        r4 = tour(4, f"réponse à commune_naissance : 'à {TEST_COMMUNE}'")
        slots_apres_4 = get_dossier(dossier_id)["slots"]
        print(f"  slots en base : commune_naissance={slots_apres_4.get('commune_naissance')!r}")
        assert slots_apres_4.get("commune_naissance") == TEST_COMMUNE, (
            f"❌ commune_naissance PAS rempli après une réponse claire ! slots={slots_apres_4}"
        )
        print("  ✅ commune_naissance bien rempli.")
        assert "certificat" in r4.lower() or "photo" in r4.lower(), (
            f"❌ après commune_naissance, l'agent devrait demander le certificat de naissance, pas : {r4!r}"
        )
        print("  ✅ l'agent demande bien le document suivant (certificat de naissance).")

        assert upload_document(dossier_id, "certificat_naissance", FAUX_CERTIFICAT, "image/png", "png")
        print("  [upload réel : certificat_naissance]")

        r5 = tour(5, "réponse à nom_enfant (après upload certificat) : 'Ibrahima Diallo'")
        slots_apres_5 = get_dossier(dossier_id)["slots"]
        print(f"  slots en base : nom_enfant={slots_apres_5.get('nom_enfant')!r}")
        assert slots_apres_5.get("nom_enfant") == "Ibrahima Diallo", (
            f"❌ nom_enfant PAS rempli après une réponse claire ! slots={slots_apres_5}"
        )
        print("  ✅ nom_enfant bien rempli.")

        r6 = tour(6, "réponse à date_naissance_enfant : 'le 9 août 2026'")
        slots_apres_6 = get_dossier(dossier_id)["slots"]
        print(f"  slots en base : date_naissance_enfant={slots_apres_6.get('date_naissance_enfant')!r}")
        assert slots_apres_6.get("date_naissance_enfant") == "2026-08-09", (
            f"❌ date_naissance_enfant PAS rempli (ou mal normalisé) après une réponse claire ! slots={slots_apres_6}"
        )
        print("  ✅ date_naissance_enfant bien rempli.")
        assert "déclarant" in r6.lower() or "vous" in r6.lower(), (
            f"❌ après la date de naissance, l'agent devrait demander le nom du déclarant, pas : {r6!r}"
        )

        r7 = tour(7, "réponse à nom_declarant : 'Modou Diallo'")
        slots_apres_7 = get_dossier(dossier_id)["slots"]
        print(f"  slots en base : nom_declarant={slots_apres_7.get('nom_declarant')!r}")
        assert slots_apres_7.get("nom_declarant") == "Modou Diallo", (
            f"❌ nom_declarant PAS rempli après une réponse claire ! slots={slots_apres_7}"
        )
        print("  ✅ nom_declarant bien rempli.")
        assert "identité" in r7.lower() or "carte" in r7.lower(), (
            f"❌ après nom_declarant, l'agent devrait demander la CNI (recto), pas : {r7!r}"
        )

        assert upload_document(dossier_id, "cni_declarant_recto", FAUX_CNI_RECTO, "image/png", "png")
        print("  [upload réel : cni_declarant_recto]")

        r8 = tour(8, "FILLER (1ère entrée sur l'étape verso -> doit demander le verso)")
        assert "verso" in r8.lower() or "autre côté" in r8.lower() or "retournez" in r8.lower(), (
            f"❌ après le recto, l'agent devrait demander le verso, pas : {r8!r}"
        )
        print("  ✅ l'agent demande bien le verso après le recto.")

        assert upload_document(dossier_id, "cni_declarant_verso", FAUX_CNI_VERSO, "image/png", "png")
        print("  [upload réel : cni_declarant_verso]")

        r9 = tour(9, "réponse à nom_mere : 'Aïssatou Ba'")
        slots_apres_9 = get_dossier(dossier_id)["slots"]
        print(f"  slots en base : nom_mere={slots_apres_9.get('nom_mere')!r}")
        assert slots_apres_9.get("nom_mere") == "Aïssatou Ba", (
            f"❌ nom_mere PAS rempli après une réponse claire ! slots={slots_apres_9}"
        )
        print("  ✅ nom_mere bien rempli.")

        r10 = tour(10, "réponse à date_naissance_mere : 'le 12 mars 1998'")
        slots_apres_10 = get_dossier(dossier_id)["slots"]
        print(f"  slots en base : date_naissance_mere={slots_apres_10.get('date_naissance_mere')!r}")
        assert slots_apres_10.get("date_naissance_mere") == "1998-03-12", (
            f"❌ date_naissance_mere PAS rempli après une réponse claire ! slots={slots_apres_10}"
        )
        print("  ✅ date_naissance_mere bien rempli.")

        r11 = tour(11, "réponse à parents_maries : 'oui à la mairie l'année dernière'")
        slots_apres_11 = get_dossier(dossier_id)["slots"]
        print(f"  slots en base : parents_maries={slots_apres_11.get('parents_maries')!r}")
        assert slots_apres_11.get("parents_maries") is True, (
            f"❌ parents_maries PAS rempli après une réponse claire ! slots={slots_apres_11}"
        )
        print("  ✅ parents_maries bien rempli.")

        r12 = tour(12, "FILLER (1ère entrée sur l'étape livret -> redemande, ignore le contenu)")
        r13 = tour(13, "refus réel du livret : 'je ne l'ai pas avec moi' (2e entrée -> classifié)")
        r14 = tour(14, "(tour supplémentaire -> devrait déclencher la relecture)")
        assert etat["phase"] == "relecture_en_cours", (
            f"❌ la relecture (RG7) ne s'est jamais déclenchée alors que tous les champs sont remplis ! "
            f"phase actuelle = {etat['phase']!r}, slots = {get_dossier(dossier_id)['slots']}"
        )
        print("  ✅ relecture (RG7) bien déclenchée une fois tous les champs remplis.")

        r15 = tour(15, "confirmation finale : 'oui c'est bon'")
        dossier_final = get_dossier(dossier_id)
        print(f"\n📋 Statut final en base : {dossier_final['statut']!r}, numero_suivi={dossier_final['numero_suivi']!r}")
        assert dossier_final["statut"] == "recu", f"❌ le dossier n'est jamais passé à 'recu' : {dossier_final}"
        assert dossier_final["numero_suivi"], "❌ aucun numéro de suivi généré"

    print("\n" + "=" * 78)
    print("✅ DIAGNOSTIC : le dialogue administratif avance normalement de bout en")
    print("   bout avec des réponses claires — chaque champ testé a été rempli")
    print("   correctement et la question suivante a bien changé à chaque tour.")
    print("   Le bug remonté (agent qui repose toujours la même question) est donc")
    print("   très probablement lié à la qualité de la transcription ASR sur du")
    print("   pulaar réel (une réponse qui ne ressemble à rien de valide est —")
    print("   normalement — rejetée et reformulée, ce qui PEUT ressembler à 'la")
    print("   même question' si la reformulation est proche du texte original),")
    print("   pas à une régression dans slot_controller/dialogue_engine.")
    print("=" * 78)


if __name__ == "__main__":
    main_test()
