import os
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")
# Origine autorisée pour CORS (web consultant/admin, Sprint C+). Défaut = serveur
# de dev Next.js standard, pour ne pas bloquer le développement local avant que
# FRONTEND_URL soit posé dans .env — à surcharger avec la vraie URL en prod.
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")