from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import httpx
import json
from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL
from search import search_demarches, format_demarche_pour_prompt

app = FastAPI(title="Agent SUNU-LANGUES - Version RAG simple")

sessions = {}

# --- Modèles ---

class ChatRequest(BaseModel):
    session_id: str
    message: str

class ChatResponse(BaseModel):
    reply: str

# --- Prompt structuré ---

def build_structured_prompt(question: str, context: str) -> str:
    """
    Construit un prompt structuré pour obtenir une réponse fiable.
    """
    if context:
        return f"""
Tu es un assistant municipal qui guide les citoyens en Pulaar.

INFORMATIONS OFFICIELLES :
{context}

QUESTION DU CITOYEN :
{question}

INSTRUCTIONS :
1. Réponds en Pulaar.
2. Utilise UNIQUEMENT les informations officielles ci-dessus.
3. Si une information n'est pas disponible, dis-le honnêtement.
4. Structure ta réponse en 3 parties :
   - Ce qu'il faut faire (documents, démarches)
   - Les conditions à remplir
   - Les coûts et délais
5. Si tu as des questions de vérification à poser, inclus-les.
6. Ne collecte jamais de données personnelles.

RÉPONSE :"""
    else:
        return f"""
Tu es un assistant municipal.

Je n'ai pas trouvé d'information spécifique pour ta question : "{question}".

Réponds en proposant une aide générale ou en orientant vers la mairie. Réponds en Pulaar.

RÉPONSE :"""

# --- Endpoint REST (pour debug) ---

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    history = sessions.get(request.session_id, [])
    history.append({"role": "user", "content": request.message})
    
    # Recherche RAG
    results = search_demarches(request.message)
    context = format_demarche_pour_prompt(results[0]) if results else ""
    
    prompt = build_structured_prompt(request.message, context)
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    # payload = {
    #     "model": "openai/gpt-3.5-turbo",
    #     "messages": [{"role": "user", "content": prompt}],
    #     "stream": False,
    #     "temperature": 0.3  # Faible pour des réponses précises
    # }

    payload = {
    "model": "meta-llama/llama-3-8b-instruct",  # Essaye celui-ci
    # ou "mistralai/mistral-7b-instruct"
    "messages": [{"role": "user", "content": prompt}],
    "stream": True,
    "temperature": 0.3  # Faible pour des réponses précises
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            data = response.json()
            reply = data["choices"][0]["message"]["content"]
            history.append({"role": "assistant", "content": reply})
            sessions[request.session_id] = history
            return ChatResponse(reply=reply)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

# --- WebSocket ---

@app.websocket("/ws/simple/{session_id}")
async def websocket_simple(websocket: WebSocket, session_id: str):
    await websocket.accept()
    
    history = sessions.get(session_id, [])
    
    try:
        while True:
            question = await websocket.receive_text()
            history.append({"role": "user", "content": question})
            
            # 1. RECHERCHE RAG
            results = search_demarches(question)
            context = format_demarche_pour_prompt(results[0]) if results else ""
            
            # 2. CONSTRUCTION DU PROMPT
            prompt = build_structured_prompt(question, context)
            
            # 3. APPEL OPENROUTER
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "openai/gpt-3.5-turbo",
                "messages": [{"role": "user", "content": prompt}],
                "stream": True,
                "temperature": 0.3
            }
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                try:
                    async with client.stream(
                        "POST",
                        f"{OPENROUTER_BASE_URL}/chat/completions",
                        headers=headers,
                        json=payload
                    ) as response:
                        response.raise_for_status()
                        
                        full_reply = ""
                        
                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                data_str = line[6:]
                                if data_str == "[DONE]":
                                    break
                                try:
                                    data = json.loads(data_str)
                                    delta = data["choices"][0]["delta"].get("content", "")
                                    if delta:
                                        full_reply += delta
                                        await websocket.send_text(delta)
                                except json.JSONDecodeError:
                                    pass
                        
                        # Sauvegarder l'historique
                        if full_reply:
                            history.append({"role": "assistant", "content": full_reply})
                            sessions[session_id] = history
                            await websocket.send_text("[END]")
                        
                except Exception as e:
                    await websocket.send_text(f"Erreur: {str(e)}")
                    break
                
    except WebSocketDisconnect:
        print(f"Client {session_id} déconnecté")

@app.get("/")
async def root():
    return {"message": "Agent SUNU-LANGUES - Version simple avec RAG"}

@app.get("/sessions")
async def list_sessions():
    return {"active_sessions": list(sessions.keys())}