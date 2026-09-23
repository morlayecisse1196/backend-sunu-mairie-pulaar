from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends, Header, Response, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional
import httpx
import json
import asyncio
import time
import os
import re
import sys
from contextlib import asynccontextmanager, suppress

# Évite un crash des print() avec emoji (⚠️, ✅...) quand la console est en
# cp1252 (terminal par défaut Windows hors Windows Terminal/UTF-8) — repéré en
# testant localement la bascule administratif (Sprint B, Tâche B.3).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, FRONTEND_URL
# RAG sémantique (pgvector) avec filtrage par commune, avec repli automatique
# sur la recherche mot-clé (Supabase REST) si la connexion directe à la base échoue.
from search2 import search_demarches as _search_demarches_semantic, format_demarche_pour_prompt
from search import search_demarches as _search_demarches_keyword
from auth import (verify_token, get_user_profile, get_current_consultant, get_current_admin,
                  get_current_profile, prechauffer_jwks)
from services.regles_statut import RefusStatut, verifier_action_consultant
from routers import moi as routeur_moi
from routers import temps_reel as routeur_temps_reel
from routers import conversations as routeur_conversations
from temps_reel import relances
from routers import notifications as routeur_notifications
from routers import citoyen as routeur_citoyen
from routers import consultant as routeur_consultant
from routers import admin as routeur_admin
from routers import atelier as routeur_atelier
from routers import demarches as routeur_demarches
from services import audit, corrections, evenements, llm, partie_confidentielle, profil, qualite_photo
from services import demarche as demarche_config  # `demarche` est déjà un nom de variable courant ici
from temps_reel.registre import registre as registre_connexions
from temps_reel.sessions import magasin as magasin_sessions
from admin_repo import (
    list_communes_admin, create_commune, update_commune,
    list_consultants, create_consultant, set_consultant_actif, update_consultant_commune,
    list_templates, create_template, update_template,
    get_supervision,
    upload_tampon, get_tampon_signed_url, confirmer_tampon, list_tampon_confirmations,
)
from demarches_repo import list_communes, list_demarches, get_demarche_by_id
from dossiers_repo import (
    create_dossier, update_dossier, resoudre_commune_id, generer_numero_suivi,
    get_dossier, upload_document, list_dossiers_par_commune, list_documents,
    list_document_formulaires, get_document_signed_url,
    get_or_create_document_formulaire, get_document_formulaire, update_champ_formulaire,
    update_champs_formulaire, telecharger_document_bytes,
    get_next_version_documents_generes, upload_document_genere,
    get_document_genere_signed_url, create_document_genere,
    list_documents_generes, update_document_genere_statut,
    list_dossiers_par_citoyen, create_remarque,
    get_or_create_formulaire_acte, get_commune,
    create_cas_particulier, list_cas_particuliers, get_cas_particulier, resoudre_cas_particulier
)
from document_generator import (
    generer_document, ErreurGenerationDocument, DemarcheSansModele,
    resoudre_template, construire_resume_document_genere,
)
from dialogue_engine import (
    normaliser_age, determiner_cas_legal, dossier_complet, construire_recapitulatif,
    TYPES_MIME_DOCUMENT_VALIDES, MAX_DOCUMENT_BYTES,
    TYPES_INCIDENT_CAS_PARTICULIER, fusionner_champs_ocr
)
import ocr_cni_service
import conversations_repo
from prompts import (
    SYSTEM_PROMPT_GENERATOR,
    SCHEMA_REPONSE_INFORMATION,
    SYSTEM_PROMPT_FORMATTER,
    SYSTEM_PROMPT_GENERATOR_ADMINISTRATIF,
    SLOTS_JSON_SCHEMA_ADMINISTRATIF,
    SYSTEM_PROMPT_ASSISTANT_CONSULTANT,
    SCHEMA_ANALYSE_ASSISTANT,
    build_generator_prompt,
    build_formatter_prompt,
    build_narration_prompt,
    build_narration_statut_dossier_prompt,
    build_generator_prompt_administratif,
    build_assistant_consultant_prompt,
    build_narration_document_genere_prompt,
)
from slot_controller import (
    traiter_tour_administratif,  # Sprint J, Tâche J.5 — remplace la collecte multi-slots
    verifier_document_recu_et_avancer,  # Correctif du 2026-08-24 — relance poussée après upload réel
)
from asr_client import transcribe_audio
from tts_service import tts_service  # <-- Nouvel import TTS

@asynccontextmanager
async def cycle_de_vie(_app: FastAPI):
    """
    Démarrage / arrêt de l'application (remplace `@app.on_event`, déprécié).
    À l'arrêt : la tâche de purge est annulée et le client HTTP partagé vers
    l'LLM est fermé — sans quoi Uvicorn signale des connexions non libérées.
    """
    tache_purge = asyncio.create_task(cleanup_inactive_sessions())
    # Clés de signature chargées d'avance : sinon la première requête attend,
    # et sur connexion lente elle échoue puis repart vers Supabase Auth.
    tache_jwks = asyncio.create_task(prechauffer_jwks())
    try:
        yield
    finally:
        for tache in (tache_purge, tache_jwks):
            tache.cancel()
            with suppress(asyncio.CancelledError):
                await tache
        await llm.fermer()


app = FastAPI(
    title="Agent SUNU-LANGUES - Architecture deux phases avec Auth et TTS",
    lifespan=cycle_de_vie,
)

# CORS (Sprint C, Tâche C.1) : le web consultant/admin (React/Next.js, origine
# distincte) doit pouvoir appeler cette API depuis le navigateur. Le mobile
# Flutter et les scripts de test (httpx/websockets) ne passent pas par un
# navigateur donc ne sont pas concernés par CORS — seule l'origine web est à
# lister. allow_credentials=True car les futurs endpoints web envoient le JWT
# via un header Authorization (pas un cookie), mais FastAPI/starlette exige ce
# flag dès qu'on veut un jour envoyer des credentials cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes v3 (profil, temps réel, notifications…) — modules séparés, sans
# dépendance vers main.py (cf. TODO_BACKEND_V3.md, principe 1).
app.include_router(routeur_moi.router)
app.include_router(routeur_temps_reel.router)
app.include_router(routeur_conversations.router)
app.include_router(routeur_notifications.router)
app.include_router(routeur_citoyen.router)
app.include_router(routeur_consultant.router)
app.include_router(routeur_admin.router)
app.include_router(routeur_atelier.router)
app.include_router(routeur_demarches.router)

# Stockage des sessions en mémoire (historique de conversation)
sessions = {}
# Horodatage de dernière activité par session, pour purger les sessions abandonnées
session_last_seen = {}
# L'état du dialogue vocal et les connexions actives vivent désormais dans
# temps_reel/sessions.py (persisté) et temps_reel/registre.py.

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


async def call_openrouter_structured(client: httpx.AsyncClient, headers: dict, payload: dict, retries: int = 2) -> dict:
    """
    Variante de call_openrouter pour les appels à sortie structurée
    (response_format json_schema, mode administratif — Tâches B.2/B.3/B.4).
    Observé empiriquement (pas juste en théorie) : malgré le mode strict, le
    contenu retourné est parfois tronqué / JSON invalide (~1 appel sur 5-10
    sur google/gemini-2.5-flash via OpenRouter). Rejoue l'appel complet (pas
    un reparsing du même contenu, qui échouerait à nouveau à l'identique) —
    résout le problème dans les cas observés jusqu'ici.
    """
    last_exc = None
    for attempt in range(retries + 1):
        data = await call_openrouter(client, headers, payload)
        contenu = data["choices"][0]["message"]["content"]
        try:
            return json.loads(contenu)
        except json.JSONDecodeError as e:
            last_exc = e
            print(f"⚠️ JSON structuré invalide (tentative {attempt + 1}/{retries + 1}) : {contenu[:200]!r}")
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
            print(f"🧹 {len(expired)} session(s) /chat inactive(s) purgée(s) de la mémoire")
        purgees = magasin_sessions.purger_inactives(SESSION_TTL_SECONDS, registre_connexions.sessions_connectees())
        if purgees:
            print(f"🧹 {purgees} session(s) de dialogue retirée(s) du cache (état conservé en base)")


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

async def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentification requise")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Format Authorization invalide")
    token = authorization.split(" ")[1]
    payload = await verify_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token invalide")
    profile = await get_user_profile(user_id)
    return {"id": user_id, "commune": profile.get("commune", "National")}


@app.get("/me")
async def me(identite: dict = Depends(get_current_profile)):
    """
    Compte connecté — le web consultant/admin partage un seul écran de login
    (Tâche F.1) ; le frontend appelle ceci juste après signInWithPassword()
    pour savoir vers quel espace rediriger (bug réel trouvé en usage :
    redirection en dur vers /consultant/dossiers, 403 immédiat pour un admin).

    Réponse enrichie (identité, préférences, mot de passe temporaire, dernière
    connexion) : c'est aussi l'appel qui journalise la connexion, quand
    `last_sign_in_at` a changé depuis la dernière valeur vue.
    """
    if identite["role"] == "citoyen":
        # L'appli mobile n'a besoin que du rôle et de la commune : pas d'appel
        # Auth admin supplémentaire sur son chemin critique.
        return identite
    return await profil.lire(identite["id"], identite["role"], identite["commune"], identite.get("email"))

# --- Endpoints REST protégés ---

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, user: dict = Depends(get_current_user)):
    commune = user["commune"]
    # Historique cloisonné par utilisateur (correctif sécurité 2026-09-14) :
    # auparavant, n'importe quel utilisateur connecté pouvait lire et
    # prolonger l'historique d'un autre en réutilisant son session_id.
    cle_session = f"chat:{user['id']}:{request.session_id}"
    history = sessions.get(cle_session, [])
    history.append({"role": "user", "content": request.message})
    session_last_seen[cle_session] = time.time()

    # 1. Recherche RAG sémantique avec filtrage par commune
    results = search_demarches(request.message, commune=commune)
    resume = get_resume_rag(results)

    # 2. Phase 1 : Générateur (non streaming), avec l'historique récent pour le multi-tours
    generator_prompt = build_generator_prompt(request.message, resume, history=history[-(HISTORY_TURNS_FOR_PROMPT * 2 + 1):])

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    # Même schéma structuré que le WS (cf. §mode information) — /chat n'implémente
    # pas la bascule administratif (endpoint debug/fallback texte, cf. FLUTTER_APP_PROMPTS.md
    # §0), mais doit utiliser le MÊME system prompt/schéma que le WS pour rester
    # cohérent : SYSTEM_PROMPT_GENERATOR décrit maintenant explicitement les champs
    # JSON attendus, un appel non structuré casserait le format de réponse. Les
    # champs propose_demarrer_demarche/confirme_demarrage_demarche sont ignorés ici.
    payload_gen = {
        "model": MODEL_GENERATOR,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_GENERATOR},
            {"role": "user", "content": generator_prompt}
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "reponse_information", "strict": True, "schema": SCHEMA_REPONSE_INFORMATION}
        },
        "stream": False,
        "temperature": 0.3
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            parsed_info = await call_openrouter_structured(client, headers, payload_gen)
            reponse_courte_fr = parsed_info["reponse"]
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Erreur générateur: {str(e)}")

    # 3. Phase 2 : Formateur (traduction en pulaar, sans streaming pour le REST)
    # "Salam" uniquement au tout premier tour (même correctif que le WS, cf.
    # temps_reel/connexion.py) — `history` contient déjà le message
    # utilisateur de ce tour mais aucune réponse assistant tant qu'on n'a pas
    # encore atteint ce point.
    premier_tour = not any(h.get("role") == "assistant" for h in history)
    formatter_prompt = build_formatter_prompt(request.message, reponse_courte_fr, premier_tour=premier_tour)
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
    sessions[cle_session] = history
    
    # On retourne la version française (pour affichage) et pulaar (pour TTS) dans un objet JSON
    return ChatResponse(reply=json.dumps({
        "fr": reponse_courte_fr,
        "pulaar": reponse_pulaar
    }))

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

# --- Upload de document (Sprint B, Tâche B.5) ---

EXTENSIONS_PAR_MIME_DOCUMENT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


@app.post("/dossiers/{dossier_id}/documents")
async def upload_document_dossier(
    dossier_id: str,
    type: str = Form(...),
    fichier: UploadFile = File(...),
    forcer: bool = Form(False),
    user: dict = Depends(get_current_user),
):
    """
    Upload d'une pièce (photo) pour un dossier en cours de remplissage — endpoint
    REST multipart, distinct du canal WebSocket audio (cf. §5.3 du roadmap :
    protocoles séparés pour la voix et les fichiers). Déclenché côté mobile après
    réception d'un message WS {"type":"attente_upload", "document_type":...}.
    """
    types_acceptes = demarche_config.types_documents_acceptes()
    if type not in types_acceptes:
        raise HTTPException(
            status_code=400,
            detail=f"Type de document invalide. Attendu l'un de : {list(types_acceptes)}"
        )

    dossier = get_dossier(dossier_id)
    if not dossier:
        raise HTTPException(status_code=404, detail="Dossier introuvable")
    # Un citoyen ne peut uploader que sur SON PROPRE dossier — jamais confié au
    # frontend, vérifié ici à chaque appel (même principe que le filtrage
    # commune déjà en place pour le RAG démarches, cf. §5.6 du roadmap).
    if dossier["citoyen_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Ce dossier ne vous appartient pas")

    if fichier.content_type not in TYPES_MIME_DOCUMENT_VALIDES:
        raise HTTPException(
            status_code=415,
            detail=f"Format non supporté ({fichier.content_type}). Attendu : {TYPES_MIME_DOCUMENT_VALIDES}"
        )

    contenu = await fichier.read()
    if not contenu:
        raise HTTPException(status_code=400, detail="Fichier vide")
    if len(contenu) > MAX_DOCUMENT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Fichier trop volumineux (max {MAX_DOCUMENT_BYTES // (1024 * 1024)} Mo)"
        )

    # Contrôle qualité (flou, sombre, trop petite…) : une photo inexploitable
    # est refusée tout de suite, avec une consigne DITE au citoyen dans le
    # dialogue — plutôt que découverte des jours plus tard par le consultant.
    # `forcer=true` (nouvel essai assumé par le citoyen) contourne le contrôle.
    verdict = await asyncio.to_thread(qualite_photo.evaluer, contenu)
    if not verdict.acceptable and not forcer:
        relances.planifier(relances.pousser_message(dossier_id, verdict.message_fr))
        raise HTTPException(
            status_code=422,
            detail={"code": verdict.code, "message": verdict.message_fr, "mesures": verdict.mesures},
        )

    # Étape 5.4 : la partie basse du certificat de décès porte la cause
    # médicale. Elle ne doit jamais entrer dans le stockage de la mairie —
    # contrôlé AVANT l'enregistrement, et sans échappatoire : `forcer` sert à
    # assumer une photo floue, pas à verser une donnée de santé au dossier.
    if type == "certificat_deces":
        code, message = await asyncio.to_thread(partie_confidentielle.examiner, contenu)
        if code:
            relances.planifier(relances.pousser_message(dossier_id, message))
            raise HTTPException(status_code=422, detail={"code": code, "message": message})

    extension = EXTENSIONS_PAR_MIME_DOCUMENT.get(fichier.content_type, "bin")
    document = upload_document(dossier_id, type, contenu, fichier.content_type, extension)
    if not document:
        raise HTTPException(status_code=502, detail="Échec de l'enregistrement du document (stockage ou base)")

    relances.planifier(evenements.ajouter_evenement(
        dossier_id, "document_recu", f"Pièce reçue : {type}",
        acteur_type="citoyen", acteur_id=user["id"], details={"type_document": type, "controle_force": forcer},
    ))

    # Correctif du 2026-08-24 : sans ceci, le dialogue restait silencieux tant
    # que le citoyen ne reparlait pas de lui-même après l'upload (bug réel
    # remonté en test terrain — cf. temps_reel/relances.py).
    #
    # `asyncio.create_task` (PAS `await` direct — bug réel trouvé juste après :
    # un `await` ici retardait la réponse 200 de CET endpoint jusqu'à la fin
    # COMPLÈTE de la relance (traduction + synthèse TTS, plusieurs secondes) —
    # observé dans les logs : la ligne d'accès "200 OK" de ce POST n'apparaissait
    # qu'APRÈS le message "Relance poussée..." du tour SUIVANT. Conséquence
    # probable côté mobile : le upload du RECTO de la CNI restait "en cours"
    # pendant que l'`attente_upload` du VERSO arrivait déjà sur le WebSocket,
    # et la confirmation tardive du recto a pu écraser l'état d'attente du
    # verso côté app — expliquant le bouton photo manquant pour le verso.
    # `create_task` détache la relance : la réponse HTTP part immédiatement,
    # la relance WS se déroule en parallèle, sans lien de timing entre les deux.
    relances.planifier(relances.relancer_apres_document(dossier_id, type))

    return {"document_id": document["id"], "type": document["type"], "statut": document["statut"]}


# --- Endpoints citoyen : suivi de dossier + validation du document généré ---
# (Sprint mobile Tâche 7.1, cf. FLUTTER_APP_PROMPTS.md — Flux §2.7 / UC3 étape 7
# du DSF : jusqu'ici aucun endpoint ne permettait au citoyen de voir/valider ce
# que le consultant a généré pour lui. Même dépendance get_current_user que
# /chat, /demarches, POST /dossiers/{id}/documents — jamais consultant/admin.)

def _verifier_dossier_citoyen(dossier_id: str, user: dict) -> dict:
    """Charge le dossier et vérifie qu'il appartient au citoyen connecté —
    factorise le contrôle répété par les 3 endpoints ci-dessous, même principe
    que _verifier_dossier_commune_consultant côté consultant."""
    dossier = get_dossier(dossier_id)
    if not dossier:
        raise HTTPException(status_code=404, detail="Dossier introuvable")
    if dossier["citoyen_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Ce dossier ne vous appartient pas")
    return dossier


@app.get("/mes-dossiers")
async def mes_dossiers(user: dict = Depends(get_current_user)):
    """Dossiers du citoyen connecté (écran « Mes démarches », Tâche 7.2 mobile)."""
    return {"dossiers": list_dossiers_par_citoyen(user["id"])}


@app.get("/mes-dossiers/{dossier_id}")
async def mon_dossier_detail(dossier_id: str, user: dict = Depends(get_current_user)):
    """
    Détail d'un dossier pour son propriétaire, avec le dernier document généré
    (URL signée, bucket privé — même storage que l'écran consultant F.5) dès
    que le dossier est au statut 'en_attente_validation_citoyen' ou postérieur
    (le document n'a pas de sens à montrer avant, il n'existe pas encore).
    """
    dossier = _verifier_dossier_citoyen(dossier_id, user)

    document_genere = None
    if dossier["statut"] in ("en_attente_validation_citoyen", "finalise", "corrections_demandees"):
        documents = list_documents_generes(dossier_id)  # le plus récent d'abord
        if documents:
            document_genere = documents[0]
            document_genere["url_signee"] = get_document_genere_signed_url(document_genere["contenu_url"])

    return {"dossier": dossier, "document_genere": document_genere}


@app.post("/mes-dossiers/{dossier_id}/valider")
async def valider_mon_dossier(dossier_id: str, user: dict = Depends(get_current_user)):
    """
    Le citoyen confirme le document généré tel quel (Flux §2.7, dernière étape
    UC3) — dossier -> 'finalise', documents_generes -> 'valide' (valeurs
    distinctes, cf. contraintes `check` de 001_dossiers.sql).
    """
    dossier = _verifier_dossier_citoyen(dossier_id, user)
    if dossier["statut"] != "en_attente_validation_citoyen":
        raise HTTPException(
            status_code=400,
            detail=f"Ce dossier n'est pas en attente de validation (statut actuel : '{dossier['statut']}').",
        )

    documents = list_documents_generes(dossier_id)
    if not documents:
        raise HTTPException(status_code=502, detail="Aucun document généré trouvé pour ce dossier — incohérence à signaler.")

    document_maj = update_document_genere_statut(documents[0]["id"], "valide")
    if not document_maj:
        raise HTTPException(status_code=502, detail="Échec de la mise à jour du document généré")

    apres = await evenements.transition_statut(
        dossier_id, "finalise", acteur_type="citoyen", acteur_id=user["id"], dossier_actuel=dossier
    )
    if apres is None:
        raise HTTPException(status_code=502, detail="Échec de la mise à jour du statut du dossier")

    return {"dossier": apres, "document_genere": document_maj}


class DemanderCorrectionsIn(BaseModel):
    texte: str
    # Champ précis signalé par le citoyen (lecture du document ligne par ligne,
    # cf. GET /mes-dossiers/{id}/document/lecture) — évite au consultant de
    # deviner ce qui est à corriger.
    champ_concerne: Optional[str] = None


@app.post("/mes-dossiers/{dossier_id}/demander-corrections")
async def demander_corrections(dossier_id: str, body: DemanderCorrectionsIn, user: dict = Depends(get_current_user)):
    """
    Le citoyen signale un problème sur le document généré — journalisé dans
    `remarques` (source='citoyen', jamais appliqué automatiquement à aucun
    champ), dossier -> 'corrections_demandees' pour que le consultant le
    retrouve dans son écran F.3-F.5 (aucun changement web nécessaire de ce
    côté, la boucle de correction consultant existe déjà).

    Réutilise `nb_iterations_correction`/`SEUIL_ITERATIONS_CORRECTION_BLOQUE`
    (Tâche I.2, même compteur/seuil que la boucle de relecture RG7 pré-
    génération, Tâche B.4/G.3) : au-delà de 3 demandes de correction
    post-génération sur le MÊME dossier, il n'a pas de sens de reboucler
    indéfiniment génération -> rejet -> génération -> ... -> 'bloque' plutôt
    que 'corrections_demandees', pour qu'un agent reprenne la main directement
    (visible dans la supervision admin, Tâche G.3).
    """
    dossier = _verifier_dossier_citoyen(dossier_id, user)
    try:
        # Même implémentation que la version vocale (routers/citoyen.py) :
        # remarque, compteur d'itérations, blocage au 3e essai et transition
        # de statut (historique + notifications) vivent dans services/corrections.py.
        issue = await corrections.enregistrer_demande(
            dossier, body.texte, citoyen_id=user["id"], champ_concerne=body.champ_concerne
        )
    except corrections.CorrectionImpossible as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message})

    return {"dossier": issue["dossier"], "remarque": issue["remarque"], "bloque": issue["bloque"]}


@app.get("/mes-dossiers/{dossier_id}/documents")
async def mes_documents_dossier(dossier_id: str, user: dict = Depends(get_current_user)):
    """
    Pièces uploadées par le citoyen pendant le dialogue (certificat de
    naissance, CNI recto/verso, etc.), avec URL signée (bucket privé, même
    mécanisme que côté consultant, cf. `consultant_detail_dossier`) — gap réel
    trouvé en septembre 2026 : le citoyen n'avait jusqu'ici AUCUN moyen de
    revoir ses propres photos après upload (`GET /mes-dossiers/{id}` ne
    renvoie que le document généré final, pas les pièces sources).
    """
    _verifier_dossier_citoyen(dossier_id, user)
    documents = list_documents(dossier_id)
    for document in documents:
        if document.get("fichier_url"):
            document["url_signee"] = get_document_signed_url(document["fichier_url"])
    return {"documents": documents}


# --- Historique des conversations (mobile, migration 010) ---
#
# "Revoir mes anciennes conversations" façon Claude web — gap réel trouvé en
# septembre 2026 : l'état du dialogue ne vivait qu'en mémoire process, jamais
# consultable après coup ni au redémarrage du serveur.
# `temps_reel/connexion.py` persiste désormais chaque tour (texte
# uniquement, cf. conversations_repo) ; les endpoints ci-dessous exposent cet
# historique, et permettent de resynthétiser l'audio d'un message passé à la
# demande (pas de stockage de fichiers audio, même principe que
# get_demarche_audio/get_dossier_audio déjà en place).

def _verifier_conversation_citoyen(conversation_id: str, user: dict) -> dict:
    conversation = conversations_repo.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation introuvable")
    if conversation["citoyen_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Cette conversation ne vous appartient pas")
    return conversation


@app.get("/mes-conversations")
async def mes_conversations(user: dict = Depends(get_current_user)):
    """Liste triée par activité la plus récente — même logique que la barre latérale de Claude web."""
    return {"conversations": conversations_repo.list_conversations_citoyen(user["id"])}


@app.get("/mes-conversations/{conversation_id}")
async def mon_conversation_detail(conversation_id: str, user: dict = Depends(get_current_user)):
    conversation = _verifier_conversation_citoyen(conversation_id, user)
    return {"conversation": conversation, "messages": conversations_repo.list_messages(conversation_id)}


@app.get("/mes-conversations/{conversation_id}/messages/{message_id}/audio")
async def audio_message_conversation(conversation_id: str, message_id: str, user: dict = Depends(get_current_user)):
    """
    Rejoue l'audio d'un message passé de l'agent (Pulaar) — resynthétisé à la
    demande (jamais stocké, cf. commentaire de section) : léger délai, mais
    aucun fichier audio à conserver indéfiniment pour chaque tour de chaque
    conversation.
    """
    _verifier_conversation_citoyen(conversation_id, user)
    message = conversations_repo.get_message(message_id)
    if not message or message["conversation_id"] != conversation_id:
        raise HTTPException(status_code=404, detail="Message introuvable dans cette conversation")
    if message["role"] != "assistant" or not message.get("contenu_pulaar"):
        raise HTTPException(status_code=400, detail="Ce message n'a pas d'audio associé (pas une réponse de l'agent)")

    try:
        audio_bytes = await tts_service.synthesize_text(message["contenu_pulaar"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Échec de la synthèse audio : {str(e)}")
    return Response(content=audio_bytes, media_type="audio/wav")


# --- Narration audio du statut d'un dossier (Sprint mobile, Tâche 7.4) ---

# Libellé FR par type_demarche — même contenu que _typeDemarcheLabels côté
# mobile (dossier_labels.dart), dupliqué ici volontairement : le backend ne
# doit pas dépendre du code Flutter, et cette narration a besoin du nom en
# toutes lettres dans la phrase (pas juste un badge visuel).
LABELS_TYPE_DEMARCHE = {"extrait_naissance": "extrait de naissance"}

# Phrase FR courte par statut (`{nom}` remplacé par LABELS_TYPE_DEMARCHE) —
# reprend le sens des libellés de badge de dossier_labels.dart (côté mobile)
# mais en phrase complète, adaptée à une narration orale plutôt qu'un badge
# visuel. Ne dépend QUE du statut, jamais de l'identité du dossier — c'est ce
# qui permet la mise en cache par (type_demarche, statut) ci-dessous.
PHRASES_STATUT_DOSSIER = {
    "en_cours": "Votre dossier de {nom} est en cours de constitution, il n'a pas encore été envoyé à la mairie.",
    "recu": "Votre dossier de {nom} a bien été reçu par la mairie et attend d'être traité.",
    "en_traitement": "Votre dossier de {nom} est en cours de traitement à la mairie.",
    "genere": "Le document de votre dossier de {nom} est en cours de préparation.",
    "en_attente_validation_citoyen": "Votre dossier de {nom} est prêt ! Le document est disponible, vous pouvez le valider.",
    "finalise": "Votre dossier de {nom} est terminé, le document final est disponible.",
    "corrections_demandees": "Des corrections sont nécessaires sur votre dossier de {nom}. Un agent de la mairie vous a laissé une remarque.",
    "bloque": "Votre dossier de {nom} rencontre une difficulté. Un agent de la mairie va vous contacter directement.",
}


def construire_phrase_statut_dossier(type_demarche: str, statut: str) -> str:
    nom = LABELS_TYPE_DEMARCHE.get(type_demarche, type_demarche)
    gabarit = PHRASES_STATUT_DOSSIER.get(statut)
    if gabarit is None:
        # Statut inconnu (ne devrait pas arriver, CHECK en base) : repli honnête
        # plutôt qu'une exception qui casserait la narration pour un cas limite.
        return f"Votre dossier de {nom} a pour statut : {statut}."
    return gabarit.format(nom=nom)


@app.post("/mes-dossiers/{dossier_id}/audio")
async def get_dossier_audio(dossier_id: str, user: dict = Depends(get_current_user)):
    """
    Narration pulaar COURTE du statut actuel d'un dossier citoyen (Sprint
    mobile, Tâche 7.4 — accessibilité, FLUTTER_APP_PROMPTS.md). Bouton
    « 🔊 Écouter » sur chaque `_DossierCard` de l'écran "Mes dossiers".

    Contrairement à POST /demarches/{id}/audio (contenu stable d'une démarche,
    mis en cache par démarche) : le statut d'un dossier change dans le temps,
    mais la phrase annoncée ne dépend QUE de sa VALEUR (type_demarche, statut),
    jamais de l'identité du dossier — deux citoyens ayant chacun un dossier
    'en_traitement' entendent exactement la même annonce. Le cache est donc
    indexé par ce COUPLE, pas par dossier_id : évite de resynthétiser (TTS
    CPU, ~45s sur cette machine) la même phrase pour chaque dossier partageant
    un statut, contrairement à un cache par dossier qui grossirait sans fin
    pour un gain nul (le contenu est strictement identique).
    """
    dossier = _verifier_dossier_citoyen(dossier_id, user)
    type_demarche = dossier["type_demarche"]
    statut = dossier["statut"]

    cache_path = os.path.join(AUDIO_CACHE_DIR, f"dossier_{type_demarche}_{statut}.wav")
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return Response(content=f.read(), media_type="audio/wav")

    phrase_fr = construire_phrase_statut_dossier(type_demarche, statut)
    narration_prompt = build_narration_statut_dossier_prompt(phrase_fr)

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
        async with TTS_CONCURRENCY:
            audio_bytes = await tts_service.synthesize_text(texte_pulaar)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur TTS: {str(e)}")

    try:
        with open(cache_path, "wb") as f:
            f.write(audio_bytes)
    except OSError as e:
        print(f"⚠️ Écriture du cache audio échouée pour dossier_{type_demarche}_{statut} ({e}) — réponse servie quand même.")

    return Response(content=audio_bytes, media_type="audio/wav")


@app.post("/mes-dossiers/{dossier_id}/document/audio")
async def get_document_genere_audio(dossier_id: str, user: dict = Depends(get_current_user)):
    """
    Narration pulaar du CONTENU du document généré (Tâche 7.5 mobile) — pas
    son statut (Tâche 7.4 ci-dessus) : le PDF est un formulaire (champs,
    cases, tableaux), imbuvable lu mot pour mot. Un citoyen qui ne lit pas
    doit pouvoir ENTENDRE ce que dit le document avant de décider ✓/✗
    (Tâche 7.3), pas seulement voir un PDF.

    Cache par `document_genere_id` (pas par couple type_demarche/statut comme
    Tâche 7.4) : le contenu est unique à chaque dossier, aucun partage de
    cache possible entre deux citoyens différents.
    """
    dossier = _verifier_dossier_citoyen(dossier_id, user)
    documents = list_documents_generes(dossier_id)
    if not documents:
        raise HTTPException(status_code=404, detail="Aucun document généré pour ce dossier — rien à résumer.")
    document_genere = documents[0]  # le plus récent (list_documents_generes trie par version décroissante)

    cache_path = os.path.join(AUDIO_CACHE_DIR, f"document_genere_{document_genere['id']}.wav")
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return Response(content=f.read(), media_type="audio/wav")

    commune = get_commune(dossier.get("commune_id"))
    formulaires = list_document_formulaires(dossier_id)
    formulaire_acte = get_or_create_formulaire_acte(dossier_id)
    if formulaire_acte and not any(f["id"] == formulaire_acte["id"] for f in formulaires):
        formulaires.append(formulaire_acte)
    champs_formulaire = {}
    for formulaire in formulaires:
        for champ in (formulaire.get("champs") or []):
            if champ.get("valeur") is not None:
                champs_formulaire[champ["nom"]] = champ["valeur"]

    jugement_requis = dossier.get("cas_legal") == "jugement_requis"
    valeurs, _erreurs = resoudre_template(dossier, commune, champs_formulaire, jugement_requis)
    phrase_fr = construire_resume_document_genere(valeurs)
    narration_prompt = build_narration_document_genere_prompt(phrase_fr)

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
        async with TTS_CONCURRENCY:
            audio_bytes = await tts_service.synthesize_text(texte_pulaar)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur TTS: {str(e)}")

    try:
        with open(cache_path, "wb") as f:
            f.write(audio_bytes)
    except OSError as e:
        print(f"⚠️ Écriture du cache audio échouée pour document_genere_{document_genere['id']} ({e}) — réponse servie quand même.")

    return Response(content=audio_bytes, media_type="audio/wav")


# --- Endpoints consultant (Sprint C, Tâche C.2) ---

@app.get("/consultant/dossiers")
async def consultant_liste_dossiers(consultant: dict = Depends(get_current_consultant)):
    """
    Liste des dossiers de la commune du consultant, triée par ancienneté (les
    plus anciens d'abord) avec le badge cas_legal (cf. Flux §2.1). Filtrage
    EXCLUSIVEMENT sur la commune du profil consultant authentifié, jamais un
    paramètre d'URL — même principe que /demarches (§5.6 du roadmap).
    """
    commune_id = resoudre_commune_id(consultant["commune"])
    if not commune_id:
        # Commune du consultant absente de la table `communes` (cf. Tâche A.2,
        # ex. seedée sans être encore complète) : aucun dossier ne peut lui être
        # rattaché tant que ce n'est pas corrigé côté admin (Sprint G) — liste
        # vide, pas une erreur serveur.
        return {"dossiers": []}
    return {"dossiers": list_dossiers_par_commune(commune_id)}


@app.get("/consultant/dossiers/{dossier_id}")
async def consultant_detail_dossier(dossier_id: str, consultant: dict = Depends(get_current_consultant)):
    """
    Détail complet d'un dossier : slots, documents (avec URL signée — bucket
    privé, cf. Tâche B.5), document_formulaires (vide tant que le Sprint D
    n'existe pas, exposé tel quel).

    Première ouverture par un consultant ('recu' ou 'corrections_demandees')
    -> bascule automatiquement en 'en_traitement' (Tâche I.1, cycle de vie
    §3.1 : recu -> en_traitement -> genere -> ... — jusqu'ici rien ne
    déclenchait jamais cette transition, le dossier sautait directement à
    'genere'). Pas de "Prendre en charge" explicite : ouvrir le dossier EST
    le signal qu'un consultant s'en occupe.
    """
    dossier = _verifier_dossier_commune_consultant(dossier_id, consultant)
    if dossier["statut"] in ("recu", "corrections_demandees"):
        apres = await evenements.transition_statut(
            dossier_id, "en_traitement", acteur_type="consultant", acteur_id=consultant["id"],
            libelle="Dossier pris en charge par un agent", dossier_actuel=dossier,
        )
        if apres:
            dossier = apres

    documents = list_documents(dossier_id)
    for document in documents:
        if document.get("fichier_url"):
            document["url_signee"] = get_document_signed_url(document["fichier_url"])

    return {
        "dossier": dossier,
        "documents": documents,
        "document_formulaires": list_document_formulaires(dossier_id),
    }


def _verifier_dossier_commune_consultant(dossier_id: str, consultant: dict) -> dict:
    """
    Charge le dossier et vérifie qu'il appartient à la commune du consultant —
    factorise le contrôle répété par les endpoints formulaire ci-dessous
    (même logique que dans consultant_detail_dossier).
    """
    dossier = get_dossier(dossier_id)
    if not dossier:
        raise HTTPException(status_code=404, detail="Dossier introuvable")
    commune_id_consultant = resoudre_commune_id(consultant["commune"])
    if not commune_id_consultant or dossier["commune_id"] != commune_id_consultant:
        raise HTTPException(status_code=403, detail="Ce dossier n'appartient pas à votre commune")
    return dossier


def _exiger_action_autorisee(dossier: dict, action: str) -> None:
    """409 explicite si l'action consultant est interdite au statut courant (services/regles_statut.py)."""
    try:
        verifier_action_consultant(dossier.get("statut", ""), action)
    except RefusStatut as refus:
        raise HTTPException(status_code=409, detail=refus.detail())


@app.get("/consultant/dossiers/{dossier_id}/formulaires")
async def consultant_liste_formulaires(dossier_id: str, consultant: dict = Depends(get_current_consultant)):
    """
    Formulaires structurés du dossier (un par document uploadé), créés à la
    volée s'ils n'existent pas encore — pré-remplis source="dialogue" depuis
    dossiers.slots là où la correspondance est fiable (cf. Flux §2.2 V1,
    dialogue_engine.construire_champs_formulaire).
    """
    dossier = _verifier_dossier_commune_consultant(dossier_id, consultant)
    documents = list_documents(dossier_id)
    formulaires = []
    for document in documents:
        formulaire = get_or_create_document_formulaire(dossier_id, document, dossier["slots"])
        if formulaire:
            formulaires.append(formulaire)
    return {"formulaires": formulaires}


class PatchChampFormulaire(BaseModel):
    nom: str
    valeur: Optional[str] = None  # si fourni : met à jour la valeur ET passe source="manuel"
    verifie: Optional[bool] = None  # si fourni : bouton "Champ vérifié", indépendant de valeur


@app.patch("/consultant/dossiers/{dossier_id}/formulaires/{form_id}")
async def consultant_maj_champ_formulaire(
    dossier_id: str,
    form_id: str,
    body: PatchChampFormulaire,
    consultant: dict = Depends(get_current_consultant),
):
    """Met à jour un champ d'un formulaire (correction et/ou marquage "vérifié")."""
    dossier = _verifier_dossier_commune_consultant(dossier_id, consultant)
    _exiger_action_autorisee(dossier, "modifier_formulaire")

    if body.valeur is None and body.verifie is None:
        raise HTTPException(status_code=400, detail="Fournir au moins 'valeur' ou 'verifie'")

    formulaire = get_document_formulaire(form_id)
    if not formulaire or formulaire["dossier_id"] != dossier_id:
        raise HTTPException(status_code=404, detail="Formulaire introuvable pour ce dossier")

    resultat = update_champ_formulaire(formulaire, body.nom, valeur=body.valeur, verifie=body.verifie)
    if not resultat:
        raise HTTPException(status_code=404, detail=f"Champ '{body.nom}' introuvable dans ce formulaire")

    return resultat


@app.post("/consultant/dossiers/{dossier_id}/ocr-cni")
async def consultant_ocr_cni(dossier_id: str, consultant: dict = Depends(get_current_consultant)):
    """
    Lance l'extraction OCR (YOLOv8s + EasyOCR, Sprint K) sur les deux photos
    de la CNI du déclarant (cni_declarant_recto/verso, Sprint J) déjà
    uploadées, et met à jour leurs document_formulaires respectifs.

    Action EXPLICITE du consultant (bouton "Lancer l'OCR") — même logique que
    "Analyser le dossier" (E.1) ou "Générer le document" (D.3) : jamais
    automatique dès l'upload (l'inférence prend plusieurs secondes).
    """
    dossier = _verifier_dossier_commune_consultant(dossier_id, consultant)
    _exiger_action_autorisee(dossier, "ocr")
    documents = list_documents(dossier_id)

    doc_recto = next((d for d in documents if d["type"] == "cni_declarant_recto"), None)
    doc_verso = next((d for d in documents if d["type"] == "cni_declarant_verso"), None)
    manquants = [
        nom for nom, d in (("cni_declarant_recto", doc_recto), ("cni_declarant_verso", doc_verso)) if d is None
    ]
    if manquants:
        raise HTTPException(
            status_code=400,
            detail=f"Document(s) manquant(s) pour lancer l'OCR : {', '.join(manquants)}",
        )

    recto_bytes = telecharger_document_bytes(doc_recto)
    verso_bytes = telecharger_document_bytes(doc_verso)
    if not recto_bytes or not verso_bytes:
        raise HTTPException(status_code=502, detail="Échec du téléchargement d'une des deux photos de la CNI")

    try:
        resultat_ocr = await ocr_cni_service.extraire_cni(recto_bytes, verso_bytes)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur OCR : {str(e)}")

    formulaires_maj = []
    for document in (doc_recto, doc_verso):
        formulaire = get_or_create_document_formulaire(dossier_id, document, dossier["slots"])
        if not formulaire:
            continue
        nouveaux_champs = fusionner_champs_ocr(formulaire["champs"], resultat_ocr)
        resultat = update_champs_formulaire(formulaire, nouveaux_champs)
        if resultat:
            formulaires_maj.append(resultat)

    return {"formulaires": formulaires_maj}


@app.post("/consultant/dossiers/{dossier_id}/generer")
async def consultant_generer_document(dossier_id: str, consultant: dict = Depends(get_current_consultant)):
    """
    Déclenche la génération du document (Tâche D.3). Bloque explicitement
    (RG6 du DSF) si des champs obligatoires manquent ou si la validation XSD
    échoue — jamais de PDF partiel silencieux, cf. document_generator.py (D.2).
    `version` incrémentée à chaque appel : aucun écrasement, historique conservé.
    """
    dossier = _verifier_dossier_commune_consultant(dossier_id, consultant)
    _exiger_action_autorisee(dossier, "generer")

    try:
        pdf_bytes = generer_document(dossier_id)
    except DemarcheSansModele as e:
        # 422 et non 404 : le dossier existe, c'est le modèle qui manque.
        raise HTTPException(status_code=422, detail={"message": str(e), "champs_en_erreur": []})
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ErreurGenerationDocument as e:
        raise HTTPException(status_code=422, detail={"message": str(e), "champs_en_erreur": e.erreurs})

    version = get_next_version_documents_generes(dossier_id)
    chemin = upload_document_genere(dossier_id, version, pdf_bytes)
    if not chemin:
        raise HTTPException(status_code=502, detail="Échec du stockage du PDF généré")

    document_genere = create_document_genere(dossier_id, "extrait_naissance_v1", version, chemin)
    if not document_genere:
        raise HTTPException(status_code=502, detail="Échec de l'enregistrement du document généré")

    # Cycle de vie du dossier (§3.1) : recu -> en_traitement -> genere -> ...
    # L'envoi au citoyen pour validation (Flux §2.7) reste une action explicite
    # du consultant (POST .../valider) — la génération ne l'envoie pas.
    await evenements.transition_statut(
        dossier_id, "genere", acteur_type="consultant", acteur_id=consultant["id"],
        libelle=f"Document généré (version {version})", details={"version": version}, dossier_actuel=dossier,
    )
    await audit.journaliser(
        "document_genere", acteur=consultant, cible_type="dossier", cible_id=dossier_id,
        cible_libelle=dossier.get("numero_suivi"), details={"version": version},
    )

    return {
        "document_genere_id": document_genere["id"],
        "version": version,
        "statut": document_genere["statut"],
        "url_signee": get_document_genere_signed_url(chemin),
    }


@app.get("/consultant/dossiers/{dossier_id}/documents-generes")
async def consultant_liste_documents_generes(dossier_id: str, consultant: dict = Depends(get_current_consultant)):
    """
    Historique des PDF déjà générés pour ce dossier (le plus récent d'abord),
    avec URL signée — Tâche F.5 : permet à l'écran consultant d'afficher la
    dernière version au chargement sans devoir relancer une génération.
    """
    _verifier_dossier_commune_consultant(dossier_id, consultant)
    documents = list_documents_generes(dossier_id)
    for document in documents:
        if document.get("contenu_url"):
            document["url_signee"] = get_document_genere_signed_url(document["contenu_url"])
    return {"documents_generes": documents}


@app.post("/consultant/dossiers/{dossier_id}/valider")
async def consultant_valider_dossier(dossier_id: str, consultant: dict = Depends(get_current_consultant)):
    """
    Bouton « Valider » final (Tâche F.5) : envoie le document généré au
    citoyen pour validation — PAS un téléchargement/une finalisation directe
    (Flux §2.7, UC3 étape 7 du DSF). Fait donc passer le dossier à
    `en_attente_validation_citoyen`, jamais `finalise` (qui suppose la
    validation citoyenne elle-même, hors scope de ce backend consultant/admin
    — cf. le cycle de vie §3.1 du roadmap).

    Bloque explicitement si aucun document n'a été généré pour ce dossier
    (rien à envoyer), ou si le dossier n'est pas dans l'état `genere` (ex.
    déjà envoyé, ou en cours de retouche) — pas de double-envoi silencieux.
    """
    dossier = _verifier_dossier_commune_consultant(dossier_id, consultant)
    _exiger_action_autorisee(dossier, "valider")

    documents = list_documents_generes(dossier_id)
    if not documents:
        raise HTTPException(status_code=400, detail="Aucun document généré pour ce dossier — rien à envoyer au citoyen.")
    dernier_document = documents[0]  # list_documents_generes trie par version décroissante

    document_maj = update_document_genere_statut(dernier_document["id"], "en_attente_validation_citoyen")
    if not document_maj:
        raise HTTPException(status_code=502, detail="Échec de la mise à jour du document généré")

    apres = await evenements.transition_statut(
        dossier_id, "en_attente_validation_citoyen", acteur_type="consultant", acteur_id=consultant["id"],
        libelle="Document envoyé au citoyen pour validation",
        details={"document_genere_id": dernier_document["id"], "version": dernier_document.get("version")},
        dossier_actuel=dossier,
    )
    if not apres:
        raise HTTPException(status_code=502, detail="Échec de la mise à jour du statut du dossier")

    await audit.journaliser(
        "document_envoye_citoyen", acteur=consultant, cible_type="dossier", cible_id=dossier_id,
        cible_libelle=dossier.get("numero_suivi"),
    )
    return {"dossier": apres, "document_genere": document_maj}


@app.post("/consultant/dossiers/{dossier_id}/analyser")
async def consultant_analyser_dossier(dossier_id: str, consultant: dict = Depends(get_current_consultant)):
    """
    Analyse assistée par LLM (Sprint E, Tâche E.2) : résumé, incohérences,
    complétude vis-à-vis des règles de gestion (RG1-RG6) applicables au
    cas_legal, suggestions — jamais de décision automatique (cf. Tâche E.1,
    prompt système repris mot pour mot, rôle read+suggest uniquement).

    `ocr_disponible` (renvoyé au client) reflète si l'OCR CNI (Sprint K) a
    réellement été lancé sur ce dossier — au moins un champ en source="ocr"
    parmi les formulaires — pas un simple drapeau figé : tant qu'aucun champ
    ne vient de l'OCR, les règles 2/3 du prompt système (incohérence
    dialogue/OCR, confiance OCR) n'ont simplement rien à comparer, ce que le
    client doit pouvoir distinguer d'un vrai résultat d'analyse OCR.
    """
    dossier = _verifier_dossier_commune_consultant(dossier_id, consultant)
    _exiger_action_autorisee(dossier, "analyser")

    documents = list_documents(dossier_id)
    formulaires = list_document_formulaires(dossier_id)
    formulaire_acte = get_or_create_formulaire_acte(dossier_id)
    if formulaire_acte and not any(f["id"] == formulaire_acte["id"] for f in formulaires):
        formulaires.append(formulaire_acte)

    contexte = {"dossier": dossier, "documents": documents, "document_formulaires": formulaires}

    # Vues RÉSOLUES (document_generator.py, mêmes fonctions que D.2/D.3) plutôt
    # que de laisser le LLM reconstruire lui-même le mapping slots-dialogue
    # (ex. "date_naissance_enfant") <-> champs XSD (ex. "dateNaissance") — trouvé
    # en testant cette tâche : sans ce mapping explicite, l'assistant confondait
    # les deux nomenclatures et signalait des champs bien remplis comme manquants.
    commune = get_commune(dossier.get("commune_id"))
    champs_formulaire = {}
    for formulaire in formulaires:
        for champ in (formulaire.get("champs") or []):
            if champ.get("valeur") is not None:
                champs_formulaire[champ["nom"]] = champ["valeur"]
    jugement_requis = dossier.get("cas_legal") == "jugement_requis"
    valeurs_resolues, champs_bloquants_verifies = resoudre_template(dossier, commune, champs_formulaire, jugement_requis)

    prompt_utilisateur = (
        build_assistant_consultant_prompt(contexte)
        + "\n\nVALEURS RÉSOLUES pour le document final (mêmes noms que extrait_naissance.xsd, déjà "
        "fusionnées depuis les slots du dialogue et les formulaires ci-dessus — c'est CETTE vue qui "
        f"fait foi pour juger la complétude, pas les sections précédentes) :\n"
        f"{json.dumps(valeurs_resolues, ensure_ascii=False, indent=2, default=str)}\n\n"
        "Champs VÉRIFIÉS PAR LE SYSTÈME comme obligatoires (RG6) et actuellement vides dans la vue "
        f"ci-dessus : {', '.join(champs_bloquants_verifies) if champs_bloquants_verifies else 'aucun'}. "
        "Inclus-les nécessairement dans completude.elements_manquants avec gravite='bloquant'. "
        "Un champ vide qui n'est PAS dans cette liste (optionnel) est au plus 'a_verifier' ou 'mineur', "
        "jamais 'bloquant'."
        "\n\nRetourne le JSON demandé (resume, incoherences, champs_a_verifier, completude, suggestions_generales)."
    )

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL_GENERATOR,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_ASSISTANT_CONSULTANT},
            {"role": "user", "content": prompt_utilisateur}
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "analyse_dossier", "strict": True, "schema": SCHEMA_ANALYSE_ASSISTANT}
        },
        "stream": False,
        "temperature": 0.2,  # analyse, pas une conversation : moins de variance créative désirée
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            analyse = await call_openrouter_structured(client, headers, payload)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Erreur de l'assistant : {str(e)}")

    analyse["ocr_disponible"] = any(
        champ.get("source") == "ocr"
        for formulaire in formulaires
        for champ in (formulaire.get("champs") or [])
    )
    return analyse


# --- Cas particuliers (Sprint E, Tâche E.3) ---

class CasParticulierIn(BaseModel):
    type_incident: str
    description: Optional[str] = None
    options_proposees: list = []


@app.get("/consultant/dossiers/{dossier_id}/cas-particuliers")
async def consultant_liste_cas_particuliers(dossier_id: str, consultant: dict = Depends(get_current_consultant)):
    _verifier_dossier_commune_consultant(dossier_id, consultant)
    return {"cas_particuliers": list_cas_particuliers(dossier_id)}


@app.post("/consultant/dossiers/{dossier_id}/cas-particuliers")
async def consultant_creer_cas_particulier(
    dossier_id: str, body: CasParticulierIn, consultant: dict = Depends(get_current_consultant)
):
    """
    Création d'un cas particulier (Tâche E.3) — soit par l'agent (E.2, cf.
    document_generator.py pour les cas déclenchés automatiquement à la
    génération), soit ici par le consultant lui-même quand il repère une
    situation non couverte par les règles codées (cf. Flux §2.5 : "deux
    déclarants, document dans une langue non attendue, informations
    contradictoires entre deux uploads"...).
    """
    dossier = _verifier_dossier_commune_consultant(dossier_id, consultant)
    _exiger_action_autorisee(dossier, "creer_cas")

    if body.type_incident not in TYPES_INCIDENT_CAS_PARTICULIER:
        raise HTTPException(
            status_code=400,
            detail=f"type_incident invalide. Attendu l'un de : {TYPES_INCIDENT_CAS_PARTICULIER}"
        )
    if not (1 <= len(body.options_proposees) <= 3):
        raise HTTPException(status_code=400, detail="options_proposees doit contenir entre 1 et 3 options (§2.5 du Flux)")

    cas = create_cas_particulier(dossier_id, body.type_incident, body.description, body.options_proposees)
    if not cas:
        raise HTTPException(status_code=502, detail="Échec de la création du cas particulier")
    return cas


class ResoudreCasParticulierIn(BaseModel):
    decision_consultant: str


@app.post("/consultant/dossiers/{dossier_id}/cas-particuliers/{cas_id}/resoudre")
async def consultant_resoudre_cas_particulier(
    dossier_id: str, cas_id: str, body: ResoudreCasParticulierIn, consultant: dict = Depends(get_current_consultant)
):
    """
    Le consultant choisit une des options proposées (ou en formule une autre
    librement, cf. §2.5) — `decision_consultant` toujours renseigné par un
    humain via ce endpoint, jamais par défaut : rejeté si vide (§2.5 :
    "l'agent ne prend jamais cette décision seul").
    """
    dossier = _verifier_dossier_commune_consultant(dossier_id, consultant)
    _exiger_action_autorisee(dossier, "resoudre_cas")

    if not body.decision_consultant or not body.decision_consultant.strip():
        raise HTTPException(status_code=400, detail="decision_consultant ne peut pas être vide")

    cas = get_cas_particulier(cas_id)
    if not cas or cas["dossier_id"] != dossier_id:
        raise HTTPException(status_code=404, detail="Cas particulier introuvable pour ce dossier")

    resultat = resoudre_cas_particulier(cas_id, body.decision_consultant.strip())
    if not resultat:
        raise HTTPException(status_code=502, detail="Échec de l'enregistrement de la décision")
    return resultat

# --- Endpoints admin (Sprint C, Tâche C.4) ---

class CommuneIn(BaseModel):
    nom: str
    region: Optional[str] = None
    departement: Optional[str] = None
    arrondissement: Optional[str] = None


class CommunePatch(BaseModel):
    region: Optional[str] = None
    departement: Optional[str] = None
    arrondissement: Optional[str] = None


@app.get("/admin/communes")
async def admin_liste_communes(admin: dict = Depends(get_current_admin)):
    communes = list_communes_admin()
    for commune in communes:
        if commune.get("tampon_numerique_url"):
            commune["tampon_url_signee"] = get_tampon_signed_url(commune["tampon_numerique_url"])
    return {"communes": communes}


@app.post("/admin/communes")
async def admin_creer_commune(body: CommuneIn, admin: dict = Depends(get_current_admin)):
    commune = create_commune(body.nom, body.region, body.departement, body.arrondissement)
    if not commune:
        raise HTTPException(status_code=502, detail="Échec de la création de la commune (nom déjà pris ?)")
    await audit.journaliser(
        "commune_creee", acteur=admin, cible_type="commune", cible_id=commune.get("id"), cible_libelle=body.nom
    )
    return commune


@app.patch("/admin/communes/{commune_id}")
async def admin_maj_commune(commune_id: str, body: CommunePatch, admin: dict = Depends(get_current_admin)):
    champs = {k: v for k, v in body.model_dump().items() if v is not None}
    commune = update_commune(commune_id, **champs)
    if not commune:
        raise HTTPException(status_code=404, detail="Commune introuvable ou mise à jour échouée")
    await audit.journaliser(
        "commune_modifiee", acteur=admin, cible_type="commune", cible_id=commune_id,
        cible_libelle=commune.get("nom"), details=champs,
    )
    return commune


# --- Tampon numérique (Sprint G, Tâche G.1, §5.4 — AUCUNE valeur légale confirmée à ce stade) ---

EXTENSIONS_PAR_MIME_TAMPON = {"image/png": "png", "image/jpeg": "jpg"}
MAX_TAMPON_BYTES = 5 * 1024 * 1024  # 5 Mo — une image de tampon, pas une photo de document


@app.post("/admin/communes/{commune_id}/tampon")
async def admin_uploader_tampon(
    commune_id: str,
    fichier: UploadFile = File(...),
    confirmation: bool = Form(...),
    admin: dict = Depends(get_current_admin),
):
    """
    Enregistrement du tampon numérique d'une commune (§5.4, proposition V2 —
    PAS une fonctionnalité à valeur légale confirmée, cf. mise en garde
    affichée côté frontend sur cet écran). Refuse explicitement si la case de
    confirmation n'est pas cochée : ce n'est PAS un champ file input anonyme,
    c'est un acte volontaire d'un représentant autorisé, journalisé
    (tampon_confirmations, migration 006) avec qui et quand — jamais
    silencieux, jamais implicite.
    """
    if not confirmation:
        raise HTTPException(
            status_code=400,
            detail="La confirmation d'autorisation est obligatoire pour enregistrer un tampon numérique.",
        )

    commune = get_commune(commune_id)
    if not commune:
        raise HTTPException(status_code=404, detail="Commune introuvable")

    if fichier.content_type not in EXTENSIONS_PAR_MIME_TAMPON:
        raise HTTPException(
            status_code=415,
            detail=f"Format non supporté ({fichier.content_type}). Attendu : {list(EXTENSIONS_PAR_MIME_TAMPON)}",
        )

    contenu = await fichier.read()
    if not contenu:
        raise HTTPException(status_code=400, detail="Fichier vide")
    if len(contenu) > MAX_TAMPON_BYTES:
        raise HTTPException(status_code=413, detail=f"Fichier trop volumineux (max {MAX_TAMPON_BYTES // (1024 * 1024)} Mo)")

    extension = EXTENSIONS_PAR_MIME_TAMPON[fichier.content_type]
    chemin = upload_tampon(commune_id, contenu, extension, fichier.content_type)
    if not chemin:
        raise HTTPException(status_code=502, detail="Échec du stockage du tampon")

    confirmation_row = confirmer_tampon(commune_id, admin["id"], chemin)
    if not confirmation_row:
        raise HTTPException(status_code=502, detail="Le fichier a été stocké mais la confirmation n'a pas pu être journalisée — réessayer.")

    await audit.journaliser(
        "tampon_enregistre", acteur=admin, cible_type="commune", cible_id=commune_id,
        cible_libelle=commune.get("nom"),
    )
    return {
        "commune_id": commune_id,
        "fichier_url": chemin,
        "url_signee": get_tampon_signed_url(chemin),
        "confirmation": confirmation_row,
    }


@app.get("/admin/communes/{commune_id}/tampon-confirmations")
async def admin_liste_confirmations_tampon(commune_id: str, admin: dict = Depends(get_current_admin)):
    """Journal des confirmations pour une commune (traçabilité, critère de validation de G.1)."""
    confirmations = list_tampon_confirmations(commune_id)
    return {"confirmations": confirmations}


class ConsultantIn(BaseModel):
    email: str
    commune: str
    nom_complet: Optional[str] = Field(default=None, max_length=120)


class ConsultantPatch(BaseModel):
    commune: Optional[str] = None
    actif: Optional[bool] = None


@app.get("/admin/consultants")
async def admin_liste_consultants(admin: dict = Depends(get_current_admin)):
    return {"consultants": list_consultants()}


@app.post("/admin/consultants")
async def admin_creer_consultant(body: ConsultantIn, admin: dict = Depends(get_current_admin)):
    """
    Crée un compte consultant (DSF A2). Le mot de passe temporaire retourné
    dans la réponse n'apparaît qu'UNE SEULE FOIS — à communiquer au
    consultant par un canal sûr, il ne sera plus jamais accessible ensuite.
    """
    if not resoudre_commune_id(body.commune):
        raise HTTPException(
            status_code=400,
            detail=f"Commune {body.commune!r} inconnue — créez-la d'abord via POST /admin/communes"
        )
    consultant = create_consultant(body.email, body.commune, body.nom_complet)
    if not consultant:
        raise HTTPException(status_code=502, detail="Échec de la création du compte consultant")
    await audit.journaliser(
        "consultant_cree", acteur=admin, cible_type="consultant", cible_id=consultant["id"],
        cible_libelle=body.email, details={"commune": body.commune},
    )
    return consultant


@app.patch("/admin/consultants/{consultant_id}")
async def admin_maj_consultant(consultant_id: str, body: ConsultantPatch, admin: dict = Depends(get_current_admin)):
    if body.commune is None and body.actif is None:
        raise HTTPException(status_code=400, detail="Fournir au moins 'commune' ou 'actif'")
    if body.commune is not None:
        if not resoudre_commune_id(body.commune):
            raise HTTPException(status_code=400, detail=f"Commune {body.commune!r} inconnue")
        if not update_consultant_commune(consultant_id, body.commune):
            raise HTTPException(status_code=502, detail="Échec de la mise à jour de la commune")
        await audit.journaliser(
            "consultant_commune_modifiee", acteur=admin, cible_type="consultant", cible_id=consultant_id,
            details={"commune": body.commune},
        )
    if body.actif is not None:
        if not set_consultant_actif(consultant_id, body.actif):
            raise HTTPException(status_code=502, detail="Échec du changement de statut actif")
        await audit.journaliser(
            "consultant_reactive" if body.actif else "consultant_desactive",
            acteur=admin, cible_type="consultant", cible_id=consultant_id,
        )
    return {"id": consultant_id, "commune": body.commune, "actif": body.actif}


class TemplateIn(BaseModel):
    type_demarche: str
    nom_fichier_xml: str
    nom_fichier_html: str
    version: int = 1


class TemplatePatch(BaseModel):
    nom_fichier_xml: Optional[str] = None
    nom_fichier_html: Optional[str] = None
    version: Optional[int] = None


@app.get("/admin/templates")
async def admin_liste_templates(admin: dict = Depends(get_current_admin)):
    return {"templates": list_templates()}


@app.post("/admin/templates")
async def admin_creer_template(body: TemplateIn, admin: dict = Depends(get_current_admin)):
    template = create_template(body.type_demarche, body.nom_fichier_xml, body.nom_fichier_html, body.version)
    if not template:
        raise HTTPException(status_code=502, detail="Échec de la création du template (type_demarche déjà pris ?)")
    await audit.journaliser(
        "template_cree", acteur=admin, cible_type="template", cible_id=template.get("id"),
        cible_libelle=body.type_demarche,
    )
    return template


@app.patch("/admin/templates/{type_demarche}")
async def admin_maj_template(type_demarche: str, body: TemplatePatch, admin: dict = Depends(get_current_admin)):
    champs = {k: v for k, v in body.model_dump().items() if v is not None}
    template = update_template(type_demarche, **champs)
    if not template:
        raise HTTPException(status_code=404, detail="Template introuvable ou mise à jour échouée")
    await audit.journaliser(
        "template_modifie", acteur=admin, cible_type="template", cible_id=template.get("id"),
        cible_libelle=type_demarche, details=champs,
    )
    return template


@app.get("/admin/supervision")
async def admin_supervision(admin: dict = Depends(get_current_admin)):
    """Tableau de bord DSF A4 : volumes par statut, délai moyen de traitement, dossiers bloqués (Q3/Q5)."""
    return get_supervision()

# --- Mode administratif : bascule information -> administratif (Sprint B, Tâche B.3) ---

from temps_reel.etat import SLOTS_VIDES_EXTRAIT_NAISSANCE  # noqa: E402 — définition unique

# Confirmation directe (oui/non), pas un appel LLM dédié : dans les dialogues
# types (Exemples_Dialogues_Agent_SUNU-MAIRIE.md, 1.2/1.3/2.1), aussi bien
# l'acceptation de bascule que la confirmation après relecture (RG7) sont des
# "oui" très directs — un appel LLM supplémentaire juste pour classifier ça
# alourdirait la latence pour un gain marginal. Réutilisée pour les deux
# usages (Tâche B.3 et B.4). Limite connue : ne détecte pas une acceptation
# formulée de façon indirecte/détournée — une réponse qui ne matche aucun de
# ces mots est traitée comme NON affirmative (donc, en relecture, comme une
# demande de correction — cf. RG7 : ne jamais forcer l'envoi par défaut).
#
# ⚠️ BUG RÉEL trouvé en test terrain (2026-08-20) : cette liste était
# uniquement en FRANÇAIS alors que les citoyens sont censés pouvoir dialoguer
# en pulaar (raison d'être du produit) — un "oui" dit en pulaar n'était donc
# JAMAIS reconnu, bloquant silencieusement toute bascule information ->
# administratif et toute confirmation RG7 pour un citoyen pulaarophone.
# "eyyi" ajouté d'après plusieurs transcriptions réelles cohérentes ("Eyyi
# mbiɗo joogui" = "oui je l'ai", en réponse directe à une question fermée) —
# PAS vérifié par un locuteur natif, à corriger/compléter (variantes
# d'orthographe, autres formulations d'accord) dès qu'un locuteur pulaar
# peut relire cette liste.
# Correctif RG7 (2026-09-14) : la détection gère désormais la négation et les
# réserves (« non ce n'est pas correct », « oui mais… » ne sont plus des
# confirmations) — implémentation et tests dans temps_reel/intentions.py.
from temps_reel.intentions import MOTS_REPONSE_AFFIRMATIVE, est_reponse_affirmative  # noqa: E402


# Décision Q3/Q5, §1 du roadmap : 3 itérations de relecture rouverte par une
# correction (pas une confirmation) sans jamais aboutir -> le dossier est
# vraisemblablement mal engagé (incompréhension répétée, cas trop complexe
# pour le dialogue vocal) -> bloqué, signalé à l'admin (Tâche G.3) plutôt que
# de boucler indéfiniment sur le même récapitulatif.
SEUIL_ITERATIONS_CORRECTION_BLOQUE = 3


# Alias explicite pour le site d'appel de la bascule (Tâche B.3) — même
# détection que est_reponse_affirmative, nom conservé pour la lisibilité au
# point d'usage et la compatibilité avec test_bascule_administratif.py.
detecter_acceptation_bascule = est_reponse_affirmative


def est_demarche_extrait_naissance(nom_demarche: str) -> bool:
    """
    La démarche trouvée par la recherche est-elle celle que le dialogue guidé
    sait mener ?

    Le test se faisait sur le mot « naissance » présent n'importe où dans le
    nom : « certificat de naissance » et « déclaration de naissance », qui sont
    d'autres démarches, basculaient donc vers l'extrait de naissance. La
    reconnaissance passe depuis l'étape 2.3 par les mots-clés déclarés en base
    (`demarche_definitions.mots_cles`).
    """
    return demarche_config.reconnaitre_demarche(nom_demarche) is not None


def fusionner_slots(actuels: dict, maj: dict) -> dict:
    """
    Fusion défensive : une valeur non nulle dans `maj` remplace celle
    d'`actuels`, une valeur nulle ne l'efface jamais. Filet de sécurité en
    plus de la consigne donnée au LLM (SYSTEM_PROMPT_GENERATOR_ADMINISTRATIF)
    de ne jamais mettre à null un slot déjà rempli.
    """
    fusion = dict(actuels)
    for cle, valeur in (maj or {}).items():
        if cle == "age_enfant":
            if valeur and valeur.get("valeur") is not None and valeur.get("unite"):
                fusion["age_enfant"] = valeur
        elif valeur is not None:
            fusion[cle] = valeur
    return fusion


# ---------------------------------------------------------------------------
# Dialogue vocal temps réel : déplacé dans temps_reel/ (moteur de dialogue,
# sessions persistées et possédées par un citoyen, protocoles v1 et v2) et
# exposé par routers/temps_reel.py. L'ancienne boucle (état en mémoire jamais
# purgé, sans propriété de session, sans interruption) a été retirée — cf.
# TODO_BACKEND_V3.md, phase 3, et README-TEMPS-REEL-MOBILE.md.
# ---------------------------------------------------------------------------

# --- Routes de base ---

@app.get("/")
async def root():
    return {"message": "Agent SUNU-LANGUES - Architecture deux phases (Générateur + Formateur)"}

@app.get("/health")
async def health():
    return {"status": "ok", "sessions": len(sessions)}