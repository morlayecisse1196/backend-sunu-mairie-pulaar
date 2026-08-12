import asyncio
import websockets
import json
import os
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Configuration
# AUDIO_FILE = "C:\\Users\\USER\\Desktop\\DATASET_PULAAR\\RESOURCES\\AUDIO\\whatsapp_audio3.wav"  # Remplacez par votre fichier audio
AUDIO_FILE = "audio/whatsapp_audio2.wav"  # Fichier audio d'entrée
# Le token n'est jamais codé en dur : mettez TEST_SUPABASE_TOKEN dans votre .env (fichier non commité)
TOKEN = os.getenv("TEST_SUPABASE_TOKEN")
if not TOKEN:
    raise RuntimeError("TEST_SUPABASE_TOKEN manquant dans .env — récupérez un JWT valide depuis Supabase")


# Créer un dossier avec timestamp
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
session_dir = f"recordings/session_{timestamp}"
os.makedirs(session_dir, exist_ok=True)
print(f"📁 Dossier de session : {session_dir}")

# Sauvegarder l'audio d'entrée (le fichier envoyé)
input_audio_path = os.path.join(session_dir, "input_audio.wav")
with open(AUDIO_FILE, "rb") as f_in:
    with open(input_audio_path, "wb") as f_out:
        f_out.write(f_in.read())
print(f"📥 Audio d'entrée sauvegardé : {input_audio_path}")

async def test_audio_websocket():
    # uri = f"ws://localhost:8000/ws/test_session?token={TOKEN}"
    uri = f"ws://76.13.134.241:8000/ws/test_session?token={TOKEN}"
    
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
            output_counter = 0  # Pour numéroter les fichiers audio reçus
            
            while True:
                message = await websocket.recv()
                
                # Si c'est un message binaire (audio TTS)
                if isinstance(message, bytes):
                    output_counter += 1
                    output_file = os.path.join(session_dir, f"tts_output_{output_counter}.wav")
                    with open(output_file, "wb") as f:
                        f.write(message)
                    print(f"🔊 Audio TTS reçu ({len(message)} bytes) sauvegardé : {output_file}")
                    continue
                
                # Sinon c'est un message texte (JSON)
                try:
                    data = json.loads(message)
                    msg_type = data.get("type", "unknown")
                    
                    if msg_type == "stream_fr":
                        print(f"🇫🇷 (FR) : {data['content']}")
                    elif msg_type == "stream_pulaar":
                        print(f"🇵🇺 (Pulaar) : {data['content']}")
                    elif msg_type == "tts_progress":
                        print(f"⏳ TTS progression : {data['current']}/{data['total']}")
                    elif msg_type == "tts_end":
                        print("🔊 TTS terminé")
                    elif msg_type == "end":
                        print("✅ Fin de la réponse")
                        break
                    elif msg_type == "error":
                        print(f"❌ Erreur : {data['content']}")
                        break
                    else:
                        print(f"📨 Message type inconnu : {data}")
                except json.JSONDecodeError:
                    print(f"📨 Message texte non JSON : {message}")
                    
    except Exception as e:
        print(f"❌ Erreur : {e}")
    
    print(f"\n📁 Tous les fichiers ont été sauvegardés dans : {session_dir}")
    print("   - input_audio.wav : votre fichier audio envoyé")
    print("   - tts_output_*.wav : les réponses audio générées par le TTS")

if __name__ == "__main__":
    asyncio.run(test_audio_websocket())