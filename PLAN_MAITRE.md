# Plan maître — SUNU-MAIRIE

Ce document est **l'ordre d'exécution**. Il ne remplace pas les listes détaillées :
il dit dans quel ordre les traiter, et pourquoi.

| Liste détaillée | Portée |
|---|---|
| `backend-agent/TODO_BACKEND_V3.md` | Backend v3 — terminé, migrations appliquées |
| `backend-agent/TODO_DEMARCHES.md` | Démarches paramétrables et pulaar validé |
| `sunu_langues_mobile/TODO_MOBILE_V3.md` | Refonte mobile et temps réel |
| `sunu_langues_mobile/TODO_AVATAR.md` | Avatar vivant |

## Règles de travail

1. **Rien n'est coché sans vérification** : analyse statique propre, tests au vert, et
   pour tout ce qui se voit ou s'entend, essai réel sur téléphone.
2. **Un correctif de bug s'accompagne du test qui l'aurait attrapé**, et ce test est
   vérifié en réintroduisant le bug.
3. **Aucune règle de droit n'est codée sans source**, et toute règle non confirmée par un
   officier d'état civil est signalée dans le code comme une hypothèse.
4. **Aucune donnée de santé n'entre dans le système** (cf. certificat de causes de décès).
5. On livre par étapes utilisables : à la fin de chacune, quelque chose marche mieux pour
   un citoyen ou pour un agent.

## Ce qui dépend de vous

| Ce qu'il me faut | Bloque | État |
|---|---|---|
| Traductions pulaar validées (par vous) | Étapes 1 et 3 | ⏳ |
| Un acte de décès délivré par une mairie (le certificat médical reçu n'est PAS l'acte) | Étape 5.5 | ⏳ |
| Confirmation des règles par un officier d'état civil | Mise en service de l'étape 5 | ⏳ |
| Accord pour les gestes des bras de l'avatar | Étape 6 | ⏳ |
| Accord pour embarquer Three.js (téléchargement) | Étape 6 | ⏳ |
| Adresse du serveur backend joignable depuis un téléphone | Étape 0 | ⏳ |
| Application de la migration 017 (conditions des démarches) | Suite de l'étape 2 | ✅ |
| Application de la migration 018 + vérification de la bascule | Étape 3 | ✅ |
| Application de la migration 019 (versions des démarches) | Étape 4 | ⏳ |
| Application de la migration 020 (phrases et relances) | Étape 3 | ⏳ |
| Application de la migration 021 (gabarits) | Étape 3 | ⏳ |
| Application de la migration 022 (invalidation des audios) | Étape 3 | ⏳ |
| Lancement de `scripts/pregenerer_audio.py` après la relecture | Fin de l'étape 3 | ⏳ |
| Application des migrations 023 et 024 (atelier) | Étape 4.2 | ⏳ |
| Migrations 025 et 026, publication, puis pulaar des 4 phrases dans l'atelier | Étape 5.1 | ⏳ |
| Migration 027 puis relecture des règles du mariage par un officier | Étape 5.2 | ⏳ |
| Migration 028 puis relecture des règles du décès par un officier | Étape 5.3 | ⏳ |
| Migration 029 (brouillons pulaar) puis relecture des ~200 phrases à l'atelier | Étapes 5.1 à 5.3 | ⏳ |
| Réimport de `phrases.tsv` réparé (3 lignes décalées) | Urgent | ⏳ |
| Relecture des noms de mois en pulaar | Fin de l'étape 3 | ⏳ |
| Relecture des 53 phrases pulaar | Fin de l'étape 3 | 🔸 importées, à écouter dans `/admin/atelier` |

---

# Ordre d'exécution

## Étape 0 — Correctifs bloquants

**Pourquoi en premier :** ce sont des choses cassées aujourd'hui.

- [x] 0.1 **L'inscription n'enregistre plus la commune.** La migration 011, que vous avez
      appliquée, interdit au mobile d'écrire `profiles`. `auth_service.dart` le fait encore
      et masque l'échec : tout nouveau citoyen reste en commune « National », donc ses
      dossiers partent à la mauvaise mairie. Passer par `POST /me/profil-citoyen`
- [x] 0.2 Cas de la confirmation par e-mail : sans session, pas de jeton — envoyer alors la
      commune à la première connexion réussie
- [x] 0.3 **Adresse du backend configurable** (`.env`) au lieu de `127.0.0.1` figé, sinon
      l'application ne fonctionne sur aucun téléphone réel
- [ ] 0.4 Essai de bout en bout sur téléphone : inscription, dialogue, dépôt de photo
      **(à faire par vous — voir les deux actions ci-dessous)**
      - [ ] Ajouter `BACKEND_URL=http://<ip-de-votre-machine>:8000` dans le `.env` du mobile
      - [ ] Démarrer le backend et vérifier qu'un compte créé arrive dans la bonne commune

**Vérification :** un compte créé depuis un téléphone apparaît dans la bonne commune côté
web admin.

## Étape 1 — Pulaar : le gain immédiat

**Pourquoi maintenant :** quelques heures de travail, effet audible tout de suite, sans
rien restructurer.

- [x] 1.1 Remplacer les deux exemples du prompt de traduction, **aujourd'hui écrits en
      français** alors qu'ils sont donnés au modèle comme du pulaar (`prompts.py`)
- [x] 1.2 Glossaire des termes administratifs, injecté à chaque traduction
      (`services/pulaar.py`) — 82 entrées, dont 50 tirées du corpus de traduction
      `RESOURCES/MODEL TRADUCTION/dataset_ful_fr_ameliorer.jsonl` ;
      **70 restent à valider par vous**
- [x] 1.3 Orthographe de substitution pour les mots que la synthèse vocale prononce mal,
      appliquée dans `tts_client.synthesize_remote` (donc dialogue ET narration)
- [x] 1.4 Écoute comparative avant / après, par vous, sur cinq phrases types —
      **jugée concluante le 2026-09-19**, d'où l'élargissement du glossaire ci-dessus
- [ ] 1.5 Deuxième écoute sur les trois phrases ajoutées, qui couvrent les nouveaux
      termes **(à faire par vous : `python scripts/ecoute_comparative_pulaar.py`)**

**Vérification :** vous jugez le pulaar meilleur à l'oreille. Sinon, on ne continue pas.

## Étape 2 — Modèle de données des démarches

**Pourquoi avant les phrases figées :** le pulaar validé se range dans ce modèle. Le
construire après obligerait à tout déplacer.

- [x] 2.1 Représenter les **quatre formes de conditions** rencontrées dans les règles
      réelles : champ obligatoire ; **délai qui interrompt la démarche** (six mois pour le
      mariage, un an pour le décès) ; **condition croisée entre deux champs** (la polygamie
      interdit la communauté de biens) ; **alternative entre deux pièces** (certificat
      médical **ou** deux témoins)
      — `services/conditions.py` (langage de conditions à trois valeurs),
      `services/regles_demarche.py` (effets `bloquer` / `interdire`),
      migration `017_conditions_demarches.sql`. **Migration à appliquer.**
- [x] 2.2 Migrations : colonnes pulaar et audio, messages des documents, règles de cas
      — migration `018_demarches_pilotees_par_la_donnee.sql`. **Migration à appliquer.**
- [x] 2.3 Sortir du code ce qui y est figé : types de documents, slots initiaux, bascule en
      mode administratif, règle des cas légaux (`determiner_cas_legal`)
      — point d'accès unique `services/demarche.py`, avec repli sur les anciennes
      constantes quand la base est injoignable
- [x] 2.4 Version d'une démarche figée pour les dialogues déjà commencés
      — migration `019_versions_demarches.sql`, publication par
      `scripts/publier_demarche.py`. **Migration à appliquer.**
- [x] 2.5 Tests : une démarche fictive pilote le moteur de bout en bout
      (`tests/unit/test_demarche_conditions.py`) — à compléter quand 2.3 sortira du code
      les dernières constantes

**Vérification :** l'extrait de naissance fonctionne exactement comme avant, sans aucune
constante en dur le concernant.

## Étape 3 — Phrases figées et audio pré-généré

**Pourquoi ici :** c'est le vrai remède au pulaar incohérent.

- [ ] 3.1 Toutes les questions et messages de l'extrait de naissance reçoivent un pulaar
      validé par vous — **atelier prêt** (`scripts/atelier_pulaar.py`), ~52 phrases,
      **la relecture vous revient**
- [x] 3.0 Les RELANCES sortent du modèle : elles étaient improvisées à chaque fois, donc
      retraduites, au moment où le citoyen comprend le moins (migration 020)
- [x] 3.2 Gabarits à trous, et énoncé des dates et des nombres en pulaar, sans LLM
      — `services/pulaar_nombres.py`, `services/gabarits.py`, migration 021.
      **Migration à appliquer.**
- [x] 3.3 `parole.py` : si la phrase a un pulaar validé, aucun appel au modèle
- [x] 3.4 Pré-génération des audios, invalidation quand le texte change
      — `services/catalogue_audio.cle_phrase` : le fichier est retrouvé par l'EMPREINTE
      du texte pulaar, donc un texte corrigé n'a plus d'audio et repart à la synthèse.
      Script `scripts/pregenerer_audio.py`, migration 022. **Migration à appliquer.**
- [x] 3.5 Repli explicite : phrase sans pulaar validé → traduction, et signalement à valider
      (`services/phrases.signalements()`)

**Vérification :** un dialogue complet d'extrait de naissance, sans un seul appel de
traduction, écouté par vous du début à la fin.

## Étape 4 — Interface admin : éditeur et atelier

- [x] 4.1 Éditeur de démarche : séquence, champs, documents, cas, récapitulatif
      — `/admin/demarches`, service `services/editeur.py`, routeur `routers/demarches.py`.
      Toute écriture est vérifiée sur la démarche telle qu'elle SERAIT : une
      modification qui casserait le dialogue est refusée (409) avec l'endroit fautif.
      Aucune migration.
- [x] 4.2 Atelier pulaar : liste des phrases, saisie, écoute, validation, historique
      — `/admin/atelier`, service `services/atelier.py`, routeur `routers/atelier.py`.
      L'écoute précède la validation : le bouton reste inactif tant que la phrase
      n'a pas été entendue. Migrations 023 (historique) et 024 (relecture par
      phrase et non par ligne). **Migrations à appliquer.**
- [x] 4.3 Simulateur : jouer une démarche entière avant publication
      — onglet « Simulateur » de l'éditeur, `services/simulateur.py`. Emprunte les
      MÊMES fonctions que le dialogue réel (séquence, validation, cas, récapitulatif).
      Ne simule PAS l'extraction : la valeur est donnée, pas comprise. Aucune migration.
- [x] 4.4 Brouillon et publication — `services/brouillon.py`, panneau « Brouillon » de
      l'éditeur. Les tables vivantes SONT le brouillon : un dialogue lit la version
      publiée figée (étape 2.4). Écarts listés, publication refusée si rien n'a changé
      ou si un problème bloquant subsiste, abandon (retour à la version publiée).
      Récapitulatif désormais figé dans la version (il s'entendait tout de suite).
      Publication en lecture stricte : une panne réseau ne fige plus une démarche vide.
      Le simulateur joue le brouillon ou la version en service. Aucune migration.
      **À faire : publier une fois (v3) pour figer le récapitulatif.**

**Vérification :** vous modifiez une question depuis le web, et le changement s'entend dans
l'application sans redéploiement.

## Étape 5 — Les trois démarches

- [ ] 5.1 Extrait de naissance : corriger les quatre écarts vus sur l'acte de Tambacounda
      - [x] arrondissement facultatif (XSD, modèle, générateur, impression)
      - [x] sexe stocké M/F, imprimé MASCULIN / FÉMININ ; accepte « masculin », « fille »…
      - [ ] numéro d'acte à dix-neuf chiffres : **attend l'officier d'état civil**, rien inventé
      - [x] sexe demandé par le dialogue (migration 025, champ « choix »), pré-remplit le
            formulaire du consultant, qui garde la priorité
      - [x] option C retenue : noms complets gardés (le consultant sépare prénom et nom) ;
            « Êtes-vous le père de l'enfant ? », nom du père si non (facultatif) ;
            question sur le mariage et récapitulatif rendus neutres (migration 026)
      - `date_naissance_mere` gardée : elle sert à vérifier que la mère est née avant
        l'enfant
- [x] 5.2 Constatation de mariage — migration 027 : 24 questions (les deux époux, le
      mariage, deux témoins), 7 pièces, récapitulatif, et deux règles transverses :
      au-delà de six mois la démarche s'arrête et oriente vers le tribunal ; la
      communauté des biens est refusée avec une option polygamique. Dispense d'âge
      demandée seulement si l'un des époux était mineur.
      Le dialogue vocal démarrait TOUJOURS l'extrait de naissance : la bascule choisit
      maintenant la démarche demandée (`demarche_proposee`).
      **Toutes les règles sont marquées « hypothèse » : à confirmer par un officier
      d'état civil avant mise en service.**
      Reste pour 5.5 : le document de sortie et les champs du formulaire consultant
      pour les nouvelles pièces.
- [x] 5.3 Déclaration de décès — migration 028 : 24 questions (le défunt, le décès, le
      déclarant, et deux témoins quand il n'y a pas de certificat médical), 8 pièces,
      récapitulatif. Le procès-verbal de police est exigé d'après la case « obstacle
      médico-légal » cochée par le médecin, jamais d'après une question au citoyen sur
      les circonstances. Au-delà d'un an : arrêt et orientation vers le tribunal.
      Nouvelle règle de validation `apres:` (une date de décès antérieure à la naissance
      était acceptée).
      **Règles marquées « hypothèse » : à confirmer par un officier d'état civil.**
- [x] 5.4 **Protection du certificat de causes de décès** — `services/partie_confidentielle.py` :
      la consigne de photo dit de n'envoyer que la partie haute détachée ; la partie basse
      est reconnue et REFUSÉE avant tout enregistrement, sans échappatoire (`forcer` ne
      contourne pas) ; quand la lecture est impossible, on refuse plutôt que d'enregistrer
      sans savoir ; aucun champ de cause n'existe dans la démarche ; rien de ce qui est lu
      ne sort de la fonction, ni vers l'API ni vers le journal.
- [ ] 5.5 Documents générés : modèle par démarche, correspondance des champs
      **En attente de vos modèles réels** (acte de décès, certificat de mariage constaté) :
      sans eux, impossible d'écrire les XSD sans inventer des mentions légales.
      Décidé : un XSD par démarche, comme pour la naissance (validation stricte).
      Fait en attendant : la génération REFUSE une démarche sans modèle (elle
      fabriquait un extrait de naissance à partir d'un dossier de mariage).
      Restera à faire : lire la table `templates` (l'écran « Modèles » n'est
      branché sur rien), enregistrer le document sous le nom de sa démarche,
      formulaires consultant des nouvelles pièces, règles de l'assistant par démarche.
- [ ] 5.6 Contenu du mode information pour les trois, avec coûts et délais réels

**Vérification :** trois dossiers complets, du dialogue au document, relus par un officier
d'état civil.

## Étape 6 — Avatar vivant

Indépendant des étapes 2 à 5 : peut passer avant si vous préférez du visible plus tôt.

- [ ] 6.1 Nettoyage du moteur actuel (A1)
- [ ] 6.2 Moteur en couches : activité, émotion, réactions, regard (A2, A3)
- [ ] 6.3 Directeur côté Flutter et ses tests (A4)
- [ ] 6.4 Mode écriture et écoute naturelle (A5, A6)
- [ ] 6.5 Bouche synchronisée sur le son réel (A7)
- [ ] 6.6 Performance sur téléphone modeste (A8)

## Étape 7 — Accessibilité et confort restants

- [ ] 7.1 Catalogue audio d'interface avec cache disque (M3.1)
- [ ] 7.2 Commune par position GPS (M3.5) — demande un paquet supplémentaire
- [ ] 7.3 Notifications (M4.6) — demande Firebase
- [ ] 7.4 Tests widget des composants critiques et contrôle d'accessibilité (M5.2, M5.3)

## Étape 8 — Vérification finale

- [ ] 8.1 Suites de tests complètes, backend et mobile
- [ ] 8.2 Essai terrain avec un citoyen non lecteur, en pulaar, du début à la fin
- [ ] 8.3 Revue de sécurité : clés, données de santé, journal d'audit
- [ ] 8.4 Documentation à jour

---

## Jalons

| Jalon | Ce qui est vrai à ce moment-là |
|---|---|
| J1 — fin étape 0 | L'application fonctionne sur un vrai téléphone, commune comprise |
| J2 — fin étape 1 | Le pulaar est meilleur, sans changement d'architecture |
| J3 — fin étape 3 | Le dialogue d'extrait de naissance est en pulaar validé, sans LLM |
| J4 — fin étape 4 | Vous modifiez une démarche sans développeur |
| J5 — fin étape 5 | Trois démarches réelles fonctionnent |
| J6 — fin étape 6 | L'avatar réagit comme un interlocuteur |

## Risques

- **Le temps de validation du pulaar** est le vrai chemin critique : environ 150 à 200
  phrases pour les trois démarches. Tout le reste attend derrière.
- **Les règles de droit non confirmées** : une condition fausse produit un acte invalide.
- **Le certificat de causes de décès** : le collecter par erreur serait une faute grave.
- **Le numéro d'acte à dix-neuf chiffres** reste une hypothèse depuis le début du projet.

## Abandonné

- **Changer de fournisseur LLM depuis l'admin.** Ce n'était pas la cause du problème de
  pulaar : la cause est que des phrases connues d'avance sont retraduites à chaque
  conversation. Les étapes 1 à 3 y répondent directement.
