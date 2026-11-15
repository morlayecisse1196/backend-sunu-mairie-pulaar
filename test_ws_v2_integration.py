"""
Test d'intégration du protocole temps réel **v2** (`/ws/v2`) contre un serveur
qui tourne vraiment.

Pourquoi ce fichier : les 46 scripts `test_*.py` de la racine visent tous le
protocole **v1** (`/ws/{session_id}?token=`), figé. Le v2 — celui que le mobile
utilise et que le futur front web utilisera — n'était vérifié que par
`tests/unit/test_ws_temps_reel.py`, avec ASR, TTS, LLM et Supabase remplacés
par des doublures. Rien ne vérifiait le protocole sur le vrai serveur.

Deux séries :
- **Série A — sans compte** : poignée de main, refus d'authentification, délai
  des 10 secondes. Tourne toujours, c'est le filet de sécurité.
- **Série B — avec compte** : un tour de dialogue complet, chronométré étape
  par étape, et le remplacement de session. Demande un JWT Supabase valide,
  soit dans `TEST_SUPABASE_TOKEN`, soit obtenu par `TEST_CITOYEN_EMAIL` +
  `TEST_CITOYEN_MOT_DE_PASSE` (compte citoyen de test, jamais un vrai citoyen).

Usage :
    venv\\Scripts\\python.exe test_ws_v2_integration.py
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time

import httpx
import websockets
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

BASE_HTTP = os.getenv("TEST_BASE_URL", "http://127.0.0.1:8000")
BASE_WS = BASE_HTTP.replace("http", "ws", 1)
URL_V2 = f"{BASE_WS}/ws/v2"

# Le serveur ferme en 4408 si `auth` n'arrive pas dans les 10 s : on laisse une
# marge, sinon le test conclut à tort que la règle n'est pas appliquée.
DELAI_AUTH = 14

_ok = 0
_ko = 0


def verdict(reussi: bool, titre: str, detail: str = "") -> None:
    global _ok, _ko
    if reussi:
        _ok += 1
    else:
        _ko += 1
    print(f"  {'OK   ' if reussi else 'ECHEC'}  {titre}" + (f"\n          {detail}" if detail else ""))


def expiration(jeton: str):
    try:
        charge = jeton.split(".")[1]
        charge += "=" * (-len(charge) % 4)
        return int(json.loads(base64.urlsafe_b64decode(charge))["exp"])
    except Exception:
        return None


async def obtenir_jeton():
    """
    Un JWT utilisable : celui du `.env` s'il est encore valide, sinon une
    connexion par mot de passe. Jamais de jeton fabriqué localement — l'auth du
    backend ne vérifie que des signatures asymétriques issues du JWKS Supabase
    (cf. ALGORITHMES_AUTORISES dans auth.py), c'est voulu.
    """
    jeton = os.getenv("TEST_SUPABASE_TOKEN")
    if jeton:
        exp = expiration(jeton)
        if exp and exp > time.time() + 60:
            quand = time.strftime("%Y-%m-%d %H:%M", time.localtime(exp))
            print(f"  jeton de .env valide jusqu'au {quand}")
            return jeton
        quand = time.strftime("%Y-%m-%d", time.localtime(exp)) if exp else "illisible"
        print(f"  TEST_SUPABASE_TOKEN expiré ({quand})")

    email = os.getenv("TEST_CITOYEN_EMAIL")
    mot_de_passe = os.getenv("TEST_CITOYEN_MOT_DE_PASSE")
    if not (email and mot_de_passe):
        return None

    url = os.environ["SUPABASE_URL"].rstrip("/")
    cle = os.environ["SUPABASE_KEY"]
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{url}/auth/v1/token",
            params={"grant_type": "password"},
            headers={"apikey": cle, "Content-Type": "application/json"},
            json={"email": email, "password": mot_de_passe},
        )
    if r.status_code != 200:
        print(f"  connexion refusée pour {email} : HTTP {r.status_code} {r.text[:120]}")
        return None
    print(f"  jeton frais obtenu pour {email}")
    return r.json()["access_token"]


# ------------------------------------------------------------------ série A


async def serie_a() -> None:
    print("\nSÉRIE A — poignée de main et refus (sans compte)")

    # La connexion s'ouvre sans jeton dans l'URL, puis un jeton invalide ferme
    # en 4401.
    try:
        async with websockets.connect(URL_V2, open_timeout=10) as ws:
            verdict(True, "la connexion s'ouvre sans jeton dans l'URL")
            await ws.send(json.dumps({"type": "auth", "token": "pas-un-jeton"}))
            try:
                while True:
                    brut = await asyncio.wait_for(ws.recv(), timeout=15)
                    if isinstance(brut, bytes):
                        continue
                    msg = json.loads(brut)
                    if msg.get("type") == "error":
                        print(f"          error reçu : {msg.get('code')}")
            except asyncio.TimeoutError:
                verdict(False, "jeton invalide → fermeture 4401", "aucune fermeture en 15 s")
            except websockets.ConnectionClosed as f:
                code = f.rcvd.code if f.rcvd else None
                verdict(code == 4401, "jeton invalide → fermeture 4401", f"code reçu : {code}")
    except Exception as e:
        verdict(False, "la connexion s'ouvre sans jeton dans l'URL", f"{type(e).__name__}: {e}")

    # Aucun `auth` : fermeture en 4408 au bout de 10 s. Sans cette règle, un
    # client muet immobilise une session côté serveur.
    try:
        async with websockets.connect(URL_V2, open_timeout=10) as ws:
            debut = time.monotonic()
            try:
                while True:
                    await asyncio.wait_for(ws.recv(), timeout=DELAI_AUTH)
            except asyncio.TimeoutError:
                verdict(False, "silence → fermeture 4408 en ~10 s",
                        f"toujours ouvert après {DELAI_AUTH} s")
            except websockets.ConnectionClosed as f:
                ecoule = time.monotonic() - debut
                code = f.rcvd.code if f.rcvd else None
                verdict(code == 4408, "silence → fermeture 4408 en ~10 s",
                        f"code {code} après {ecoule:.1f} s")
    except Exception as e:
        verdict(False, "silence → fermeture 4408 en ~10 s", f"{type(e).__name__}: {e}")

    # Premier message qui n'est pas `auth`.
    try:
        async with websockets.connect(URL_V2, open_timeout=10) as ws:
            await ws.send(json.dumps({"type": "ping", "t": 1}))
            recu = []
            try:
                while True:
                    brut = await asyncio.wait_for(ws.recv(), timeout=12)
                    if isinstance(brut, str):
                        recu.append(json.loads(brut).get("type"))
            except asyncio.TimeoutError:
                verdict(False, "premier message ≠ auth → refusé", f"reçu : {recu}")
            except websockets.ConnectionClosed as f:
                code = f.rcvd.code if f.rcvd else None
                verdict(code in (4401, 4408), "premier message ≠ auth → refusé",
                        f"code {code}, messages {recu}")
    except Exception as e:
        verdict(False, "premier message ≠ auth → refusé", f"{type(e).__name__}: {e}")


# ------------------------------------------------------------------ série B


async def authentifier(ws, jeton: str, **extra) -> dict:
    await ws.send(json.dumps({"type": "auth", "token": jeton, **extra}))
    vus: dict = {}
    debut = time.monotonic()
    while time.monotonic() - debut < 25:
        brut = await asyncio.wait_for(ws.recv(), timeout=25)
        if isinstance(brut, bytes):
            continue
        msg = json.loads(brut)
        vus[msg.get("type")] = msg
        if {"auth_ok", "session", "status"} <= set(vus):
            break
    return vus


async def serie_b(jeton: str) -> None:
    print("\nSÉRIE B — dialogue réel (compte authentifié)")

    session_id = None
    async with websockets.connect(URL_V2, open_timeout=15, max_size=None) as ws:
        t0 = time.monotonic()
        # Conversation neuve à chaque exécution : sur une session reprise, le
        # serveur peut rejouer une réponse non dite (contrat §4), et les durées
        # mesurées ne sont alors plus comparables d'un passage à l'autre.
        vus = await authentifier(ws, jeton, nouvelle_conversation=True)
        verdict("auth_ok" in vus, "auth_ok reçu", f"en {time.monotonic() - t0:.2f} s")
        verdict(vus.get("auth_ok", {}).get("protocole") == 2, "protocole annoncé = 2",
                f"reçu : {vus.get('auth_ok', {}).get('protocole')}")
        verdict(bool(vus.get("auth_ok", {}).get("exp")),
                "exp fourni (sans lui, auth_refresh est impossible)")
        interessant = ("mode", "phase", "statut", "reprise", "nouvelle")
        verdict("session" in vus, "session reçue",
                json.dumps({k: v for k, v in vus.get("session", {}).items() if k in interessant},
                           ensure_ascii=False))
        verdict(vus.get("status", {}).get("state") == "listening", "status listening")
        session_id = vus.get("session", {}).get("session_id")

        # ping / pong
        t = int(time.time() * 1000)
        debut = time.monotonic()
        await ws.send(json.dumps({"type": "ping", "t": t}))
        pong = None
        while time.monotonic() - debut < 15:
            brut = await asyncio.wait_for(ws.recv(), timeout=15)
            if isinstance(brut, str) and json.loads(brut).get("type") == "pong":
                pong = json.loads(brut)
                break
        verdict(pong is not None and pong.get("t") == t, "ping → pong avec le même t",
                f"aller-retour {(time.monotonic() - debut) * 1000:.0f} ms" if pong else "pas de pong")

        # un tour écrit complet, chronométré étape par étape
        question = os.getenv("TEST_QUESTION", "Je veux un extrait de naissance")
        print(f"\n  tour de dialogue : « {question} »")
        depart = time.monotonic()
        await ws.send(json.dumps({"type": "texte", "texte": question, "turn_id": "t-integration"}))

        jalons: list = []
        frames = 0
        octets = 0
        pulaar = ""
        dernier_pulaar = None
        fr = ""
        erreurs = []
        fini = False
        while not fini and time.monotonic() - depart < 180:
            reste = 180 - (time.monotonic() - depart)
            try:
                brut = await asyncio.wait_for(ws.recv(), timeout=reste)
            except asyncio.TimeoutError:
                break
            ecoule = time.monotonic() - depart

            if isinstance(brut, bytes):
                frames += 1
                octets += len(brut)
                jalons.append((ecoule, f"audio #{frames} ({len(brut)} o)"))
                continue

            msg = json.loads(brut)
            type_ = msg.get("type")
            if type_ == "stream_fr":
                fr = msg.get("content", "")
                jalons.append((ecoule, f"stream_fr ({len(fr)} car.)"))
            elif type_ == "stream_pulaar":
                # On horodate le PREMIER et le DERNIER incrément, pas chacun :
                # c'est la fenêtre de traduction qui nous intéresse. Sans ces
                # deux jalons, on voyait un trou de 12 s entre `stream_fr` et
                # la première trame audio sans pouvoir dire si la traduction
                # arrivait progressivement (donc affichable en sous-titres) ou
                # d'un bloc à la fin.
                if not pulaar:
                    jalons.append((ecoule, "stream_pulaar #1 (début traduction)"))
                pulaar += msg.get("content", "")
                dernier_pulaar = ecoule
            elif type_ == "error":
                erreurs.append(f"{msg.get('code')} (récupérable={msg.get('recuperable')})")
                jalons.append((ecoule, f"error {msg.get('code')}"))
            elif type_ == "end":
                jalons.append((ecoule, "end"))
                fini = True
            elif type_ == "pong":
                continue
            else:
                etiquette = type_
                if type_ in ("status", "etape", "lent"):
                    etiquette = f"{type_}:{msg.get('state') or msg.get('etape')}"
                elif type_ == "progression":
                    etiquette = f"progression {msg.get('faites')}/{msg.get('total')}"
                elif type_ == "tts_progress":
                    etiquette = f"tts_progress {msg.get('current')}"
                jalons.append((ecoule, etiquette))

        if dernier_pulaar is not None:
            jalons.append((dernier_pulaar, "stream_pulaar dernier (fin traduction)"))
            jalons.sort(key=lambda j: j[0])

        print("\n  chronologie du tour :")
        for ecoule, quoi in jalons:
            print(f"    {ecoule:7.2f} s  {quoi}")

        # Décomposition du temps, du point de vue d'un citoyen qui ne lit pas :
        # seul le premier SON compte, le texte français affiché avant ne lui
        # sert à rien.
        #
        # Attention à l'interprétation : voir l'audio arriver après la fin de
        # la traduction ne veut PAS dire que les phases ne se chevauchent pas.
        # `temps_reel/parole.py` lance bien la synthèse dès qu'une phrase est
        # complète dans le flux (`planifier`). Quand la traduction ne dure que
        # deux secondes, il n'y a simplement plus rien à recouvrir : ce qui
        # reste est le temps de synthèse lui-même.
        t_fr = next((e for e, q in jalons if q.startswith("stream_fr")), None)
        t_pulaar1 = next((e for e, q in jalons if q.startswith("stream_pulaar #1")), None)
        t_audio1 = next((e for e, q in jalons if q.startswith("audio #1")), None)

        print("\n  où part le temps :")
        if t_fr is not None:
            print(f"    réflexion (LLM générateur)      {t_fr:5.1f} s")
        if t_fr is not None and dernier_pulaar is not None:
            print(f"    traduction pulaar (LLM, en flux) {dernier_pulaar - t_fr:5.1f} s")
        if t_pulaar1 is not None and t_audio1 is not None:
            # Majorant du temps de synthèse de la première phrase : elle ne
            # peut pas avoir été planifiée avant le début de la traduction.
            print(f"    synthèse de la 1re phrase       {t_audio1 - t_pulaar1:5.1f} s  (au plus)")
        if t_audio1 is not None:
            print(f"    -> premier SON entendu à        {t_audio1:5.1f} s")
        if t_fr is not None and t_audio1 is not None:
            print(f"\n  silence après la réponse française : {t_audio1 - t_fr:.1f} s — "
                  f"un citoyen qui ne lit pas n'a rien du tout pendant ce temps.")
            print("  Levier déjà présent dans le code : une phrase relue dont l'audio est")
            print("  pré-généré saute la synthèse (catalogue_audio.audio_phrase), cf. la")
            print("  docstring de parole.dire. Reste à remplir la banque de phrases.")
        if fr:
            print(f"\n  réponse FR     : {fr[:220]}")
        if pulaar:
            print(f"  réponse pulaar : {pulaar[:220]}")

        verdict(fini, "le tour se termine par `end`",
                f"{len(jalons)} messages en {time.monotonic() - depart:.1f} s")
        verdict(bool(fr), "une réponse française est produite")
        verdict(bool(pulaar), "une traduction pulaar est produite")
        verdict(frames > 0, "de l'audio TTS arrive en trames binaires",
                f"{frames} trames, {octets} octets")
        premier = next((e for e, q in jalons if q.startswith("audio #1")), None)
        if premier is not None:
            verdict(premier < 30, "première phrase audible en moins de 30 s", f"{premier:.1f} s")
        if erreurs:
            print(f"  erreurs reçues : {erreurs}")

    # Deuxième tour : on accepte la démarche proposée. L'agent pose alors la
    # première question du formulaire — et CELLE-LÀ est une phrase relue, dont
    # l'audio est pré-généré. C'est le seul endroit où le gain se voit : le
    # premier tour passe par le mode information, qui produit du texte libre,
    # donc toujours traduit et synthétisé à la volée.
    if session_id:
        async with websockets.connect(URL_V2, open_timeout=15, max_size=None) as ws:
            await authentifier(ws, jeton, session_id=session_id)
            print("\n  tour 2 (chemin administratif) : « oui »")
            depart = time.monotonic()
            await ws.send(json.dumps({"type": "texte", "texte": "oui", "turn_id": "t-tour2"}))

            t_premier_audio = None
            t_fr2 = None
            frames2 = 0
            fini = False
            lents = []
            while not fini and time.monotonic() - depart < 120:
                reste = 120 - (time.monotonic() - depart)
                try:
                    brut = await asyncio.wait_for(ws.recv(), timeout=reste)
                except asyncio.TimeoutError:
                    break
                ecoule = time.monotonic() - depart
                if isinstance(brut, bytes):
                    frames2 += 1
                    if t_premier_audio is None:
                        t_premier_audio = ecoule
                    continue
                msg = json.loads(brut)
                if msg.get("type") == "stream_fr":
                    t_fr2 = ecoule
                elif msg.get("type") == "lent":
                    lents.append(f"{msg.get('etape')}@{ecoule:.1f}s")
                elif msg.get("type") == "end":
                    fini = True

            if t_fr2 is not None and t_premier_audio is not None:
                print(f"    réponse française à {t_fr2:.1f} s, premier SON à {t_premier_audio:.1f} s")
                print(f"    silence après la réponse française : {t_premier_audio - t_fr2:.1f} s")
            verdict(t_premier_audio is not None, "le 2e tour produit de l'audio",
                    f"{frames2} trames")
            if t_premier_audio is not None:
                verdict(t_premier_audio - (t_fr2 or 0) < 2.0,
                        "audio quasi immédiat après la réponse (phrase pré-générée)",
                        f"{t_premier_audio - (t_fr2 or 0):.2f} s d'écart"
                        + (f" ; lent reçu : {lents}" if lents else ""))

    # Une 2e connexion sur la même session prend la main : l'ancienne reçoit
    # session_remplacee puis la fermeture 4409.
    if session_id:
        async with websockets.connect(URL_V2, open_timeout=15) as a:
            await authentifier(a, jeton, session_id=session_id)
            async with websockets.connect(URL_V2, open_timeout=15) as b:
                await authentifier(b, jeton, session_id=session_id)
                code = None
                remplacee = False
                try:
                    debut = time.monotonic()
                    while time.monotonic() - debut < 20:
                        brut = await asyncio.wait_for(a.recv(), timeout=20)
                        if isinstance(brut, str) and json.loads(brut).get("type") == "session_remplacee":
                            remplacee = True
                except websockets.ConnectionClosed as f:
                    code = f.rcvd.code if f.rcvd else None
                except asyncio.TimeoutError:
                    pass
                verdict(code == 4409 or remplacee,
                        "2e connexion sur la même session → session_remplacee puis 4409",
                        f"session_remplacee={remplacee}, code={code}")


async def principal() -> None:
    print(f"Cible : {URL_V2}")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{BASE_HTTP}/health")
        print(f"/health : {r.status_code} {r.text}")
    except Exception as e:
        print(f"Serveur injoignable sur {BASE_HTTP} ({type(e).__name__}) — démarrez uvicorn d'abord.")
        return

    await serie_a()

    jeton = await obtenir_jeton()
    if jeton:
        await serie_b(jeton)
    else:
        print("\nSÉRIE B ignorée — aucun jeton utilisable.")
        print("  Renseignez dans .env, au choix :")
        print("    TEST_SUPABASE_TOKEN=<JWT frais>")
        print("    TEST_CITOYEN_EMAIL=… et TEST_CITOYEN_MOT_DE_PASSE=…  (compte citoyen de test)")

    print(f"\nRésultat : {_ok} OK, {_ko} échec(s)")
    sys.exit(1 if _ko else 0)


if __name__ == "__main__":
    asyncio.run(principal())
