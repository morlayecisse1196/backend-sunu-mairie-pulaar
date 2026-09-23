# Exemples de dialogues Bot ↔ Citoyen — SUNU-MAIRIE

Ce document sert de référence pour le développement de l'agent conversationnel (dialogue manager, NLU, gestion des slots). Chaque tour de dialogue important est annoté avec l'intention détectée, les entités extraites et l'état du dossier, pour faciliter la traduction en code (prompts, machine à états, ou schéma de slots).

Démarche couverte : **extrait de naissance pour un nouveau-né**.

---

## PARTIE 1 — MODE INFORMATIONNEL

Le citoyen veut comprendre une démarche sans déposer de dossier. Le bot doit détecter le mode (`mode = information`), adapter sa réponse selon la situation, puis proposer de basculer vers le mode administratif s'il le souhaite.

### Exemple 1.1 — Naissance récente (cas « dans les délais »)

```
Citoyen : Bonjour, je voudrais savoir comment faire pour avoir l'extrait de
          naissance de mon fils.

  → NLU: intent = demander_information
         entity = type_demarche: extrait_naissance
         mode   = information (aucune intention explicite de dépôt)

Bot     : Bonjour ! Je peux vous expliquer ça. Dites-moi d'abord :
          quel âge a votre fils ?

  → slot attendu: age_enfant

Citoyen : Il est né il y a une semaine.

  → NLU: entity = age_enfant: {valeur: 7, unite: jours}
         règle appliquée: age < 30 jours → cas = "dans_les_delais"

Bot     : Très bien, vous êtes largement dans les délais. Vous avez un mois
          après la naissance pour déclarer votre fils, gratuitement, à la
          mairie du lieu où il est né.

  → action: afficher_info(cas="dans_les_delais")

Bot     : Pour cette démarche, il vous faudra :
          - le certificat de naissance délivré par l'hôpital ou la
            maternité
          - votre carte d'identité
          - votre livret de famille, si vous en avez déjà un
          Voulez-vous que je vous aide à préparer et envoyer la demande
          maintenant, ou souhaitez-vous juste avoir l'information ?

  → slot attendu: souhaite_deposer (bool)

Citoyen : Juste l'information pour l'instant, merci.

  → NLU: intent = fin_conversation (mode=information confirmé, pas de bascule)

Bot     : Avec plaisir. N'attendez pas trop, vous avez encore trois
          semaines. Bonne journée !
```

**Points d'implémentation :**
- `age_enfant` doit accepter des formats libres (jours, semaines, mois, "il y a une semaine") → normalisation nécessaire côté NLU/entity extraction.
- La réponse du bot est **générée à partir d'un cas** (`dans_les_delais` / `tardif` / `jugement_requis`), pas d'un script figé — prévoir un module de règles (RG1/RG2/RG3 du DSF) qui retourne le cas à partir de `age_enfant`.

---

### Exemple 1.2 — Enfant jamais déclaré, plus d'un an (cas « jugement requis »)

```
Citoyen : Mon petit-fils n'a jamais été déclaré, il a 3 ans, qu'est-ce que
          je dois faire ?

  → NLU: intent = demander_information
         entity = type_demarche: extrait_naissance
         entity = age_enfant: {valeur: 3, unite: annees}
         entity = declaration_existante: false
         règle appliquée: age > 1 an ET jamais déclaré → cas = "jugement_requis"

Bot     : D'accord. Dans ce cas, il faut d'abord passer par le tribunal
          avant d'aller à la mairie, parce que le délai d'un an est dépassé.

  → action: afficher_info(cas="jugement_requis")

Bot     : Sans cet acte, votre petit-fils ne pourra pas être inscrit à
          l'école plus tard, ni avoir de carte d'identité. C'est pour ça
          que c'est important de régulariser, même si ça prend un peu plus
          de temps.

Bot     : Voici ce qu'il faut réunir :
          - un certificat médical de naissance, ou à défaut deux témoins
            qui ont assisté à la naissance
          - un certificat de non-inscription, à demander à la mairie
          - les cartes d'identité des parents ou du tuteur
          - le livret de famille ou certificat de mariage, si les parents
            sont mariés
          Il faudra aussi déposer une demande manuscrite au tribunal, avec
          deux témoins.

Bot     : Côté délais et coûts : le jugement coûte environ 4 600 FCFA et
          peut prendre de quelques semaines à quelques mois selon le
          tribunal. Une fois le jugement obtenu, l'extrait lui-même coûte
          environ 300 FCFA et est prêt en quelques jours.

Bot     : Je peux vous aider à préparer les informations pour ce dossier
          dès maintenant dans l'application, mais sachez que le dépôt de
          la demande manuscrite au tribunal reste une étape que vous devrez
          faire en personne. Voulez-vous commencer à préparer le dossier ?

  → IMPORTANT: ne jamais laisser croire que ce cas est 100% dématérialisable
    (cf. DSF §10 "points à trancher" — à confirmer avec l'encadrant)

Citoyen : Oui, je veux bien commencer.

  → NLU: intent = accepter_bascule_mode
         action: transition mode = information → mode = administratif
                 (cas = "jugement_requis" déjà connu, pas de nouveau cadrage)
```

**Points d'implémentation :**
- Ce cas illustre une **limite fonctionnelle assumée** : le bot doit être honnête sur ce qu'il peut faire dématérialiser (préparation du dossier) et ce qui reste physique (dépôt au greffe). Le contenu du message ne doit jamais varier sur ce point, quel que soit le prompt — à traiter comme une règle métier dure, pas une suggestion du LLM.
- La transition `information → administratif` doit **réutiliser les slots déjà remplis** (âge, cas légal) pour ne pas reposer les mêmes questions.

---

### Exemple 1.3 — Naissance entre 1 mois et 1 an (cas « tardif »)

```
Citoyen : Ma fille a 4 mois, je n'ai pas encore fait les papiers, c'est
          grave ?

  → NLU: intent = demander_information
         entity = type_demarche: extrait_naissance
         entity = age_enfant: {valeur: 4, unite: mois}
         entity = declaration_existante: false
         règle appliquée: 1 mois < age <= 1 an → cas = "tardif"

Bot     : Ce n'est pas grave, mais il ne faut plus trop attendre. Vous
          pouvez encore déclarer votre fille directement à la mairie,
          c'est ce qu'on appelle une déclaration tardive. Passé un an,
          par contre, il faudrait passer par le tribunal, ce qui est plus
          long.

  → action: afficher_info(cas="tardif")
    ATTENTION: message doit toujours mentionner l'échéance des 12 mois
    pour créer l'incitation à agir vite (cf. ton du DSF §5 RG2)

Bot     : Les documents sont les mêmes que pour une déclaration normale :
          certificat de naissance ou attestation de la sage-femme, votre
          carte d'identité, et le livret de famille si vous en avez un.
          Certaines mairies demandent en plus une petite justification du
          retard, mais ce n'est pas systématique — ça dépend de la mairie.

  → NOTE dev: cette variabilité inter-mairie doit rester un texte
    d'avertissement générique ("selon la mairie"), pas une règle dure
    codée, tant qu'elle n'est pas confirmée commune par commune.

Bot     : Voulez-vous que je vous aide à préparer le dossier maintenant ?

Citoyen : Oui.

  → transition mode = information → administratif, cas_legal = "tardif"
    déjà connu (pas de nouveau cadrage nécessaire)
```

---

## PARTIE 2 — MODE ADMINISTRATIF (dépôt de demande)

Le citoyen construit un dossier complet avec le bot : collecte des informations, upload de documents, relecture orale, confirmation, envoi au consultant.

### Exemple 2.1 — Dépôt complet, cas « dans les délais »

```
Bot     : Parfait, on va préparer votre demande. D'abord, dans quelle
          commune votre fils est-il né ?

  → slot: commune_naissance

Citoyen : À Tambacounda.

  → entity: commune_naissance = "Tambacounda"
    action: résolution de la mairie destinataire (lookup table communes)

Bot     : Merci. Est-ce qu'on vous a remis un certificat de naissance ou
          d'accouchement à l'hôpital ou à la maternité ?

  → slot attendu: certificat_naissance (bool + document)

Citoyen : Oui, je l'ai avec moi.

Bot     : Très bien, vous pouvez me l'envoyer en photo maintenant.

  → UI: bouton/action "envoyer une photo"
    action: upload_document(type="certificat_naissance")

Citoyen : [upload d'une image]

  → événement: document_recu(type="certificat_naissance", fichier_id=...)
    statut affiché au citoyen: "Document reçu ✓"
    (l'OCR n'est PAS lancé côté citoyen — il est déclenché plus tard côté
     consultant, cf. UC3 du DSF)

Bot     : Merci. Quel est le nom complet de votre fils ?

  → slot: nom_enfant

Citoyen : Ibrahima Diallo.

Bot     : Et sa date de naissance exacte ?

  → slot: date_naissance_enfant

Citoyen : Le 9 août 2026.

  → validation format date + cohérence avec age_enfant déjà connu (7 jours)

Bot     : Pouvez-vous me donner votre nom complet, à vous, en tant que
          déclarant ?

  → slot: nom_declarant

Citoyen : Modou Diallo.

Bot     : Avez-vous votre carte d'identité sur vous ? Vous pouvez
          m'envoyer une photo.

  → slot: cni_declarant (document)

Citoyen : [upload d'une image]

  → événement: document_recu(type="cni_declarant", fichier_id=...)

Bot     : Et la maman de l'enfant, quel est son nom complet et sa date de
          naissance ?

  → slot: nom_mere, date_naissance_mere

Citoyen : Aïssatou Ba, née le 12 mars 1998.

Bot     : Êtes-vous mariés, elle et vous ?

  → slot: parents_maries (bool)

Citoyen : Oui, à la mairie l'année dernière.

Bot     : Avez-vous le livret de famille ou le certificat de mariage ?
          Vous pouvez me l'envoyer, ou me dire que vous ne l'avez pas sous
          la main.

  → slot: livret_famille (optionnel selon RG6)

Citoyen : Je ne l'ai pas avec moi aujourd'hui.

  → action: marquer_document_manquant(type="livret_famille", requis=false,
            note="à compléter ultérieurement")

Bot     : Pas de problème, ce n'est pas bloquant. Je vous relis maintenant
          tout ce que j'ai noté pour vérifier que c'est correct :

          « Ibrahima Diallo, né le 9 août 2026 à Tambacounda, fils de
          Modou Diallo et de Aïssatou Ba, née le 12 mars 1998, parents
          mariés (livret de famille non fourni). »

          Est-ce que tout est exact ?

  → action: relecture_complete(recapitulatif=dossier_courant)
    RÈGLE OBLIGATOIRE (RG7 du DSF): cette étape ne peut jamais être
    sautée, même si tous les slots sont remplis via upload de documents.

Citoyen : Oui, c'est bon.

  → NLU: intent = confirmer_dossier

Bot     : Voilà, votre demande est envoyée à la mairie de Tambacounda.
          Voici votre numéro de suivi : SM-2026-000452. Je vous
          préviendrai dès que votre extrait de naissance sera prêt.

  → action: creer_dossier(statut="recu", commune="Tambacounda",
            numero_suivi="SM-2026-000452")
    notification programmée: relance si statut inchangé après X jours
```

**Points d'implémentation :**
- **Machine à états / slots** suggérée pour ce flux : `commune_naissance → certificat_naissance → nom_enfant → date_naissance_enfant → nom_declarant → cni_declarant → nom_mere/date_naissance_mere → parents_maries → [livret_famille] → recapitulatif → confirmation → envoi`.
- Chaque document uploadé doit être stocké avec son `type` (enum : `certificat_naissance`, `cni_declarant`, `cni_conjoint`, `livret_famille`, `certificat_mariage`) pour que le consultant sache quoi attendre à l'OCR (UC3).
- Un slot peut être marqué `requis=false` avec une note — le dossier reste envoyable, mais le consultant verra le manque et pourra demander un complément (UC3, scénario alternatif « dossier incomplet »).
- La relecture finale (RG7) doit être un **nœud obligatoire** dans le graphe de dialogue, jamais contournable par une confirmation implicite plus tôt dans la conversation.

---

### Exemple 2.2 — Relance pour complément de dossier

```
Bot     : Bonjour Modou, le consultant de la mairie de Tambacounda a
          examiné votre dossier SM-2026-000452. Il manque encore le
          livret de famille pour finaliser. Pouvez-vous me l'envoyer en
          photo ?

  → déclencheur: événement côté consultant "demande_complement"
    (cf. DSF UC3, scénario alternatif)
    slot rouvert: livret_famille

Citoyen : [upload d'une image]

  → événement: document_recu(type="livret_famille", fichier_id=...)
    action: mise_a_jour_dossier(statut="complement_recu")
    notification consultant: dossier mis à jour

Bot     : Merci, c'est transmis à la mairie. Je vous préviens dès que
          votre extrait sera prêt.
```

---

### Exemple 2.3 — Déviation : le citoyen ne peut/veut pas envoyer de photo

```
Bot     : Est-ce qu'on vous a remis un certificat de naissance ou
          d'accouchement ? Vous pouvez me l'envoyer en photo.

Citoyen : Je ne sais pas prendre de photo avec le téléphone, ou je n'ai
          pas de réseau assez fort en ce moment.

  → NLU: intent = refus_upload / incapacite_technique
    RÈGLE: ne jamais bloquer le dossier sur un upload impossible —
    proposer une alternative dictée + upload différé.

Bot     : Pas de souci. Est-ce que quelqu'un près de vous peut m'aider à
          prendre la photo, ou préférez-vous me dire les informations du
          document à voix haute, et l'envoyer plus tard quand vous
          pourrez ?

  → slot: mode_document = "photo" | "dicte" | "differe"

Citoyen : Je préfère vous le dire de vive voix pour l'instant.

Bot     : D'accord. Quel est le nom de la sage-femme ou de la structure de
          santé indiquée sur le papier ?

  → collecte manuelle des champs clés du document (structure_sante,
    date_delivrance) en l'absence d'OCR possible
    action: marquer_document(type="certificat_naissance", mode="dicte",
            fichier_id=null, statut="a_completer")

Bot     : Merci, j'ai noté ça. On continue, et n'oubliez pas d'envoyer la
          photo du document dès que possible — le consultant en aura
          besoin pour finaliser votre extrait.
```

**Point d'implémentation :** un dossier avec un document en statut `a_completer` (saisie dictée sans image) doit rester **bloquant côté consultant** pour la validation finale (UC3/RG6 du DSF) — le champ dicté aide à avancer la conversation mais ne remplace pas la pièce justificative pour la génération officielle.

---

### Exemple 2.4 — Déviation : document illisible ou mal cadré

```
Citoyen : [upload d'une image floue/coupée]

  → événement: document_recu(type="certificat_naissance", fichier_id=...)
    contrôle qualité (côté app, avant envoi au backend) : résolution/
    flou/cadrage détecté insuffisant

Bot     : La photo est un peu difficile à lire, on dirait qu'elle est
          floue ou coupée. Pouvez-vous réessayer, si possible avec plus de
          lumière et le document bien à plat ?

  → NOTE dev: ce contrôle de qualité est idéalement fait CÔTÉ CLIENT
    (heuristique simple : taille fichier, netteté) pour éviter un
    aller-retour serveur inutile ; un contrôle plus fin peut être refait
    côté OCR au moment du traitement consultant (UC3).

Citoyen : [upload d'une nouvelle image]

Bot     : Merci, celle-ci est bien plus claire.
```

---

### Exemple 2.5 — Déviation : information incohérente ou ambiguë

```
Citoyen : Mon fils est né le 30 février.

  → NLU: entity = date_naissance_enfant → échec de parsing/validation
    (date invalide)

Bot     : Je crois qu'il y a une erreur sur la date — le mois de février
          n'a pas de 30ᵉ jour. Pouvez-vous vérifier la date exacte, par
          exemple sur le certificat de naissance ?

  → RÈGLE: toute entité qui échoue à la validation de format déclenche
    une reformulation ciblée, jamais une correction silencieuse ni un
    blocage sans explication.

Citoyen : Ah pardon, c'est le 28 février.

  → entity: date_naissance_enfant = validée, conversation reprend au
    même point du graphe de dialogue (pas de retour en arrière complet)
```

---

## Annexe technique — schéma de slots proposé (pour prototypage rapide)

```json
{
  "demarche": "extrait_naissance",
  "mode": "information | administratif",
  "cas_legal": "dans_les_delais | tardif | jugement_requis",
  "slots": {
    "age_enfant": {"valeur": null, "unite": null},
    "commune_naissance": null,
    "nom_enfant": null,
    "date_naissance_enfant": null,
    "nom_declarant": null,
    "nom_mere": null,
    "date_naissance_mere": null,
    "parents_maries": null
  },
  "documents": [
    {"type": "certificat_naissance", "fichier_id": null, "requis": true},
    {"type": "cni_declarant", "fichier_id": null, "requis": true},
    {"type": "livret_famille", "fichier_id": null, "requis": false}
  ],
  "statut": "en_cours | recu | complement_demande | valide | pret"
}
```

Ce schéma peut servir directement de point de départ pour le state management côté agent (ex. LangGraph, machine à états custom, ou simple objet de session) lors du développement dans Claude Code.

---

## Annexe — Taxonomie des intentions (NLU)

| Intent | Déclenché par | Exemple |
|---|---|---|
| `demander_information` | Question ouverte sur une démarche | « comment avoir un extrait de naissance » |
| `accepter_bascule_mode` | Confirmation de vouloir déposer un dossier | « oui je veux bien commencer » |
| `refus_upload` | Incapacité/refus d'envoyer une photo | « je ne sais pas prendre de photo » |
| `confirmer_dossier` | Validation finale après relecture | « oui c'est bon » / « c'est correct » |
| `corriger_information` | Rectification d'une donnée déjà donnée | « non en fait c'est le 28 » |
| `demander_statut` | Question sur l'avancement d'un dossier déjà déposé | « où en est ma demande » |
| `fin_conversation` | Sortie explicite sans dépôt | « juste l'information merci » |
| `hors_perimetre` | Démarche non couverte par le MVP | question sur un divorce, un permis de construire, etc. |

## Annexe — Taxonomie des entités

| Entité | Type | Normalisation attendue |
|---|---|---|
| `type_demarche` | enum | `extrait_naissance` (MVP), autres à venir |
| `age_enfant` | {valeur, unité} | convertir en jours pour appliquer RG1/RG2/RG3 |
| `date_naissance_enfant` / `date_naissance_mere` | date | valider format + plausibilité (pas de 30 février, pas de date future) |
| `commune_naissance` | string → id commune | lookup contre la table `Commune` du DSF §8 |
| `nom_enfant` / `nom_declarant` / `nom_mere` | string | pas de normalisation forte — relecture humaine obligatoire (RG7) |
| `parents_maries` | bool | — |
| `declaration_existante` | bool | utilisé uniquement en mode information pour déterminer le cas légal |

## Annexe — Prompts système de départ (à affiner)

Ces prompts sont des points de départ pour prototyper rapidement les deux sous-agents (classification d'intention + gestion de dialogue) dans Claude Code. Ils sont volontairement génériques et devront être adaptés une fois le pipeline ASR/traduction pulaar branché.

**Prompt — module de détection d'intention et d'extraction d'entités :**

```
Tu es le module de compréhension du langage d'un agent d'assistance
administrative sénégalais. L'utilisateur s'exprime en français (traduit
depuis le pulaar en amont). Analyse son message et retourne un JSON avec :
- "intent" : une valeur parmi [demander_information, accepter_bascule_mode,
  refus_upload, confirmer_dossier, corriger_information, demander_statut,
  fin_conversation, hors_perimetre]
- "entities" : un objet contenant les entités détectées parmi
  [type_demarche, age_enfant, date_naissance_enfant, date_naissance_mere,
  commune_naissance, nom_enfant, nom_declarant, nom_mere, parents_maries,
  declaration_existante], uniquement celles mentionnées explicitement.
- "confidence" : score entre 0 et 1

Ne déduis jamais une information non dite explicitement (ex. ne pas
supposer que les parents sont mariés si ce n'est pas mentionné).
Retourne uniquement le JSON, sans texte autour.
```

**Prompt — module de gestion de dialogue (dialogue manager) :**

```
Tu es l'agent conversationnel SUNU-MAIRIE. Tu accompagnes un citoyen
sénégalais, potentiellement analphabète, pour une démarche administrative
(extrait de naissance pour le MVP). Règles impératives :

1. Une seule question à la fois, formulée simplement, sans jargon
   administratif non expliqué.
2. Ne jamais confirmer un dossier sans relecture orale complète et
   confirmation explicite de l'utilisateur (RG7).
3. Ne jamais affirmer qu'une démarche nécessitant un passage physique
   (ex. jugement supplétif au tribunal) peut être entièrement réalisée
   sans déplacement.
4. Si une donnée échoue à la validation (date invalide, incohérence),
   le signaler et redemander, sans deviner ni corriger silencieusement.
5. Rester dans le périmètre du MVP (extrait de naissance) ; pour toute
   autre demande, l'indiquer clairement et orienter vers un contact
   humain.

État courant du dossier (slots remplis, documents reçus, cas légal
déterminé) : {état injecté dynamiquement}

Détermine la prochaine question ou action à partir de l'état courant et
du dernier message utilisateur.
```

**Note pour le développement :** ces deux prompts correspondent à une architecture à deux étages (NLU séparé du dialogue manager). Une alternative plus simple pour un premier prototype est de fusionner les deux dans un seul appel avec function calling / structured output (le modèle retourne à la fois la réponse en langage naturel ET l'état mis à jour du dossier en JSON) — à évaluer selon la latence obtenue avec le pipeline vocal complet.
