# Document de Spécification Fonctionnelle (DSF)

## Conception et mise en œuvre d'un agent vocal intelligent en langue Pulaar pour l'accompagnement et l'assistance des démarches administratives

**Projet :** SUNU-MAIRIE
**Version :** 0.1 — brouillon de travail
**Date :** Août 2026

---

## 1. Introduction

### 1.1 Contexte et problématique

Au Sénégal, une part importante de la population — en particulier en zone rurale et parmi les locuteurs pulaar — rencontre des difficultés d'accès aux services administratifs de base : méconnaissance des procédures, analphabétisme, barrière de la langue (le français étant la langue administrative), éloignement géographique des mairies et tribunaux.

Ces difficultés se traduisent notamment par un défaut d'enregistrement à l'état civil (actes de naissance non déclarés ou déclarés tardivement), avec des conséquences directes sur l'accès à l'école, à la carte d'identité, au passeport, à l'héritage, ou au mariage civil.

### 1.2 Objectifs du système

Le système SUNU-MAIRIE vise à :

- Permettre à un citoyen pulaarophone, y compris analphabète, de **s'informer** sur une démarche administrative par un dialogue vocal en pulaar, sans se déplacer.
- Permettre à ce même citoyen de **déposer une demande** administrative (ex. extrait de naissance) directement depuis son mobile, avec upload des documents justificatifs.
- Permettre à un **consultant** (agent de mairie ou de tribunal) de traiter ces demandes à distance : vérifier les informations et documents collectés, générer le document officiel à partir d'un template, et le valider.
- Permettre à un **administrateur** de superviser et paramétrer le système (communes, templates, utilisateurs).

### 1.3 Périmètre

**Inclus dans le MVP :**
- Démarche pilote : obtention d'un extrait de naissance pour un nouveau-né (les 2 cas : déclaration dans les délais / déclaration tardive).
- Dialogue vocal en pulaar avec le citoyen (mode information + mode dépôt de demande).
- Interface web consultant pour la prévisualisation, l'OCR et la génération de document.
- Suivi de dossier basique.

**Hors périmètre du MVP (évolutions futures) :**
- Autres démarches d'état civil (mariage, décès), urbanisme, services sociaux.
- Canaux WhatsApp / SMS / USSD, API REST pour partenaires ONG.
- Signalement de problèmes locaux.

---

## 2. Acteurs du système

| Acteur | Description | Interface |
|---|---|---|
| **Citoyen** | Usager pulaarophone, potentiellement analphabète, qui s'informe ou dépose une demande administrative | Application mobile (agent vocal) |
| **Consultant** | Agent d'une mairie ou d'un tribunal, rattaché à une commune donnée | Application web (dashboard) |
| **Administrateur** | Gère la configuration globale du système | Application web (back-office) |

---

## 3. Besoins fonctionnels par acteur

### 3.1 Citoyen

- **F1 — Mode information** : dialoguer avec l'agent vocal pour comprendre une démarche (pourquoi, comment, délais, coûts, documents nécessaires), sans engager de dossier.
- **F2 — Mode dépôt de demande** : être guidé pas à pas par l'agent pour constituer et envoyer une demande complète (informations + pièces justificatives), avec des questions adaptées à sa situation (âge de l'enfant, déclaration déjà faite ou non, présence des documents, etc.).
- **F3 — Upload de document** : envoyer une photo d'un document demandé (ex. certificat d'accouchement) directement dans la conversation.
- **F4 — Confirmation orale** : se voir relire par l'agent chaque information saisie avant validation (indispensable pour un usager analphabète).
- **F5 — Suivi de dossier** : connaître l'état de sa demande (reçue / en traitement / validée / prête).
- **F6 — Réception du document final** : recevoir l'extrait de naissance généré sans avoir à se déplacer.

### 3.2 Consultant

- **C1 — Liste des dossiers** : visualiser les demandes envoyées par les citoyens de sa commune.
- **C2 — Prévisualisation** : consulter le détail des informations et documents collectés par l'agent pour un dossier donné.
- **C3 — Extraction OCR** : déclencher l'extraction automatique des données depuis les documents/images envoyés par le citoyen (ex. certificat d'accouchement scanné).
- **C4 — Génération de document** : générer l'extrait de naissance à partir d'un template pré-défini (structuré, ex. XML), en y injectant les données collectées et extraites par OCR.
- **C5 — Vérification et correction** : relire le document généré, corriger si nécessaire les champs mal extraits.
- **C6 — Validation** : valider le document, ce qui déclenche l'envoi/mise à disposition au citoyen.
- **C7 — Rejet / demande de complément** : si le dossier est incomplet, renvoyer une demande de complément au citoyen (ex. document manquant).

### 3.3 Administrateur

- **A1 — Gestion des communes** : ajouter/configurer les mairies et tribunaux couverts.
- **A2 — Gestion des utilisateurs** : créer/désactiver des comptes consultants, leur rattacher une commune.
- **A3 — Gestion des templates** : ajouter/modifier les modèles de documents (structure XML) par type de démarche.
- **A4 — Supervision** : tableau de bord des volumes de dossiers, délais moyens de traitement.

---

## 4. Cas d'usage détaillés

### UC1 — S'informer sur une démarche (mode information)

- **Acteur principal :** Citoyen
- **Déclencheur :** Le citoyen ouvre l'application et exprime une intention informative (ex. « comment obtenir un extrait de naissance pour mon enfant »)
- **Pré-condition :** Aucune
- **Scénario nominal :**
  1. L'agent détecte l'intention (démarche = extrait de naissance) et le mode (information, pas dépôt).
  2. L'agent pose une question de cadrage : *« Quel âge a l'enfant ? »* / *« Sa naissance a-t-elle déjà été déclarée quelque part ? »*
  3. Selon la réponse, l'agent adapte le scénario :
     - Enfant < 1 mois / dans les délais → explique la déclaration directe à la mairie (documents, gratuité, délai).
     - Enfant entre 1 mois et 1 an → explique la déclaration tardive à la mairie.
     - Enfant > 1 an, jamais déclaré → explique le passage obligatoire par le tribunal (jugement d'inscription), les documents, le coût (~4 600 FCFA), le délai (semaines à mois).
  4. L'agent explique **pourquoi** la démarche est nécessaire (conséquences pour l'enfant : école, CNI, passeport).
  5. L'agent liste les documents à réunir et **où** les obtenir (structure de santé, mairie, commissariat).
  6. L'agent demande si le citoyen souhaite maintenant déposer une demande (bascule vers UC2) ou simplement terminer la conversation.
- **Scénarios alternatifs :**
  - Citoyen ne connaît pas l'âge exact de l'enfant → agent demande une estimation ou la date de naissance.
  - Question hors périmètre (autre démarche non couverte par le MVP) → agent l'indique et propose de contacter la mairie directement.

### UC2 — Déposer une demande d'extrait de naissance (mode administratif)

- **Acteur principal :** Citoyen
- **Déclencheur :** Le citoyen confirme vouloir déposer une demande (directement ou après UC1)
- **Pré-condition :** L'agent connaît déjà le cas (dans les délais / tardif / jugement) via le cadrage initial
- **Scénario nominal (cas « dans les délais ») :**
  1. L'agent demande le lieu de naissance (commune) → détermine la mairie destinataire.
  2. L'agent demande si un certificat d'accouchement/de naissance a été délivré → invite à **uploader une photo**.
  3. L'agent demande l'identité du déclarant (nom, CNI — upload possible) et vérifie sa disponibilité.
  4. L'agent demande les informations sur la mère (nom, date de naissance) même en l'absence de sa pièce d'identité.
  5. L'agent demande si les parents sont mariés → si oui, upload du certificat de mariage / livret de famille si disponible ; sinon, note l'absence pour complément ultérieur.
  6. L'agent collecte nom complet et date de naissance exacte de l'enfant.
  7. L'agent **relit oralement** l'ensemble des informations saisies pour confirmation (essentiel pour usager analphabète).
  8. Le citoyen confirme (validation orale, équivalent de l'empreinte digitale dans le scénario physique).
  9. Le dossier est envoyé au consultant de la mairie concernée ; un **numéro de suivi** est communiqué au citoyen.
- **Variante « déclaration tardive » :** mêmes étapes + mention du certificat de non-inscription à demander à la mairie.
- **Variante « jugement requis » (> 1 an) :** le dépôt via l'agent couvre la préparation du dossier (documents, identification de deux témoins) mais la demande manuscrite et le passage au tribunal restent une étape physique obligatoire — l'agent l'indique clairement au citoyen et ne promet pas une délivrance sans déplacement dans ce cas.
- **Post-condition :** Le dossier est visible côté consultant avec statut « reçu ».

### UC3 — Traiter et générer le document (consultant)

- **Acteur principal :** Consultant
- **Déclencheur :** Un nouveau dossier apparaît dans la liste des demandes de sa commune
- **Scénario nominal :**
  1. Le consultant ouvre le dossier et prévisualise les informations et images envoyées par le citoyen.
  2. Le système exécute l'**OCR** sur les documents image (ex. certificat d'accouchement) pour extraire les champs pertinents.
  3. Le consultant vérifie la cohérence entre les données saisies vocalement et les données extraites par OCR.
  4. Le consultant sélectionne le **template** correspondant (extrait de naissance) et déclenche la génération automatique du document (injection des données dans le template structuré).
  5. Le système affiche le document généré pour relecture.
  6. Le consultant corrige si besoin, puis **valide**.
  7. Le document validé est rendu disponible au citoyen (statut « prêt »).
- **Scénario alternatif — dossier incomplet :** le consultant signale le(s) élément(s) manquant(s) ; le citoyen reçoit une notification/relance via l'agent vocal pour compléter.

### UC4 — Recevoir le document (citoyen)

- **Acteur principal :** Citoyen
- **Déclencheur :** Le consultant valide le dossier
- **Scénario nominal :**
  1. Le citoyen est notifié (vocalement/dans l'app) que son document est prêt.
  2. Il peut consulter ou télécharger l'extrait de naissance directement depuis l'application, sans déplacement.

---

## 5. Règles de gestion

| Règle | Détail |
|---|---|
| RG1 | Délai de déclaration directe en mairie : 1 mois après la naissance (jusqu'à 45 jours en zone rurale éloignée selon les sources) |
| RG2 | Entre 1 mois et 1 an : déclaration tardive possible en mairie, avec formalités éventuellement renforcées |
| RG3 | Au-delà d'1 an sans déclaration : passage obligatoire par un jugement d'autorisation d'inscription (tribunal) avant toute inscription en mairie |
| RG4 | La déclaration de naissance est gratuite ; le retrait de l'extrait coûte environ 300 FCFA |
| RG5 | La procédure de jugement d'inscription coûte environ 4 600 FCFA |
| RG6 | Un dossier ne peut être validé par le consultant que si tous les documents obligatoires du cas concerné sont présents ou justifiés (ex. témoins à défaut de certificat médical) |
| RG7 | Toute information collectée oralement doit être relue au citoyen avant validation finale de son dépôt |

---

## 6. Exigences non-fonctionnelles

- **Accessibilité** : dialogue 100% vocal possible côté citoyen (pas de lecture/écriture requise), en langue pulaar.
- **Confidentialité** : les données personnelles et documents d'identité transitent et sont stockés de façon sécurisée ; accès consultant limité aux dossiers de sa commune.
- **Fiabilité de l'OCR** : taux d'erreur d'extraction à mesurer et à corriger obligatoirement par relecture humaine avant validation (pas de génération 100% automatique sans contrôle).
- **Traçabilité** : chaque dossier conserve un historique (dépôt, relance, validation) et un numéro de suivi.
- **Disponibilité multicanal (évolutif)** : mobile en priorité pour le MVP, autres canaux en V2.

---

## 7. Architecture fonctionnelle (vue d'ensemble)

```
[Citoyen - App mobile]
   ↕ (voix pulaar : ASR → NLU/dialogue manager → TTS)
[Agent conversationnel - backend]
   → Détection intention/démarche
   → Collecte guidée des informations (arbre de dialogue adaptatif)
   → Réception uploads (images documents)
   → Création/mise à jour du dossier
        ↓
[Base de données dossiers]
        ↓
[Dashboard Consultant - Web]
   → Prévisualisation dossier
   → Module OCR (extraction données depuis images)
   → Moteur de génération de document (template structuré, ex. XML)
   → Validation / rejet
        ↓
[Citoyen - App mobile] ← document final disponible
```

*(Cette architecture est à affiner avec la stack déjà en place côté SUNU-LANGUES : Whisper fine-tuné pulaar pour l'ASR, NLLB pour la traduction, MMS-TTS pour la synthèse, moteur de dialogue avec RAG.)*

---

## 8. Modèle de données (esquisse — à valider)

**Entités principales :**
- `Citoyen` (identité, contact, commune)
- `Dossier` (type de démarche, statut, cas légal — dans les délais / tardif / jugement, historique)
- `Document` (type, fichier image source, données OCR extraites, document généré)
- `Commune` (mairie/tribunal rattaché)
- `Consultant` (identité, commune rattachée)
- `Template` (type de démarche, structure XML)

---

## 9. Annexes

### 9.1 Glossaire

- **DSF** : Document de Spécification Fonctionnelle
- **OCR** : Optical Character Recognition (reconnaissance optique de caractères)
- **ASR** : Automatic Speech Recognition
- **TTS** : Text-to-Speech
- **UC** : Use Case (cas d'usage)

### 9.2 Scénarios de dialogue de référence

Les scénarios détaillés suivants ont servi de base à la rédaction des cas d'usage ci-dessus et peuvent être conservés en annexe complète du DSF pour illustrer le ton et le niveau de détail attendu de l'agent :
- Dialogue citoyen analphabète / agent mairie (dépôt physique, cas « dans les délais »)
- Dialogue citoyen / spécialiste (mode information, cas « jugement requis », enfant de 3 ans)
- Dialogue citoyen / spécialiste (mode information, cas « dans les délais », enfant de 10 jours)

*(à joindre en pièce jointe séparée ou en annexe complète selon le format final exigé par votre encadrant)*

---

## 10. Points à trancher avec votre encadrant

- Le passage obligatoire par le tribunal (cas > 1 an) reste-t-il **hors du flux 100% dématérialisé**, ou le système doit-il aussi couvrir la prise de rendez-vous/l'accompagnement pour ce cas ?
- Quel niveau de validation humaine minimal est exigé avant la délivrance d'un acte d'état civil généré automatiquement (question de valeur légale du document) ?
- Le consultant doit-il pouvoir traiter uniquement les dossiers de sa commune, ou existe-t-il un rôle superviseur multi-communes ?
