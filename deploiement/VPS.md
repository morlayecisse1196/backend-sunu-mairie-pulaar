# Déploiement — VPS de production

Mis en service le 2026-11-15 sur un VPS Hostinger neuf (Ubuntu 24.04.5 LTS,
2 vCPU, 8 Go, 96 Go NVMe).

**Adresse : <https://sunu-mairie.duckdns.org>**

Ce document décrit ce qui tourne et comment le mettre à jour. Il remplace
`doc_vps_hostinger.md`, qui décrit une machine à laquelle plus personne n'a
accès et contient des secrets morts — à supprimer.

---

## 1. Ce qui tourne

```
                    Internet
                       │  443 (TLS)
                 ┌─────▼─────┐
                 │   Caddy   │  certificat Let's Encrypt, renouvelé seul
                 └──┬─────┬──┘
        /api/*  ────┘     └──── tout le reste
           │                         │
   127.0.0.1:8000            127.0.0.1:3000
   sunu-backend              sunu-web
   FastAPI + WebSocket       Next.js
```

| Service | Rôle | Dossier |
|---|---|---|
| `sunu-backend` | API FastAPI, dialogue temps réel | `/opt/sunu/backend` |
| `sunu-web` | Espaces consultant, admin et citoyen | `/opt/sunu/web` |
| `caddy` | HTTPS, répartition, redirection depuis l'IP | `/etc/caddy/Caddyfile` |

Les deux applications écoutent **uniquement sur `127.0.0.1`**. Caddy est seul à
leur parler : il n'existe aucune porte en clair sur la machine. Le pare-feu
(`ufw`) n'ouvre que 22, 80 et 443.

Les deux services tournent sous l'utilisateur système **`sunu`**, sans shell de
connexion, avec `NoNewPrivileges`, `ProtectSystem=strict` et `/tmp` isolé.

### Pourquoi l'API est sous `/api`

`/admin` est **à la fois** une page Next et une famille d'endpoints FastAPI.
Sur une même origine sans préfixe, les deux se disputeraient l'URL.
`handle_path /api/*` retire le préfixe avant de transmettre : le backend ne
voit que ses propres chemins et son code ignore tout de ce découpage.

Deux bénéfices : une seule origine, donc **aucune question de CORS** entre le
web et l'API ; et un seul certificat.

Le WebSocket (`wss://…/api/ws/v2`) passe par la même règle, sans configuration
supplémentaire — Caddy relaie l'upgrade nativement.

---

## 2. Mettre à jour

### Le backend

```bash
ssh root@sunu-mairie.duckdns.org
cd /opt/sunu/backend
runuser -u sunu -- git pull
# seulement si requirements.txt a changé :
runuser -u sunu -- venv/bin/pip install -r requirements.txt
systemctl restart sunu-backend
systemctl is-active sunu-backend
```

### Le web

```bash
cd /opt/sunu/web
runuser -u sunu -- git pull
runuser -u sunu -- npm ci          # si package-lock.json a changé
runuser -u sunu -- npx next build  # TOUJOURS : voir l'avertissement ci-dessous
systemctl restart sunu-web
```

> ⚠️ **Les variables `NEXT_PUBLIC_*` sont figées à la compilation.** Next les
> remplace dans le code au moment du `build`, pas au démarrage. Changer
> l'adresse de l'API ou le projet Supabase dans `.env.local` n'a **aucun effet**
> tant qu'on n'a pas rebâti. C'est aussi pourquoi changer de nom de domaine
> impose une recompilation.

---

## 3. Journaux

```bash
journalctl -u sunu-backend -f     # dialogue, préchauffage vocal, erreurs
journalctl -u sunu-web -f
journalctl -u caddy -f            # accès HTTP et renouvellement du certificat
```

Au démarrage, le backend réveille les Spaces Hugging Face. Une ligne
`prechauffage.termine asr=True tts=True modele_tts=True` confirme que l'ASR et
le TTS répondent — sans elle, le premier citoyen attendra le réveil à froid
(mesuré à 55 s).

---

## 4. Secrets

`/opt/sunu/backend/.env` et `/opt/sunu/web/.env.local`, tous deux en `600` et
appartenant à `sunu`. Ils ne sont **pas** dans les dépôts (`.gitignore`).

Deux points qui ont déjà causé des pannes silencieuses :

* **`DATABASE_URL` doit viser le pooler**, pas l'hôte direct
  `db.<ref>.supabase.co` : celui-ci n'a plus qu'un enregistrement AAAA (IPv6).
  Sur une machine sans route IPv6, la recherche sémantique échoue et retombe
  **sans rien dire** sur la recherche par mots-clés.
* **`FRONTEND_URLS`** doit lister l'origine de production. Vide, `config.py`
  retombe sur ses origines de développement (`localhost:3000/3001`) et rien
  d'autre ne serait autorisé.

---

## 5. Accès SSH

Deux clés distinctes, révocables séparément :

| Clé | Portée |
|---|---|
| `deploiement-sunu-mairie` | accès `root` au VPS, pour l'administration |
| `vps-sunu-mairie-lecture` | clé de déploiement GitHub, **lecture seule**, pour `git pull` du dépôt web (privé) |

Retirer un accès au VPS :

```bash
sed -i '/<commentaire-de-la-clé>/d' ~/.ssh/authorized_keys
```

---

## 6. Vérifier que tout va bien

```bash
curl -s https://sunu-mairie.duckdns.org/api/health
curl -s https://sunu-mairie.duckdns.org/api/communes
```

La seconde doit renvoyer les communes de la table `communes` — jamais
« National », qui est la sentinelle du RAG et non une commune.

Depuis un navigateur, sur n'importe quelle page du site, la console doit
donner `window.isSecureContext === true` : c'est la condition sans laquelle le
micro (`getUserMedia`) est refusé, et donc sans laquelle l'écran « Parler » ne
peut pas fonctionner.
