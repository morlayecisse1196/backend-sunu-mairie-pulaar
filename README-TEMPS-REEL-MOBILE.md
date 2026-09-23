# Temps réel & dialogue mobile — contrat backend

Ce document décrit **ce que le backend expose aujourd'hui** pour l'application
mobile : le protocole WebSocket v2, la compatibilité v1, et les endpoints REST
associés (suivi, corrections à la voix, lecture du document, audio d'interface,
notifications).

Il est écrit pour être suffisant à lui seul pour écrire le client Flutter.

---

## 1. Vue d'ensemble

```
                     ┌──────────────────────────────────────────┐
  App mobile  ──WS──▶│ routers/temps_reel.py  (/ws/v2, /ws/{id})│
                     │            temps_reel/connexion.py        │
                     │   phase A « comprendre »  (verrou session)│
                     │   phase B « parler »      (annulable)     │
                     └──────────┬───────────────────────────────┘
                                │
             temps_reel/moteur.py (un tour de dialogue, sans transport)
                                │
      temps_reel/sessions.py (état persisté)   services/evenements.py (statuts)
```

Deux règles structurantes :

1. **Phase A jamais interrompue** : transcription, décision, écritures en base.
   Couper ici laisserait l'état incohérent (un slot écrit à moitié, un dossier
   créé sans numéro de suivi).
2. **Phase B toujours interruptible** : traduction pulaar + synthèse vocale. Le
   citoyen qui parle par-dessus l'agent (*barge-in*) l'arrête immédiatement.

Un seul moteur sert les deux protocoles : le v1 historique et le v2 sont deux
adaptateurs. Le comportement métier est donc strictement identique.

---

## 2. WebSocket v2 — `/ws/v2`

### 2.1 Ouverture

Connexion **sans jeton dans l'URL** (une URL fuit dans les journaux, les
proxies et l'historique). Le premier message doit être `auth`, dans les
**10 secondes** :

```json
{ "type": "auth", "token": "<JWT Supabase>", "session_id": "<optionnel>", "nouvelle_conversation": false }
```

- `session_id` : reprendre une session précédente (sinon la session active du
  citoyen est reprise, ou une nouvelle est créée).
- `nouvelle_conversation: true` : forcer une session neuve.

Réponses :

```json
{ "type": "auth_ok", "protocole": 2, "exp": 1789000000 }
{ "type": "session", "protocole": 2, "reprise": true, "nouvelle": false,
  "session_id": "…", "conversation_id": "…", "mode": "information",
  "phase": "collecte", "statut": "en_cours", "dossier_id": null,
  "numero_suivi": null, "document_attendu": null, "type_demarche": null }
{ "type": "status", "state": "listening" }
```

`exp` est l'expiration du jeton : le client renouvelle **avant** cette date avec
`auth_refresh`, sans rouvrir la connexion.

### 2.2 Messages du client → serveur

| Message | Charge | Effet |
|---|---|---|
| binaire | octets audio | un tour de dialogue vocal |
| `audio_debut` | `turn_id` | annonce le `turn_id` de l'audio binaire qui suit |
| `texte` | `texte`, `turn_id?` | un tour de dialogue écrit (≤ 1000 caractères) |
| `interrupt` | — | coupe la parole en cours (barge-in explicite) |
| `ping` | `t` | maintien de connexion → `pong` avec le même `t` |
| `auth_refresh` | `token` | renouvelle le jeton ; un jeton d'un **autre** compte ferme la connexion (4403) |
| `nouvelle_conversation` | `turn_id?` | clôt la session courante et en ouvre une neuve |

Envoyer de l'audio ou du texte **interrompt automatiquement** la parole en
cours : pas besoin d'envoyer `interrupt` d'abord.

Au-delà de **3 tours en file**, le serveur répond `error/file_pleine` plutôt que
d'empiler indéfiniment.

### 2.3 Messages du serveur → client

| Message | Quand | Champs |
|---|---|---|
| `audio_recu` | audio reçu | `turn_id`, `octets` |
| `status` | changement d'état | `state` ∈ `listening` \| `thinking` \| `speaking` |
| `etape` | progression de la phase A | `etape` ∈ `transcription` \| `reflexion` |
| `lent` | une étape dépasse 6 s | `etape` — à afficher (« ça prend un peu de temps… ») |
| `transcription` | ASR terminé | `texte` |
| `dossier_mis_a_jour` | dossier créé/modifié | `dossier_id`, `numero_suivi`, `statut`… |
| `attente_upload` | un document est attendu | `document_type`, `dossier_id` |
| `stream_fr` | réponse française complète | `content`, `message_id` |
| `stream_pulaar` | traduction, en flux | `content` (incrément) |
| **binaire** | audio TTS d'une phrase | — (à lire dans l'ordre d'arrivée) |
| `tts_progress` | après chaque phrase | `current` |
| `tts_end` | fin de la synthèse | — |
| `interrompu` | parole coupée | `turn_id` |
| `end` | fin du tour | `turn_id` |
| `error` | erreur | `code`, `content`, `recuperable` |
| `session` | session (re)attachée ou tournée | cf. §2.1 |
| `session_remplacee` | la session est reprise ailleurs | — puis fermeture 4409 |

Tous les messages d'un tour portent le même `turn_id` : le client peut jeter
sans risque ce qui appartient à un tour interrompu.

**L'audio TTS arrive phrase par phrase, pendant que la traduction est encore en
cours** — le citoyen entend la première phrase sans attendre la fin.

### 2.4 Codes de fermeture

| Code | Sens | Ce que fait le client |
|---|---|---|
| 4401 | authentification absente/invalide | reconnecter après un refresh de session |
| 4403 | session d'un autre utilisateur | ne pas réessayer avec cette session |
| 4408 | pas d'`auth` en 10 s | réessayer |
| 4409 | session reprise par une autre connexion | ne pas se reconnecter en boucle |
| 1011 | persistance indisponible | réessayer plus tard (dégradation honnête) |

### 2.5 Codes d'erreur (`error.code`)

`message_invalide`, `type_inconnu`, `file_pleine`, `auth_refresh_invalide`,
`parole_indisponible`, `synthese_vocale`, `transcription_indisponible`, et les
codes audio : `audio_vide`, `trop_volumineux`, `trop_court`, `trop_long`,
`format_audio_inconnu`, `non_supporte`, `conversion_echouee`.
Chaque erreur porte `recuperable` : `true` = le dialogue continue.

### 2.6 Formats audio acceptés

WAV, OGG/Opus, M4A/AAC, WebM. Le backend transcode en **WAV 16 kHz mono** via
ffmpeg avant l'ASR. Le mobile peut donc envoyer l'enregistrement natif de la
plateforme — inutile d'envoyer du WAV brut, bien plus lourd sur un réseau 3G.

---

## 3. WebSocket v1 — `/ws/{session_id}?token=…` (compatibilité)

L'application mobile actuelle continue de fonctionner sans modification : même
moteur, même sur-ensemble de messages (elle ignore les types inconnus). Deux
différences : le jeton est dans l'URL, et une session est identifiée par la clé
client de l'URL.

**Ce protocole est figé.** Toute nouveauté passe par v2.

---

## 4. Reprise, rotation, propriété des sessions

- **Propriété** : une session appartient à un citoyen. Une autre identité est
  refusée (4403) — jamais de reprise silencieuse du dossier de quelqu'un d'autre.
- **Reprise** : à la reconnexion, l'état est relu en base. Si un document était
  attendu, `attente_upload` est renvoyé ; si une réponse n'avait pas pu être
  dite, elle est rejouée.
- **Rotation** : dès qu'une démarche est envoyée ou bloquée, la session est close
  et une session neuve est ouverte automatiquement (message `session` avec
  `nouvelle: true`). Sans cela le citoyen restait coincé sur « votre démarche est
  déjà envoyée » à chaque nouvelle question.
- **Une seule connexion par session** : la nouvelle prend la main, l'ancienne
  reçoit `session_remplacee` puis 4409.

---

## 5. Endpoints REST du mobile

### Dialogue et suivi
| Méthode | Chemin | Rôle |
|---|---|---|
| POST | `/conversations` | démarrer une nouvelle démarche (pousse `session` aux connexions actives) |
| GET | `/conversations/active` | session en cours du citoyen |
| GET | `/mes-dossiers` · `/mes-dossiers/{id}` | suivi |
| GET | `/mes-dossiers/{id}/documents` | documents déposés |
| POST | `/dossiers/{id}/documents` | dépôt d'une photo (relance le dialogue) |
| POST | `/mes-dossiers/{id}/valider` | validation du document par le citoyen |
| POST | `/mes-dossiers/{id}/demander-corrections` | correction écrite (`champ_concerne` optionnel) |

### Accessibilité (citoyens non lecteurs)
| Méthode | Chemin | Rôle |
|---|---|---|
| POST | `/mes-dossiers/{id}/demander-corrections/audio` | **corriger à la voix** |
| GET | `/mes-dossiers/{id}/document/lecture` | champs du document, libellés et valeurs (✓/✗ ligne par ligne) |
| GET | `/mes-dossiers/{id}/document/lecture/{cle}/audio` | un champ lu à voix haute |
| POST | `/mes-dossiers/{id}/audio` · `/document/audio` | statut / document lus à voix haute |
| GET | `/audio/ui` · `/audio/ui/{cle}` | catalogue audio de l'interface (libellés parlés, cache disque) |
| GET | `/communes/proche?lat=&lng=` | commune la plus proche — pas de liste à lire |

### Notifications
| Méthode | Chemin | Rôle |
|---|---|---|
| GET | `/notifications` | liste (non lues en premier) |
| POST | `/notifications/{id}/lu` · `/notifications/tout-lu` | marquage |
| POST | `/me/appareils` · DELETE `/me/appareils/{jeton}` | jeton FCM de l'appareil |

### Profil
| Méthode | Chemin | Rôle |
|---|---|---|
| GET | `/me` | rôle + commune (réponse légère pour le mobile) |
| POST | `/me/profil-citoyen` | commune, nom, langue — le mobile n'écrit **plus** `profiles` directement |

---

## 6. Ce que le client doit gérer

1. **Reconnexion** avec repli exponentiel, sauf sur 4403 et 4409.
2. **`auth_refresh` avant `exp`** — sinon la connexion est fermée en 4401.
3. **Lecture ordonnée des trames binaires** : une trame = une phrase ; les jouer
   dans l'ordre d'arrivée, et vider la file à la réception d'`interrompu`.
4. **Ignorer les types inconnus** : le protocole s'étend sans casser le client.
5. **Afficher `lent`** plutôt que laisser croire à un blocage (les services ASR
   et TTS peuvent démarrer à froid).
6. **Ne jamais supposer qu'un dossier est envoyé** sans `dossier_mis_a_jour` : la
   confirmation vient du serveur, jamais d'une déduction locale.

---

## 7. Limites connues

- L'ASR et le TTS sont hébergés sur des Spaces Hugging Face : premier appel
  lent au réveil (d'où `lent`).
- Le `turn_id` n'est pas persisté : il vaut pour la durée de la connexion.
- Les migrations 011 à 016 doivent être appliquées (cf.
  `MIGRATIONS_A_APPLIQUER.md`) ; sans 013, le dialogue fonctionne mais l'état
  n'est plus persisté (mode mémoire, signalé dans les journaux).
