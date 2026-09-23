# TODO — Backend v3 (temps réel mobile + web consultant/admin)

Liste de travail suivie pendant l'implémentation. Chaque tâche a : **pourquoi**,
**quoi**, **vérification**. Cochée seulement une fois la vérification passée.

Principes directeurs (décisions d'architecture) :

1. **Un seul moteur de dialogue, indépendant du transport** (`temps_reel/moteur.py`) :
   le WS historique `/ws/{session_id}` (app mobile actuelle) et le nouveau
   `/ws/v2` sont deux adaptateurs du même moteur. Les deux envoient le même
   sur-ensemble de messages (le mobile actuel ignore déjà les types inconnus).
2. **État du dialogue persisté** (`dialogue_sessions`) + cache mémoire + verrou
   par session ; une session appartient à UN citoyen ; démarche terminée ou
   bloquée ⇒ session close, la suivante repart proprement.
3. **Tour en deux phases** : A « comprendre et décider » (ASR, moteur,
   persistance — jamais interrompue) puis B « parler » (traduction pulaar + TTS
   — interruptible : barge-in).
4. **Transitions de statut centralisées** (`services/evenements.py`) :
   historique + notifications + push temps réel citoyen + FCM, partagés web/mobile.
5. **Dégradation honnête** : migration absente ⇒ 503 explicite ou mode mémoire,
   jamais de crash ni de donnée inventée.

---

## Phase 0 — Préparation
- [x] 0.1 Lire tout le code concerné (main.py WS, slot_controller, dialogue_engine, repos, migrations 001-010, tts/asr)
- [x] 0.2 Outillage tests : `pytest` dans le venv, `requirements-dev.txt`, dossier `tests/unit/` (tests SANS réseau)

## Phase 1 — Sécurité critique (bloquant avant tout le reste)
- [x] 1.1 RG7 : détection du « oui » avec gestion de la négation/correction (« non ce n'est pas correct », « oui mais… ») — `temps_reel/intentions.py` + tests
- [x] 1.2 Supprimer `GET /sessions` ; `/chat` : historique cloisonné par utilisateur
- [x] 1.3 JWT : algorithmes asymétriques fixés (plus d'`alg` lu dans l'en-tête), refetch JWKS limité dans le temps, appel non bloquant, `exp` exposé — tests
- [x] 1.4 Migration 011 : `profiles` protégé (trigger : rôle non modifiable hors service_role, commune d'un agent non modifiable ; RLS propriétaire) + `POST /me/profil-citoyen` pour que le mobile n'écrive plus `profiles`
- [x] 1.5 Garde-fous de statut consultant (lecture seule `finalise`/`bloque`, `generer` refusé hors statuts autorisés) — 409 explicites

## Phase 2 — Fondations partagées
- [x] 2.1 `services/journal.py` : logger applicatif sans données personnelles (longueurs, ids — jamais de transcription)
- [x] 2.2 `services/llm.py` : client OpenRouter mutualisé (structuré, texte, flux) avec timeouts
- [x] 2.3 `services/db.py` : exécution des appels Supabase synchrones hors event loop + détection « migration non appliquée »
- [x] 2.4 `services/rag.py` : recherche démarches (sémantique → mot-clé) exécutée dans un thread
- [x] 2.5 Migration 012 : `dossier_evenements`, `notes_internes`, colonnes profils/dossiers/templates (web v3)
- [x] 2.6 `services/evenements.py` : `transition_statut()` unique (update + événement + notifications + push) et `ajouter_evenement()`

## Phase 3 — Temps réel & dialogue mobile (cœur)
- [x] 3.1 Migration 013 : `dialogue_sessions` (état persistant, propriété citoyen, statut active/close)
- [x] 3.2 `temps_reel/etat.py` : état de session typé (sérialisation JSON sûre, sets ↔ listes) + tests
- [x] 3.3 `temps_reel/sessions.py` : magasin de sessions (cache + base + verrou par session + propriété + clôture/rotation)
- [x] 3.4 `temps_reel/moteur.py` : un tour de dialogue (information → bascule → collecte → RG7 → terminé/bloqué) extrait de main.py, sans transport — tests avec faux LLM
- [x] 3.5 `temps_reel/audio.py` : détection du format (wav/ogg/m4a/webm), conversion ffmpeg → WAV 16 kHz mono, durée max — tests
- [x] 3.6 `temps_reel/parole.py` : traduction pulaar en flux + TTS phrase par phrase, **annulable** (barge-in), sans fuite de tâches
- [x] 3.7 `temps_reel/connexion.py` : gestionnaire de connexion commun v1/v2 (lecteur permanent + file de tours, phases A/B, interruption, ping, lenteur signalée, délais bornés, persistance des messages avec `message_id`)
- [x] 3.8 `temps_reel/registre.py` : connexions actives par session et par citoyen ; relance après upload ; push `dossier_mis_a_jour`
- [x] 3.9 Routeur WS : `/ws/v2` (auth par 1er message, `auth_refresh`, `nouvelle_conversation`, `texte`, `interrupt`, codes de fermeture) + `/ws/{session_id}` rétro-compatible branché sur le même moteur ; retrait de l'ancienne boucle de main.py
- [x] 3.10 REST conversations : `POST /conversations` (nouvelle démarche), `GET /conversations/active`
- [x] 3.11 Tests d'intégration WS (TestClient + dépendances simulées) : auth, propriété, reprise d'upload, interruption, rotation après RG7

## Phase 4 — Suivi citoyen, notifications, accessibilité
- [x] 4.1 Migration 014 : `notifications`, `appareils` (jetons FCM)
- [x] 4.2 `services/notifications.py` + `services/push_fcm.py` (FCM HTTP v1, no-op propre si non configuré)
- [x] 4.3 Endpoints `GET /notifications`, `POST /notifications/{id}/lu`, `POST /notifications/tout-lu`, `POST/DELETE /me/appareils`
- [x] 4.4 Contrôle qualité photo à l'upload (flou, sombre, trop petite) + consigne vocale poussée dans le dialogue — tests images synthétiques
- [x] 4.5 Corrections à la voix : `POST /mes-dossiers/{id}/demander-corrections/audio` + `champ_concerne` optionnel
- [x] 4.6 Lecture structurée du document : `GET /mes-dossiers/{id}/document/lecture` (champs, libellés, valeurs) pour ✓/✗ par ligne
- [x] 4.7 Catalogue audio d'interface : `GET /audio/ui`, `GET /audio/ui/{cle}` (cache disque) + script de pré-génération
- [x] 4.8 Migration 015 : coordonnées des communes + `GET /communes/proche?lat=&lng=`

## Phase 5 — Web consultant/admin (README-BACKEND-WEB-V3)
- [x] 5.1 Profil : `GET /me` enrichi, `PATCH /me`, `PATCH /me/preferences`, `POST /me/mot-de-passe-modifie`, `GET /me/activite`
- [x] 5.2 Consultant : `GET …/remarques`, `GET/POST …/notes`, `GET …/historique`
- [x] 5.3 Admin dossiers : `GET /admin/dossiers`, `GET /admin/dossiers/{id}`, `POST …/debloquer`, historique/notes admin
- [x] 5.4 Admin comptes : consultants enrichis, `nom_complet` à la création + drapeau mot de passe temporaire, `POST /admin/consultants/{id}/reinitialiser-mot-de-passe`
- [x] 5.5 Supervision enrichie (`par_commune`, `evolution_30_jours`, `motif_blocage`) + migration 016 `journal_audit` + `GET /admin/journal`
- [x] 5.6 Branchement des transitions existantes de main.py sur `transition_statut()` (recu, en_traitement, genere, envoi citoyen, finalise, corrections, bloque)

## Phase 6 — Qualité, documentation, vérification finale
- [x] 6.1 `lifespan` (remplace `on_event`), purge des sessions inactives
- [x] 6.2 CI : job tests unitaires
- [x] 6.3 `README-TEMPS-REEL-MOBILE.md` : protocole WS v2 complet + endpoints mobile
- [x] 6.4 `MIGRATIONS_A_APPLIQUER.md` : ordre, contenu, vérifications SQL
- [x] 6.5 Vérification finale : `pytest`, `python -c "import main"`, compilation de tous les fichiers

---

## Journal de décisions (au fil de l'eau)

### Le paquet `realtime` renommé `temps_reel`
Le premier `pytest` a échoué sur
`ImportError: cannot import name 'AuthorizationError' from 'realtime'` : le
paquet que je venais de créer **masquait** le paquet PyPI `realtime`, dont
dépend `supabase`. Renommé en `temps_reel` (cohérent avec le reste du code,
écrit en français). Leçon : vérifier qu'un nom de paquet local n'existe pas déjà
dans les dépendances installées.

### Vérifier une route en l'appelant, pas en inspectant `app.routes`
J'ai d'abord conclu que `/me/profil-citoyen` n'existait pas, à partir de
`app.routes[].path` : FastAPI 0.141 enregistre les routeurs inclus comme
`_IncludedRouter`, dont les chemins n'apparaissent pas ainsi. La route
fonctionnait. Depuis, toute route nouvelle est vérifiée par un **appel réel**
(401 attendu sans jeton = route servie ; 404 = route absente) —
`scratchpad/verif_routes_v3.py`, 17 routes v3 contrôlées.

### Bug métier trouvé en lisant le code : la correction RG7 n'était jamais appliquée
Un « non » à la relecture rouvrait la collecte, mais **tous les slots étaient
déjà remplis** : plus aucune question n'était posée, le même récapitulatif
revenait, et le dossier finissait bloqué au bout de 3 tours sans que la
correction demandée soit prise en compte. Corrigé dans `temps_reel/moteur.py` :
la correction est soit appliquée après validation de la nouvelle valeur, soit le
slot est vidé pour être redemandé.

### 401 plutôt que 422 quand l'en-tête `Authorization` manque
`Header(...)` obligatoire fait répondre 422 à FastAPI — le front web
l'interprétait comme une erreur de requête, pas comme une session expirée.
Partout : `Optional[str] = Header(None)` + 401 explicite.

### Scripts de test hérités volontairement cassés
Les scripts `test_*.py` de la racine qui manipulaient `dossier_sessions` ou
`active_websockets` (état global supprimé de `main.py`) ne fonctionnent plus.
C'est assumé : ces scripts appelaient de vrais services distants et ne sont pas
des tests automatisés. La suite qui fait foi est `tests/unit/` (sans réseau,
lancée en CI).

### Une écriture d'audit ne fait jamais échouer l'action métier
`services/audit.py` avale ses propres erreurs (table absente comprise) et se
contente d'un avertissement une seule fois. Un journal indisponible ne doit
jamais empêcher de débloquer un dossier.

### Ce qui reste à faire hors code
Les migrations **011 à 016 ne sont pas appliquées** (cf.
`MIGRATIONS_A_APPLIQUER.md`). La 011 empêche l'application mobile d'écrire
`profiles` directement : vérifier que la version déployée utilise bien
`POST /me/profil-citoyen` avant de l'appliquer en production. Les coordonnées des
communes (migration 015) doivent être saisies depuis une source vérifiable — pas
inventées.
