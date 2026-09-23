"""
Tests d'intégration du WebSocket de dialogue (v1 et v2), sans réseau :
authentification, moteur, transcription et parole sont simulés ; le magasin de
sessions tourne sur une fausse persistance en mémoire.
"""
import asyncio
import io
import json
import time
import wave

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from routers import temps_reel as routeur_temps_reel
from temps_reel import connexion, relances
from temps_reel.moteur import ResultatTour
from temps_reel.registre import Registre
from temps_reel.sessions import MagasinSessions

JETONS = {"jeton-a": "citoyen-a", "jeton-b": "citoyen-b"}


class FaussePersistance:
    def __init__(self):
        self.lignes = {}

    def lignes_par_cle(self, cle):
        return [dict(l) for l in self.lignes.values() if l["cle_client"] == cle]

    def active_du_citoyen(self, citoyen_id):
        return next((dict(l) for l in self.lignes.values() if l["citoyen_id"] == citoyen_id and l["statut"] == "active"), None)

    def active_par_dossier(self, dossier_id):
        return next((dict(l) for l in self.lignes.values() if l.get("dossier_id") == dossier_id and l["statut"] == "active"), None)

    def inserer(self, ligne):
        self.lignes[ligne["id"]] = dict(ligne)

    def mettre_a_jour(self, session_id, ligne):
        self.lignes[session_id] = {**self.lignes.get(session_id, {}), **ligne, "id": session_id}


def _wav(duree=0.6):
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as fichier:
        fichier.setnchannels(1)
        fichier.setsampwidth(2)
        fichier.setframerate(16000)
        fichier.writeframes(b"\x10\x00" * int(16000 * duree))
    return tampon.getvalue()


@pytest.fixture
def environnement(monkeypatch):
    magasin = MagasinSessions(FaussePersistance())
    registre = Registre()
    scenario = {"resultat": ResultatTour("Bonjour, je vous écoute."), "duree_parole": 0.0, "messages_moteur": []}

    for module in (connexion, relances):
        monkeypatch.setattr(module, "magasin" if module is relances else "magasin_global", magasin)
        monkeypatch.setattr(module, "registre" if module is relances else "registre_global", registre)

    async def faux_verify(jeton):
        if jeton not in JETONS:
            raise HTTPException(status_code=401, detail="invalide")
        return {"sub": JETONS[jeton], "exp": int(time.time()) + 3600}

    async def faux_profil(_user_id):
        return {"commune": "Ross-Béthio", "role": "citoyen"}

    async def fausse_transcription(_wav):
        return {"success": True, "transcription": "Je veux un extrait de naissance"}

    async def faux_moteur(etat, texte, deps=None):
        scenario["messages_moteur"].append(texte)
        resultat = scenario["resultat"]
        if resultat.session_a_clore:
            etat["phase"] = "termine"
        return resultat

    async def fausse_parole(emetteur, *, texte_fr, contexte_question, premier_tour, turn_id, reponse=None):
        await asyncio.sleep(scenario["duree_parole"])
        await emetteur.envoyer_json({"type": "status", "state": "speaking", "turn_id": turn_id})
        await emetteur.envoyer_octets(b"RIFF-audio-pulaar")
        return "pulaar"

    monkeypatch.setattr(connexion, "verify_token", faux_verify)
    monkeypatch.setattr(connexion, "get_user_profile", faux_profil)
    monkeypatch.setattr(connexion, "transcribe_audio", fausse_transcription)
    monkeypatch.setattr(connexion.moteur, "traiter_message", faux_moteur)
    monkeypatch.setattr(connexion.parole, "dire", fausse_parole)
    monkeypatch.setattr(connexion, "_enregistrer_messages_sync", lambda etat, texte, reponse: ("conv-1", "msg-1"))
    monkeypatch.setattr(connexion, "_maj_pulaar_sync", lambda message_id, pulaar: None)

    app = FastAPI()
    app.include_router(routeur_temps_reel.router)
    with TestClient(app) as client:
        yield client, scenario, magasin, registre


def _lire(ws, jusqu_a_type, max_messages=40, **criteres):
    recus = []
    for _ in range(max_messages):
        message = ws.receive()
        if message.get("type") == "websocket.close":
            recus.append({"type": "__close__", "code": message.get("code")})
            return recus
        if message.get("bytes") is not None:
            recus.append({"type": "__audio__", "octets": message["bytes"]})
            continue
        donnees = json.loads(message["text"])
        recus.append(donnees)
        if donnees.get("type") == jusqu_a_type and all(donnees.get(k) == v for k, v in criteres.items()):
            return recus
    raise AssertionError(f"{jusqu_a_type} non reçu : {[m.get('type') for m in recus]}")


def _types(messages):
    return [m["type"] for m in messages]


def _connecter_v2(client, jeton="jeton-a", **extra):
    ws = client.websocket_connect("/ws/v2").__enter__()
    ws.send_json({"type": "auth", "token": jeton, **extra})
    return ws


def test_v2_jeton_invalide_ferme_en_4401(environnement):
    client, *_ = environnement
    with client.websocket_connect("/ws/v2") as ws:
        ws.send_json({"type": "auth", "token": "faux"})
        assert _lire(ws, "__close__")[-1]["code"] == 4401


def test_v2_premier_message_doit_etre_auth(environnement):
    client, *_ = environnement
    with client.websocket_connect("/ws/v2") as ws:
        ws.send_json({"type": "texte", "texte": "bonjour"})
        assert _lire(ws, "__close__")[-1]["code"] == 4401


def test_v2_auth_session_et_ping(environnement):
    client, *_ = environnement
    with client.websocket_connect("/ws/v2") as ws:
        ws.send_json({"type": "auth", "token": "jeton-a"})
        messages = _lire(ws, "status")
        assert _types(messages) == ["auth_ok", "session", "status"]
        assert messages[1]["reprise"] is False and messages[1]["mode"] == "information"
        ws.send_json({"type": "ping", "t": 42})
        assert _lire(ws, "pong")[-1]["t"] == 42


def test_v2_tour_texte_complet(environnement):
    client, scenario, *_ = environnement
    scenario["resultat"] = ResultatTour("Envoyez la photo du certificat.", document_attendu="certificat_naissance")
    with client.websocket_connect("/ws/v2") as ws:
        ws.send_json({"type": "auth", "token": "jeton-a"})
        _lire(ws, "status")
        ws.send_json({"type": "texte", "texte": "Bonjour", "turn_id": "t1"})
        messages = _lire(ws, "status", state="listening", turn_id="t1")
    types = _types(messages)
    assert types.index("transcription") < types.index("attente_upload") < types.index("stream_fr") < types.index("__audio__") < types.index("end")
    stream_fr = next(m for m in messages if m["type"] == "stream_fr")
    assert stream_fr["message_id"] == "msg-1" and stream_fr["turn_id"] == "t1"
    assert next(m for m in messages if m["type"] == "transcription")["texte"] == "Bonjour"


def test_v1_tour_audio_accuse_et_transcription(environnement):
    client, scenario, *_ = environnement
    with client.websocket_connect("/ws/cle-app?token=jeton-a") as ws:
        _lire(ws, "status")
        ws.send_bytes(_wav())
        messages = _lire(ws, "end")
    types = _types(messages)
    assert types[0] == "audio_recu"
    assert "transcription" in types and "stream_fr" in types
    assert scenario["messages_moteur"] == ["Je veux un extrait de naissance"]


def test_v1_audio_trop_court_erreur_recuperable(environnement):
    client, scenario, *_ = environnement
    with client.websocket_connect("/ws/cle-app?token=jeton-a") as ws:
        _lire(ws, "status")
        ws.send_bytes(_wav(0.05))
        erreur = _lire(ws, "error")[-1]
    assert erreur["code"] == "audio_trop_court" and erreur["recuperable"] is True
    assert scenario["messages_moteur"] == []


def test_v1_cle_d_un_autre_citoyen_refusee(environnement):
    client, _, magasin, _ = environnement
    asyncio.run(magasin.ouvrir(citoyen_id="citoyen-a", commune_profil="Dakar", cle_client="cle-victime"))
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/cle-victime?token=jeton-b") as ws:
            ws.receive()
    assert exc.value.code == 1008


def test_upload_en_attente_restitue_a_la_reconnexion(environnement):
    client, _, magasin, _ = environnement
    etat, _ = asyncio.run(magasin.ouvrir(citoyen_id="citoyen-a", commune_profil="Dakar", cle_client="cle-app"))
    etat.update(mode="administratif", dossier_id="d-1", document_en_attente="cni_declarant_verso")
    asyncio.run(magasin.enregistrer(etat))
    with client.websocket_connect("/ws/cle-app?token=jeton-a") as ws:
        messages = _lire(ws, "status")
    session = messages[0]
    assert session["reprise"] is True and session["document_attendu"] == "cni_declarant_verso"
    assert {"type": "attente_upload", "document_type": "cni_declarant_verso", "dossier_id": "d-1"} in messages


def test_demarche_envoyee_ouvre_une_nouvelle_session(environnement):
    client, scenario, *_ = environnement
    scenario["resultat"] = ResultatTour("Voilà, votre demande est envoyée.", session_a_clore=True)
    with client.websocket_connect("/ws/v2") as ws:
        ws.send_json({"type": "auth", "token": "jeton-a"})
        premiere_session = _lire(ws, "status")[1]
        ws.send_json({"type": "texte", "texte": "Oui c'est bon", "turn_id": "t9"})
        messages = _lire(ws, "end")
    nouvelle = next(m for m in messages if m["type"] == "session")
    assert nouvelle["nouvelle"] is True and nouvelle["session_id"] != premiere_session["session_id"]
    assert nouvelle["mode"] == "information"


def test_interruption_coupe_la_parole(environnement):
    client, scenario, *_ = environnement
    scenario["duree_parole"] = 5
    with client.websocket_connect("/ws/v2") as ws:
        ws.send_json({"type": "auth", "token": "jeton-a"})
        _lire(ws, "status")
        ws.send_json({"type": "texte", "texte": "Bonjour", "turn_id": "t2"})
        _lire(ws, "stream_fr")
        debut = time.monotonic()
        ws.send_json({"type": "interrupt"})
        messages = _lire(ws, "end")
    assert "interrompu" in _types(messages)
    assert "__audio__" not in _types(messages)
    assert time.monotonic() - debut < 3


def test_nouvelle_connexion_remplace_l_ancienne(environnement):
    client, *_ = environnement
    with client.websocket_connect("/ws/cle-app?token=jeton-a") as premiere:
        _lire(premiere, "status")
        with client.websocket_connect("/ws/cle-app?token=jeton-a") as seconde:
            _lire(seconde, "status")
            messages = _lire(premiere, "__close__")
    assert "session_remplacee" in _types(messages)
    assert messages[-1]["code"] == 4409


def test_relance_apres_upload_poussee_sur_la_connexion(environnement, monkeypatch):
    client, _, magasin, _ = environnement

    async def fausse_relance(etat, deps=None):
        etat["document_en_attente"] = "cni_declarant_verso"
        return ResultatTour("Merci, photo bien reçue. Retournez la carte.", document_attendu="cni_declarant_verso")

    monkeypatch.setattr(relances.moteur, "apres_document_recu", fausse_relance)
    with client.websocket_connect("/ws/cle-app?token=jeton-a") as ws:
        session = _lire(ws, "status")[0]
        etat = magasin.obtenir(session["session_id"])
        etat.update(mode="administratif", dossier_id="d-7")
        assert client.portal.call(relances.relancer_apres_document, "d-7", "cni_declarant_recto") is True
        messages = _lire(ws, "end")
    types = _types(messages)
    assert types.index("document_recu") < types.index("attente_upload") < types.index("stream_fr")
    assert next(m for m in messages if m["type"] == "stream_fr")["content"].startswith("Merci, photo bien reçue")
