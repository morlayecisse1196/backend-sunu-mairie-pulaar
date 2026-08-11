# test_audio_ws.py
import asyncio
import websockets
import json
import os
from dotenv import load_dotenv

load_dotenv()

# Lire un fichier audio (WAV, MP3, etc.)
AUDIO_FILE = "audio/whatsapp_audio5.wav"  # Remplacez par votre fichier
# Le token n'est jamais codé en dur : mettez TEST_SUPABASE_TOKEN dans votre .env (fichier non commité)
TOKEN = os.getenv("TEST_SUPABASE_TOKEN")
if not TOKEN:
    raise RuntimeError("TEST_SUPABASE_TOKEN manquant dans .env — récupérez un JWT valide depuis Supabase")

async def test_audio_websocket():
    uri = f"ws://localhost:8000/ws/test_session?token={TOKEN}"
    
    try:
        async with websockets.connect(uri) as websocket:
            print("🔗 Connecté au WebSocket")
            
            # 1. Lire le fichier audio en bytes
            with open(AUDIO_FILE, "rb") as f:
                audio_bytes = f.read()
            print(f"📁 Audio lu : {len(audio_bytes)} bytes")
            
            # 2. Envoyer les bytes audio
            await websocket.send(audio_bytes)
            print("📤 Audio envoyé")
            
            # 3. Recevoir les réponses
            while True:
                message = await websocket.recv()
                try:
                    data = json.loads(message)
                    msg_type = data.get("type", "unknown")
                    
                    if msg_type == "stream_fr":
                        print(f"🇫🇷 (FR) : {data['content']}")
                    elif msg_type == "stream_pulaar":
                        print(f"🇵🇺 (Pulaar) : {data['content']}")
                    elif msg_type == "end":
                        print("✅ Fin de la réponse")
                        break
                    elif msg_type == "error":
                        print(f"❌ Erreur : {data['content']}")
                        break
                except json.JSONDecodeError:
                    print(f"📨 Message brut : {message}")
                    
    except Exception as e:
        print(f"❌ Erreur : {e}")

if __name__ == "__main__":
    asyncio.run(test_audio_websocket())