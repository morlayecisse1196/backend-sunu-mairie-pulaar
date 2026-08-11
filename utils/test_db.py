import os
import psycopg
from dotenv import load_dotenv
import socket

load_dotenv()

# Forcer IPv4 (si l'IPv6 cause des problèmes)
try:
    # Tenter de résoudre en IPv4 d'abord
    addrinfo = socket.getaddrinfo(
        "db.ntmqnhyzpevbfosopmjy.supabase.co",
        5432,
        socket.AF_INET,  # IPv4
        socket.SOCK_STREAM
    )
    host = addrinfo[0][4][0]
    print(f"✅ Résolution IPv4 : {host}")
except:
    # Fallback sur IPv6
    addrinfo = socket.getaddrinfo(
        "db.ntmqnhyzpevbfosopmjy.supabase.co",
        5432,
        socket.AF_INET6,
        socket.SOCK_STREAM
    )
    host = addrinfo[0][4][0]
    print(f"✅ Résolution IPv6 : {host}")

try:
    conn = psycopg.connect(
        host=host,
        port=5432,
        dbname="postgres",
        user="postgres",
        password=os.getenv("SUPABASE_DB_PASSWORD"),
        sslmode="require",
        connect_timeout=10
    )
    print("✅ Connexion réussie !")
    conn.close()
except Exception as e:
    print(f"❌ Erreur : {e}")