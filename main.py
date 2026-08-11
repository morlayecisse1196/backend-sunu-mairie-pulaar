from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends, Header, Response
from pydantic import BaseModel
import httpx
import json
import asyncio
import time
import os
from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL
# RAG sémantique (pgvector) avec filtrage par commune, avec repli automatique
# sur la recherche mot-clé (Supabase REST) si la connexion directe à la base échoue.
from search2 import search_demarches as _search_demarches_semantic, format_demarche_pour_prompt
from search import search_demarches as _search_demarches_keyword
from auth import verify_token, get_user_profile
from demarches_repo import list_communes, list_demarches, get_demarche_by_id
from prompts import (
    SYSTEM_PROMPT_GENERATOR,
    SYSTEM_PROMPT_FORMATTER,
    build_generator_prompt,
    build_formatter_prompt,
    build_narration_prompt
)
from asr_client import transcribe_audio
from tts_service import tts_service  # <-- Nouvel import TTS

app = FastAPI(title="Agent SUNU-LANGUES - Architecture deux phases avec Auth et TTS")

# Stockage des sessions en mémoire (historique de conversation)
sessions = {}
# Horodatage de dernière activité par session, pour purger les sessions abandonnées
session_last_seen = {}

# --- Configuration des modèles ---
# MODEL_GENERATOR = "openai/gpt-3.5-turbo"      # Phase 1 : génération de la réponse courte
MODEL_GENERATOR = "google/gemini-2.5-flash"      # Phase 1 : génération de la réponse courte
MODEL_FORMATTER = "google/gemini-2.5-flash"    # Phase 2 : traduction et formatage en dialogue

# --- Garde-fous temps réel ---
MAX_AUDIO_BYTES = 10 * 1024 * 1024      # ~10 Mo par tour de parole : au-delà, on refuse (anti-DoS / bug client)
HISTORY_TURNS_FOR_PROMPT = 3            # nombre d'échanges précédents réinjectés dans le prompt (multi-tours)
SESSION_TTL_SECONDS = 2 * 60 * 60       # une session inactive depuis 2h est purgée de la mémoire
# Le modèle TTS est un singleton chargé une seule fois : sans limite, plusieurs
# utilisateurs simultanés saturent le thread pool et la latence explose pour tout le monde.
TTS_CONCURRENCY = asyncio.Semaphore(2)
# Cache disque des narrations de démarches (voir POST /demarches/{id}/audio) : le TTS
# tourne sur CPU sur cette machine (~45s pour une narration complète), régénérer à
# chaque appel serait inutilisable côté mobile.
AUDIO_CACHE_DIR = "audio_cache"
os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)


async def call_openrouter(client: httpx.AsyncClient, headers: dict, payload: dict, retries: int = 1) -> dict:
    """
    Appelle OpenRouter (non-streaming) avec un retry court sur erreurs transitoires
    (timeout, erreur réseau, 5xx). Les erreurs 4xx (payload invalide, clé API, etc.)
    ne sont jamais retentées.
    """
    last_exc = None
    for attempt in range(retries + 1):
        try:
            response = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code < 500:
                raise
            last_exc = e
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            last_exc = e

        if attempt < retries:
            await asyncio.sleep(1.5 * (attempt + 1))

    raise last_exc


def search_demarches(query: str, commune: str = None, limit: int = 3) -> list:
    """
    Recherche RAG : tente d'abord la recherche sémantique (pgvector, connexion
    directe psycopg à Postgres). Si la connexion échoue (ex : hôte IPv6 injoignable —
    cas classique avec Supabase, voir DATABASE_URL dans .env), on se replie sur la
    recherche mot-clé via l'API REST Supabase (search.py), qui ne dépend pas d'une
    connexion DB directe. Ne lève jamais d'exception : un souci RAG ne doit jamais
    faire tomber tout le tour de conversation (ni la connexion WebSocket).
    """
    try:
        return _search_demarches_semantic(query, commune=commune, limit=limit)
    except Exception as e:
        print(f"⚠️ RAG sémantique indisponible ({e}) — repli sur la recherche mot-clé.")
        try:
            return _search_demarches_keyword(query, commune=commune, limit=limit)
        except Exception as e2:
            print(f"⚠️ RAG mot-clé également indisponible ({e2}) — aucune démarche retournée.")
            return []


async def cleanup_inactive_sessions():
    """Tâche de fond : purge les sessions en mémoire inactives depuis SESSION_TTL_SECONDS."""
    while True:
        await asyncio.sleep(600)  # vérification toutes les 10 minutes
        now = time.time()
        expired = [sid for sid, last in session_last_seen.items() if now - last > SESSION_TTL_SECONDS]
        for sid in expired:
            sessions.pop(sid, None)
            session_last_seen.pop(sid, None)
        if expired:
            print(f"🧹 {len(expired)} session(s) inactive(s) purgée(s) de la mémoire")


@app.on_event("startup")
async def on_startup():
    asyncio.create_task(cleanup_inactive_sessions())

# --- Pydantic Models ---

class ChatRequest(BaseModel):
    session_id: str
    message: str

class ChatResponse(BaseModel):
    reply: str

class SearchRequest(BaseModel):
    query: str

# --- Fonction utilitaire pour le résumé ultra-court ---

def get_resume_rag(results: list) -> str:
    """
    Génère un résumé ultra-court des résultats RAG (1-2 phrases max).
    """
    if not results:
        return "Aucune information spécifique disponible."
    
    demarche = results[0]
    nom = demarche.get('nom_demarche', '')
    docs = demarche.get('documents_requis', [])
    docs_resume = ", ".join(docs[:3])  # Max 3 documents en résumé
    
    return f"Démarche : {nom}. Documents : {docs_resume}."

# --- Dépendance pour l'authentification (REST) ---

async def get_current_user(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Format Authorization invalide")
    token = authorization.split(" ")[1]
    payload = await verify_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token invalide")
    profile = await get_user_profile(user_id)
    return {"id": user_id, "commune": profile.get("commune", "National")}

# --- Endpoints REST protégés ---

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, user: dict = Depends(get_current_user)):
    commune = user["commune"]
    history = sessions.get(request.session_id, [])
    history.append({"role": "user", "content": request.message})
    session_last_seen[request.session_id] = time.time()

    # 1. Recherche RAG sémantique avec filtrage par commune
    results = search_demarches(request.message, commune=commune)
    resume = get_resume_rag(results)

    # 2. Phase 1 : Générateur (non streaming), avec l'historique récent pour le multi-tours
    generator_prompt = build_generator_prompt(request.message, resume, history=history[-(HISTORY_TURNS_FOR_PROMPT * 2 + 1):])

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload_gen = {
        "model": MODEL_GENERATOR,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_GENERATOR},
            {"role": "user", "content": generator_prompt}
        ],
        "stream": False,
        "temperature": 0.3
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            data = await call_openrouter(client, headers, payload_gen)
            reponse_courte_fr = data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Erreur générateur: {str(e)}")

    # 3. Phase 2 : Formateur (traduction en pulaar, sans streaming pour le REST)
    formatter_prompt = build_formatter_prompt(request.message, reponse_courte_fr)
    payload_format = {
        "model": MODEL_FORMATTER,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_FORMATTER},
            {"role": "user", "content": formatter_prompt}
        ],
        "stream": False,
        "temperature": 0.4
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            data = await call_openrouter(client, headers, payload_format)
            reponse_pulaar = data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Erreur formateur: {str(e)}")

    # 4. Enregistrer dans l'historique (on garde la version pulaar comme réponse de l'assistant)
    history.append({"role": "assistant", "content": reponse_pulaar})
    sessions[request.session_id] = history
    
    # On retourne la version française (pour affichage) et pulaar (pour TTS) dans un objet JSON
    return ChatResponse(reply=json.dumps({
        "fr": reponse_courte_fr,
        "pulaar": reponse_pulaar
    }))

@app.get("/sessions")
async def list_sessions():
    return {"active_sessions": list(sessions.keys())}

@app.post("/search")
async def search(request: SearchRequest, user: dict = Depends(get_current_user)):
    results = search_demarches(request.query, commune=user["commune"])
    if not results:
        return {"found": False, "message": "Aucune démarche trouvée pour cette question."}
    demarche = results[0]
    return {
        "found": True,
        "demarche": demarche,
        "formatted_prompt": format_demarche_pour_prompt(demarche)
    }

# --- Endpoints REST pour l'écran "Démarches" du mobile ---

@app.get("/communes")
async def get_communes():
    """Public (pas d'auth) : peuple le sélecteur de commune à l'inscription mobile."""
    return {"communes": list_communes()}

@app.get("/demarches")
async def get_demarches(user: dict = Depends(get_current_user)):
    """
    Liste complète des démarches visibles pour l'utilisateur connecté (sa commune +
    les démarches "National"). La commune vient toujours du profil/token, jamais
    d'un paramètre d'URL non vérifié.
    """
    return {"demarches": list_demarches(commune=user["commune"])}

@app.post("/demarches/{demarche_id}/audio")
async def get_demarche_audio(demarche_id: str, user: dict = Depends(get_current_user)):
    """
    Narration pulaar complète d'une démarche (bouton "Écouter" sur l'écran de détail
    mobile) : traduction/adaptation via le LLM formateur, puis synthèse TTS en une
    seule réponse HTTP (pas de streaming ici, contrairement au WebSocket conversationnel).

    Mise en cache disque par démarche : le texte d'une démarche change rarement, et la
    synthèse TTS (CPU, pas de GPU détecté sur cette machine) prend ~45s pour une narration
    complète — inacceptable à chaque tap sur "Écouter". Limite connue : le cache n'est pas
    invalidé automatiquement si la démarche est modifiée en base (à supprimer manuellement
    dans ce cas, ou à améliorer plus tard avec un hash du contenu / `updated_at`).
    """
    demarche = get_demarche_by_id(demarche_id)
    if not demarche:
        raise HTTPException(status_code=404, detail="Démarche introuvable")

    cache_path = os.path.join(AUDIO_CACHE_DIR, f"{demarche_id}.wav")
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return Response(content=f.read(), media_type="audio/wav")

    informations = format_demarche_pour_prompt(demarche)
    narration_prompt = build_narration_prompt(demarche.get("nom_demarche", ""), informations)

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL_FORMATTER,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_FORMATTER},
            {"role": "user", "content": narration_prompt}
        ],
        "stream": False,
        "temperature": 0.4
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            data = await call_openrouter(client, headers, payload)
            texte_pulaar = data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Erreur narration: {str(e)}")

    try:
        # Le sémaphore borne le nombre d'appels concurrents au Space TTS distant
        # (utile s'il ne scale pas automatiquement) — plus une histoire de CPU
        # local depuis que la synthèse tourne sur le Space (tts_client.py).
        async with TTS_CONCURRENCY:
            audio_bytes = await tts_service.synthesize_text(texte_pulaar)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur TTS: {str(e)}")

    try:
        with open(cache_path, "wb") as f:
            f.write(audio_bytes)
    except OSError as e:
        print(f"⚠️ Écriture du cache audio échouée pour {demarche_id} ({e}) — réponse servie quand même.")

    return Response(content=audio_bytes, media_type="audio/wav")

# --- WebSocket avec token dans l'URL et architecture deux phases + ASR + TTS ---

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    # Récupérer le token depuis les paramètres de requête
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008, reason="Token manquant")
        return
    
    # Vérifier le token
    try:
        payload = await verify_token(token)
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=1008, reason="Token invalide")
            return
        profile = await get_user_profile(user_id)
        commune = profile.get("commune", "National")
    except Exception:
        await websocket.close(code=1008, reason="Token invalide")
        return
    
    # Accepter la connexion
    await websocket.accept()
    print(f"✅ Utilisateur {user_id} (commune: {commune}) connecté")

    history = sessions.get(session_id, [])
    session_last_seen[session_id] = time.time()

    async def send_status(state: str):
        """Signal d'état pour le client mobile (indicateur listening/thinking/speaking)."""
        await websocket.send_text(json.dumps({"type": "status", "state": state}))

    await send_status("listening")

    try:
        while True:
            # ------------------------------------------------------------
            # 1. Recevoir l'audio (bytes) au lieu du texte
            # ------------------------------------------------------------
            audio_bytes = await websocket.receive_bytes()
            session_last_seen[session_id] = time.time()

            if len(audio_bytes) > MAX_AUDIO_BYTES:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "content": f"Audio trop volumineux (max {MAX_AUDIO_BYTES // (1024*1024)} Mo)."
                }))
                await send_status("listening")
                continue

            await send_status("thinking")

            # ------------------------------------------------------------
            # 2. Transcription via l'API ASR (Hugging Face Space)
            # ------------------------------------------------------------
            asr_result = await transcribe_audio(audio_bytes)
            if not asr_result.get("success"):
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "content": f"Erreur de transcription : {asr_result.get('error', 'inconnue')}"
                }))
                await send_status("listening")
                continue

            message = asr_result.get("transcription", "").strip()
            if not message:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "content": "Transcription vide (silence ?)"
                }))
                await send_status("listening")
                continue

            # Ajouter le message transcrit à l'historique
            history.append({"role": "user", "content": message})
            # Après la transcription, avant la recherche RAG
            print(f"📝 MESSAGE TRANSCRIT : {message}")

            # ------------------------------------------------------------
            # 3. RECHERCHE RAG sémantique avec filtrage par commune
            # ------------------------------------------------------------
            results = search_demarches(message, commune=commune)
            resume = get_resume_rag(results)

            # ------------------------------------------------------------
            # 4. PHASE 1 : GÉNÉRATEUR DE RÉPONSES (raisonnement), avec historique multi-tours
            # ------------------------------------------------------------
            generator_prompt = build_generator_prompt(
                message, resume,
                history=history[-(HISTORY_TURNS_FOR_PROMPT * 2 + 1):]
            )

            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            }
            payload_gen = {
                "model": MODEL_GENERATOR,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT_GENERATOR},
                    {"role": "user", "content": generator_prompt}
                ],
                "stream": False,
                "temperature": 0.3
            }

            reponse_courte_fr = ""
            async with httpx.AsyncClient(timeout=30.0) as client:
                try:
                    data = await call_openrouter(client, headers, payload_gen)
                    reponse_courte_fr = data["choices"][0]["message"]["content"].strip()
                except Exception as e:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "content": f"Erreur générateur: {str(e)}"
                    }))
                    await send_status("listening")
                    continue

            # Envoyer la réponse courte en français (pour affichage)
            await websocket.send_text(json.dumps({
                "type": "stream_fr",
                "content": reponse_courte_fr
            }))

            # ------------------------------------------------------------
            # 5. PHASE 2 : TRADUCTEUR ET FORMATEUR (streaming en pulaar)
            # ------------------------------------------------------------
            formatter_prompt = build_formatter_prompt(message, reponse_courte_fr)

            payload_format = {
                "model": MODEL_FORMATTER,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT_FORMATTER},
                    {"role": "user", "content": formatter_prompt}
                ],
                "stream": True,
                "temperature": 0.3
            }

            full_reply_pulaar = ""

            async with httpx.AsyncClient(timeout=60.0) as client:
                try:
                    async with client.stream(
                        "POST",
                        f"{OPENROUTER_BASE_URL}/chat/completions",
                        headers=headers,
                        json=payload_format
                    ) as response:
                        response.raise_for_status()

                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                data_str = line[6:]
                                if data_str == "[DONE]":
                                    break
                                try:
                                    data = json.loads(data_str)
                                    delta = data["choices"][0]["delta"].get("content", "")
                                    if delta:
                                        full_reply_pulaar += delta
                                        # Streamer le pulaar au fur et à mesure
                                        await websocket.send_text(json.dumps({
                                            "type": "stream_pulaar",
                                            "content": delta
                                        }))
                                except json.JSONDecodeError:
                                    pass

                        # ------------------------------------------------------------
                        # 6. SYNTHÈSE VOCALE (TTS) en streaming par phrases
                        # ------------------------------------------------------------
                        if full_reply_pulaar:
                            # Sauvegarder l'historique
                            history.append({"role": "assistant", "content": full_reply_pulaar})
                            sessions[session_id] = history
                            session_last_seen[session_id] = time.time()

                            await send_status("speaking")

                            # Synthétiser et envoyer l'audio phrase par phrase.
                            # Le sémaphore borne le nombre de synthèses simultanées (le modèle
                            # TTS est un singleton partagé entre toutes les sessions).
                            async with TTS_CONCURRENCY:
                                await tts_service.synthesize_stream(full_reply_pulaar, websocket)

                            # Signal de fin
                            await websocket.send_text(json.dumps({"type": "end"}))
                            await send_status("listening")
                        else:
                            await send_status("listening")

                except Exception as e:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "content": f"Erreur formateur: {str(e)}"
                    }))
                    await send_status("listening")
                    continue

    except WebSocketDisconnect:
        print(f"Client {session_id} déconnecté")

# --- Routes de base ---

@app.get("/")
async def root():
    return {"message": "Agent SUNU-LANGUES - Architecture deux phases (Générateur + Formateur)"}

@app.get("/health")
async def health():
    return {"status": "ok", "sessions": len(sessions)}