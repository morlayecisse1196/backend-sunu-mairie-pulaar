## dépendance python-jose
>> pip install python-jose
>> pip install soundfile
>> pip install psycopg

## commande lancement
>>  .\venv\Scripts\python.exe -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 --ws-ping-interval 20 --ws-ping-timeout 20

## Lancement recommandé (avec keep-alive WebSocket)
Sur mobile (4G/WiFi instable), sans ping/pong protocole, une connexion à moitié coupée
peut rester "ouverte" côté serveur sans jamais lever d'erreur. Ces deux flags activent
les ping/pong au niveau du protocole WebSocket (transparents pour le client — dart:io
WebSocket / web_socket_channel y répond automatiquement) :
>> uvicorn main:app --reload --port 8000 --ws-ping-interval 20 --ws-ping-timeout 20
En production (sans --reload), utiliser cette commande.

## Remarque 
À retenir pour l'intégration Flutter
Le WebSocket doit accepter des messages binaires (audio) et des messages texte (JSON de contrôle).
Le mobile doit envoyer l'audio en chunks de 1 à 2 secondes pour un temps réel optimal.
La lecture audio doit être bufférisée pour éviter les saccades.

🗺️ Prochaine étape : Intégration de l'avatar Rive
Comme nous en avons discuté, l'avatar Rive est une fonctionnalité future. Notre backend est solide et peut être étendu pour envoyer des signaux de contrôle.

Ce qu'il faudra ajouter (quand vous serez prêt)
Message	Type	Contenu	Utilisation
status	JSON	{"type":"status","state":"listening"}	Avatar en attente d'écoute
status	JSON	{"type":"status","state":"thinking"}	Avatar en réflexion
status	JSON	{"type":"status","state":"speaking"}	Avatar parle
visemes	JSON	{"type":"visemes","frames":[...]}	Synchronisation labiale


## Teste bruno
ws://localhost:8000/ws/test_session?token=eyJhbG............

POST https://ntmqnhyzpevbfosopmjy.supabase.co/auth/v1/token?grant_type=password

{
  "email":"morlayecis0003@gmail.com",
  "password":"motdepasse123"
}

apiKey = 

ADMIN
EMAIL=admin.test.g1@sunu-mairie.local
PASSWORD=QiK8Imj30JoWLVYn
