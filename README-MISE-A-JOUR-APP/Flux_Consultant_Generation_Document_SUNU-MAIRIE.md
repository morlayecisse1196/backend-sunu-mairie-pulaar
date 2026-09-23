# Flux Consultant — Réception → Génération → Validation citoyen

Ce document détaille le pendant du DSF §UC3, avec l'ajout d'un **agent LLM assistant du consultant** et la **boucle de validation par le citoyen**. Il complète `Exemples_Dialogues_Agent_SUNU-MAIRIE.md` (côté citoyen) pour couvrir l'ensemble du parcours d'un dossier.

---

## 0. Approche par phases : V1 sans OCR, V2 avec OCR (scope : CNI uniquement)

Décision de développement : la première version de l'application **ne contient pas d'OCR**. Le consultant remplit/rectifie chaque document manuellement, en comparant l'image du document à un formulaire structuré. L'OCR sera ajouté plus tard **sans changer l'interface** — il vient simplement pré-remplir un formulaire qui, en V1, se remplit déjà à la main.

**Décision de périmètre (V2) :** l'OCR ne sera entraîné/branché que sur la **carte d'identité nationale (CNI)** — texte imprimé, mise en page standardisée, zone MRZ avec chiffres de contrôle (cf. discussion précédente). Les autres documents (certificat de naissance, livret de famille, certificat de mariage, certificat de non-inscription) **restent en lecture manuelle par le consultant indéfiniment**, pas seulement le temps d'une V1 transitoire — ce sont des documents majoritairement manuscrits, à la mise en page variable d'une mairie à l'autre, donc un bien moins bon rapport effort/gain pour l'OCR. Si un champ obligatoire d'un dossier ne peut être vérifié que via l'un de ces documents non couverts par l'OCR, il reste et restera du ressort exclusif de la lecture manuelle du consultant dans l'interface du §2.2.

**Ce qui ne change pas entre V1 et V2 :** l'interface du consultant (image à gauche, formulaire à droite — détaillée en §2.2), la structure des champs du formulaire (alignée sur `extrait_naissance.xsd`), et le fait que le consultant reste toujours libre de modifier n'importe quel champ avant génération — y compris pour la CNI en V2.

**Ce qui change entre V1 et V2 :** uniquement la **source qui pré-remplit** le formulaire au départ, et uniquement pour le document `cni_declarant` (et `cni_conjoint` le cas échéant).

| | V1 (sans OCR) | V2 (OCR sur la CNI uniquement) |
|---|---|---|
| Champs déjà connus par le dialogue citoyen (nom, date, lieu de naissance, parents) | Pré-remplis automatiquement à partir des données collectées par l'agent vocal | Identique — le dialogue reste la première source |
| Champs visibles sur la CNI (nom, prénom, date de naissance, NIN) | Vides — le consultant lit l'image et saisit manuellement | Pré-remplis par l'OCR/MRZ, avec un score de confiance affiché |
| Champs visibles uniquement sur les autres documents (certificat de naissance, livret de famille, etc.) | Vides — lecture manuelle | **Toujours vides — lecture manuelle, aucun changement en V2** |
| Vérification de cohérence dialogue vs document | Faite visuellement par le consultant (image à gauche, valeurs du dialogue à droite) | Assistée par l'agent LLM (§2.4) **pour la CNI seulement** ; manuelle pour le reste |
| Effort de développement | Formulaire + stockage des champs + génération via template | + service OCR/MRZ scopé à un seul type de document |

Cette conception garde le système **facilement extensible** si vous décidez un jour d'étendre l'OCR à d'autres documents : chaque champ du formulaire est déjà modélisé avec un attribut `source` (`dialogue` / `manuel` / `ocr`) et un `type_document` associé dès la V1 — ajouter un second type de document à l'OCR reviendrait à brancher un nouveau fournisseur de valeurs pour ce `type_document`-là, sans redessiner l'écran ni changer le modèle de données (cf. §3). Mais ce n'est pas un développement prévu à court terme.

---

## 1. Vue d'ensemble du flux

```
[Dossier reçu (citoyen)]
        ↓
[1. Réception & tri]                statut = "recu"
        ↓
[2. Prévisualisation consultant]    (données dialogue + documents bruts)
        ↓
[3. OCR sur la CNI uniquement]      → données extraites + score de confiance
     (les autres documents restent en lecture manuelle, cf. §0 et §2.2)
        ↓
[4. Analyse LLM assistant]          → cohérence, anomalies, résumé, suggestions
        ↓
[5. Résolution des cas imprévus]    (LLM propose, consultant décide)         ← boucle si besoin
        ↓
[6. Sélection template + génération]  statut = "genere"
        ↓
[7. Envoi au citoyen pour validation] statut = "en_attente_validation"
        ↓
   ┌────┴────┐
   ▼         ▼
[Validé]  [Remarques du citoyen]
   │         │
   ▼         ▼
[Téléchargeable]  [Retour étape 5/6 avec remarques intégrées] ← boucle
statut="finalise"
```

Le principe directeur : **le LLM assiste et accélère, le consultant décide et valide.** Aucune génération de document d'état civil n'est envoyée au citoyen sans passage par un consultant humain (cf. DSF §6, exigence sur la relecture obligatoire).

---

## 2. Étape par étape

### 2.1 Réception & tri

Dès l'envoi du dossier par le citoyen (cf. UC2), il apparaît dans la liste du consultant de la commune concernée, trié par ordre d'ancienneté, avec un badge indiquant le **cas légal** (`dans_les_delais` / `tardif` / `jugement_requis`) et le **type de démarche**.

### 2.2 Interface consultant : image à gauche, formulaire à droite

C'est l'écran central de l'application, celui que le consultant utilise pour chaque document du dossier.

**Disposition :**
- **Colonne gauche — visionneuse d'image.** Le document uploadé par le citoyen, affiché net et zoomable (zoom/pan pour lire les zones difficiles — écriture manuscrite, cachets). Une miniature en haut permet de naviguer entre les documents du dossier (`certificat_naissance`, `cni_declarant`, `livret_famille`, etc.) sans changer d'écran.
- **Colonne droite — formulaire structuré.** Un champ de saisie par donnée attendue pour ce type de document, aligné sur les éléments du schéma `extrait_naissance.xsd` (`prenomEnfant`, `nomFamilleEnfant`, `dateNaissance`, `lieuNaissance`, `prenomPere`, `prenomMere`, `nomFamilleMere`, etc.). Chaque champ affiche une petite étiquette indiquant sa **source** :
  - `dialogue` — valeur déjà connue car donnée par le citoyen à l'agent vocal (pré-remplie, modifiable)
  - `manuel` — champ vide en V1, à remplir par le consultant en lisant l'image
  - `ocr` (V2 uniquement, cf. §2.3) — pré-rempli automatiquement, avec un indicateur de confiance

**Comportement en V1 (sans OCR) :**
1. Les champs déjà connus par le dialogue (ex. `prenomEnfant`, `dateNaissance`) apparaissent **pré-remplis** à droite dès l'ouverture — le consultant les compare visuellement à l'image et corrige si l'image révèle une différence (ex. orthographe exacte du nom sur le document officiel).
2. Les champs qui n'existent que sur le document physique (ex. structure de santé, numéro de registre local visible sur l'extrait source, mentions marginales) sont **vides** — le consultant les lit sur l'image de gauche et les saisit à droite.
3. Un bouton « Champ vérifié » par ligne permet de marquer explicitement qu'un champ a été comparé à l'image, pour la traçabilité (utile en cas de litige, cf. §2.7).

**Comportement en V2 (une fois l'OCR ajouté) — même écran :**
- Les champs `manuel` de la V1 deviennent pré-remplis automatiquement par l'OCR (source affichée `ocr`, avec score de confiance), mais restent éditables exactement de la même façon.
- Un champ à faible confiance OCR (cf. §2.3) est visuellement signalé (ex. bordure orange) pour attirer l'œil du consultant sur l'image correspondante.
- Aucun changement de disposition, de navigation entre documents, ni de logique de sauvegarde — seule la valeur initiale du champ change de provenance.

**Point d'implémentation pour la V1 :** concevoir dès maintenant le composant de formulaire pour qu'il consomme une liste de champs typés `{nom, valeur, source, confiance?}` plutôt que des champs codés en dur par type de document — `confiance` reste simplement `null`/absent tant que l'OCR n'existe pas. C'est ce qui rend le branchement de l'OCR plus tard indolore.

### 2.3 OCR sur la CNI *(V2 — non développé en V1, scope limité à ce seul type de document)*

Une fois ajouté, le document `cni_declarant` (et `cni_conjoint` le cas échéant) sera passé à l'OCR/MRZ. Résultat attendu :

```json
{
  "document_id": "...",
  "type": "certificat_naissance",
  "champs_extraits": {
    "nom_enfant": {"valeur": "Ibrahima Diallo", "confiance": 0.94},
    "date_naissance": {"valeur": "2026-08-09", "confiance": 0.88},
    "structure_sante": {"valeur": "Case de santé de ...", "confiance": 0.71}
  },
  "qualite_image": "bonne | moyenne | insuffisante"
}
```

**Point d'implémentation :** l'OCR doit retourner un **score de confiance par champ**, pas seulement un texte brut. C'est ce score qui pilote ensuite l'analyse LLM (étape 2.4) : un champ à faible confiance est un candidat naturel à la vérification humaine, pas à l'automatisation silencieuse.

### 2.4 Analyse par l'agent LLM assistant

**En V1 (sans OCR), le périmètre de cet agent est réduit** : sans données OCR, il ne peut pas comparer dialogue et document — cette comparaison reste visuelle, faite par le consultant via l'interface du §2.2. L'agent LLM reste néanmoins utile dès la V1 pour les points 1 et 4 ci-dessous (résumé et vérification de complétude selon les règles de gestion) ; les points 2 et 3 (incohérences et confiance OCR) n'activent leur plein potentiel qu'en V2. Vous pouvez tout à fait démarrer sans cet agent du tout en V1 et l'introduire au moment de l'OCR — le formulaire manuel fonctionne seul.

En V2, un agent LLM qui **lit l'ensemble du dossier** (données dialogue + résultats OCR de tous les documents) et produit une aide à la décision pour le consultant, sans jamais décider seul à sa place.

**Ce que l'agent LLM produit :**

1. **Résumé en langage naturel du dossier**, pour une lecture rapide par le consultant.
2. **Détection des incohérences** entre les sources (dialogue vs OCR, ou entre deux documents) — ex. un nom orthographié différemment sur la CNI et sur le certificat de naissance.
3. **Repérage des champs à faible confiance OCR**, avec la donnée du dialogue proposée comme alternative si disponible.
4. **Vérification de complétude** par rapport aux règles de gestion du DSF (RG1 à RG6) selon le cas légal du dossier — ex. si `cas_legal = jugement_requis`, l'agent vérifie que la mention du jugement est bien présente, sinon l'alerte comme bloquant.
5. **Suggestions d'action**, jamais des décisions automatiques : « valider tel quel », « demander telle précision au citoyen », « vérifier manuellement tel champ ».

**Exemple d'interaction consultant ↔ agent LLM :**

```
[Le consultant ouvre le dossier SM-2026-000452 et clique sur
 "Analyser avec l'assistant"]

Agent LLM → Consultant :

  Résumé : Demande d'extrait de naissance pour Ibrahima Diallo, né le
  09/08/2026 à Tambacounda, cas "dans les délais". Déclarant : Modou
  Diallo (père). Parents mariés (livret de famille non fourni — marqué
  comme non bloquant par le citoyen).

  ⚠ Incohérence détectée : le nom de la mère saisi dans le dialogue est
  "Aïssatou Ba", mais l'OCR du certificat de naissance lit "Aïssatou
  Bâ" (confiance OCR : 0.79). Il s'agit probablement du même nom avec
  une variante d'accentuation.
  → Suggestion : conserver l'orthographe du document officiel
    ("Aïssatou Bâ") car il fait foi, mais à confirmer par vous.

  ⚠ Champ à faible confiance : "structure_sante" extrait à 0.71 sur le
  certificat — la photo est un peu sombre à cet endroit.
  → Suggestion : vérifier visuellement ce champ avant génération (le
    document reste lisible pour le reste).

  ✓ Documents obligatoires présents pour ce cas (dans les délais) :
  certificat de naissance ✓, CNI déclarant ✓. Livret de famille absent
  mais non bloquant selon RG6.

  Aucun autre point bloquant détecté. Le dossier semble prêt pour
  génération sous réserve de votre validation des deux points ci-dessus.
```

Le consultant valide/corrige les points signalés (interface : accepter la suggestion en un clic, ou éditer manuellement), puis passe à l'étape suivante.

**Point d'implémentation :** cet agent doit être conçu en **read + suggest**, jamais en **write** direct sur le dossier. Toute modification de champ doit passer par une action explicite du consultant (même si l'UI ne demande qu'un clic "accepter la suggestion").

### 2.5 Gestion des cas imprévus

C'est le point que vous soulevez comme critique : le système ne doit pas bloquer sur un cas non prévu par les règles codées. Approche proposée :

- Tout ce que l'agent LLM ne sait pas classer avec un niveau de confiance suffisant (incohérence non résolue automatiquement, champ manquant sans règle claire, situation inhabituelle — ex. deux déclarants, document dans une langue non attendue, informations contradictoires entre deux uploads) déclenche une **carte "cas particulier"** dans l'interface du consultant.
- L'agent LLM formule le problème en langage clair et propose **1 à 3 options d'action concrètes**, par exemple :
  - « Demander une précision au citoyen via l'agent conversationnel (message pré-rédigé ci-dessous, modifiable) »
  - « Poursuivre la génération en laissant le champ vide, à compléter manuellement dans le document »
  - « Escalader vers un superviseur / l'administrateur de la commune »
- Le consultant choisit une option (ou en formule une autre librement) — **l'agent ne prend jamais cette décision seul**, il l'assiste et accélère la formulation.
- Chaque cas particulier résolu est **journalisé** (problème rencontré, option choisie) — cette base sert plus tard à enrichir les règles codées et les prompts de l'agent, pour réduire le nombre de cas imprévus au fil du temps.

```json
{
  "type_incident": "incoherence_non_resolue | champ_manquant | document_inattendu | autre",
  "description_llm": "texte généré expliquant le problème",
  "options_proposees": ["...", "...", "..."],
  "decision_consultant": "...",
  "horodatage": "..."
}
```

### 2.6 Sélection du template et génération du document

- Chaque type de démarche (`extrait_naissance` pour le MVP, extensible ensuite) est associé à un **template XML** dans un registre `Template` (cf. DSF §8).
- Le template définit la structure du document final et les emplacements où injecter les données du dossier (après résolution des étapes 2.4/2.5).

**Exemple simplifié de template XML pour un extrait de naissance :**

```xml
<document type="extrait_naissance" version="1.0">
  <entete>
    <republique>République du Sénégal</republique>
    <commune source="dossier.commune_naissance"/>
    <titre>Extrait du registre des actes de naissance</titre>
  </entete>
  <corps>
    <champ nom="nom_complet_enfant" source="dossier.nom_enfant" obligatoire="true"/>
    <champ nom="date_naissance" source="dossier.date_naissance_enfant"
           format="jj/mm/aaaa" obligatoire="true"/>
    <champ nom="lieu_naissance" source="dossier.commune_naissance" obligatoire="true"/>
    <champ nom="nom_pere" source="dossier.nom_declarant" obligatoire="false"/>
    <champ nom="nom_mere" source="dossier.nom_mere" obligatoire="false"/>
    <champ nom="numero_acte" source="genere.numero_registre" obligatoire="true"/>
  </corps>
  <pied>
    <champ nom="date_delivrance" source="systeme.date_generation"/>
    <champ nom="signataire" source="consultant.nom"/>
  </pied>
</document>
```

**Extensibilité (point important de votre demande) :** ce même mécanisme (registre `type_demarche → template.xml`) permet d'ajouter n'importe quelle démarche future (acte de mariage, acte de décès, etc.) sans changer le moteur de génération — seul un nouveau fichier template et son mapping de champs sont à ajouter. Le moteur de génération lit le XML, résout chaque `source="..."` contre l'objet dossier, et produit le document final (PDF, par exemple).

- Un champ marqué `obligatoire="true"` sans valeur résolue **bloque la génération finale** et remonte comme cas particulier (cf. 2.5) plutôt que de produire un document incomplet silencieusement.

### 2.7 Envoi au citoyen pour validation (et non téléchargement direct)

C'est le point clé de votre dernière demande : le document généré **n'est pas immédiatement définitif**. Il est envoyé au citoyen en mode « prévisualisation », avec un statut de dossier `en_attente_validation_citoyen`.

- Le citoyen (potentiellement analphabète) doit pouvoir **comprendre** le contenu sans le lire lui-même : l'agent vocal lui **relit oralement** les champs clés du document généré (nom, date, lieu — les mêmes que ceux confirmés lors du dépôt), pas le document brut.
- Deux issues possibles :
  - **Le citoyen valide** → statut `finalise`, le document devient définitivement téléchargeable (PDF signé/scellé selon le circuit officiel retenu).
  - **Le citoyen signale une erreur** → il énonce sa remarque (vocalement), l'agent la transcrit et la structure, et le dossier repart vers le consultant avec un statut `corrections_demandees` et la remarque attachée.

**Exemple de dialogue de validation côté citoyen :**

```
Bot     : Votre extrait de naissance est prêt. Je vous relis les
          informations principales : Ibrahima Diallo, né le 9 août 2026
          à Tambacounda, fils de Modou Diallo et Aïssatou Bâ. Est-ce que
          tout est correct ?

  → action: lecture_recapitulative(document_genere_id=...)

Citoyen : Non, le nom de la maman n'est pas bien écrit, c'est Aïssatou
          Ba, sans l'accent circonflexe.

  → NLU: intent = signaler_erreur
    entity = champ_concerne: "nom_mere"
    entity = correction_proposee: "Aïssatou Ba"

Bot     : D'accord, je transmets cette correction au consultant, votre
          document sera corrigé et vous sera renvoyé pour validation.

  → action: creer_remarque(dossier_id=..., champ="nom_mere",
            remarque="Aïssatou Ba (sans accent)", source="citoyen")
    statut dossier → "corrections_demandees"
    notification consultant: nouvelle remarque à traiter
```

**Côté consultant, à la réouverture du dossier :**

```
Agent LLM → Consultant :

  Le citoyen a signalé une correction sur le document SM-2026-000452 :
  le champ "nom_mere" doit être "Aïssatou Ba" au lieu de "Aïssatou Bâ".
  Cette remarque confirme l'incohérence déjà repérée à l'étape d'analyse
  initiale (OCR vs dialogue) — la version du dialogue était la bonne.

  → Suggestion : appliquer la correction et régénérer le document.
```

- Le consultant applique (ou ajuste), régénère via le même template (2.6), et le document repart en validation citoyen (2.7). Cette boucle peut se répéter tant que nécessaire.
- **Historique des versions** conservé : chaque génération est numérotée, avec la remarque qui l'a déclenchée, pour traçabilité (utile en cas de litige sur un acte d'état civil).

**Point d'implémentation — limite de boucle :** prévoir un compteur d'itérations (ex. au-delà de 3 allers-retours sur le même dossier) qui déclenche une alerte/escalade vers un superviseur, pour éviter qu'un dossier reste bloqué indéfiniment entre citoyen et consultant.

---

## 3. Modèle de données complémentaire (extension du DSF §8)

| Entité | Champs clés |
|---|---|
| `DocumentFormulaire` | `id`, `dossier_id`, `document_id`, `type_document`, `champs` (liste de `ChampFormulaire`), `statut` (`a_remplir` / `rempli` / `verifie`) — **c'est l'entité clé de la V1**, le formulaire structuré associé à chaque image uploadée |
| `ChampFormulaire` | `nom` (aligné sur `extrait_naissance.xsd`), `valeur`, `source` (`dialogue` / `manuel` / `ocr`), `confiance` (nul en V1, rempli par l'OCR en V2), `verifie_par_consultant` (bool) |
| `DocumentGenere` | `id`, `dossier_id`, `template_utilise`, `version`, `contenu` (PDF/XML rempli), `statut` (`genere` / `en_attente_validation` / `valide` / `corrections_demandees`), `date_generation` |
| `Remarque` | `id`, `dossier_id`, `document_genere_id`, `champ_concerne`, `texte`, `source` (`citoyen`/`consultant`), `horodatage` |
| `CasParticulier` | `id`, `dossier_id`, `type_incident`, `description_llm`, `options_proposees`, `decision_consultant`, `horodatage` |
| `Template` (déjà dans le DSF) | `type_demarche`, `structure_xml`, `version` — un registre par type de démarche, extensible |

**Pourquoi `DocumentFormulaire` est structuré ainsi :** en V1, tous les `ChampFormulaire` ont `source = "dialogue"` (pré-rempli) ou `source = "manuel"` (rempli par le consultant), et `confiance` reste toujours nul. Le jour où l'OCR est branché, il vient simplement créer des `ChampFormulaire` avec `source = "ocr"` et une `confiance` renseignée, **sans changer le schéma de l'entité ni l'écran qui l'affiche** (cf. §2.2).

**Statuts possibles d'un dossier (cycle de vie complet) :**

```
recu → en_traitement → genere → en_attente_validation_citoyen
   → finalise
   → corrections_demandees → en_traitement (boucle)
```

---

## 4. Rôle de l'agent LLM assistant — synthèse pour le prompt système

```
Tu es l'assistant du consultant d'état civil dans le système SUNU-MAIRIE.
Ton rôle est d'ACCÉLÉRER l'analyse d'un dossier, jamais de décider à la
place du consultant. Pour chaque dossier reçu, tu dois :

1. Résumer le dossier en 3-4 phrases claires.
2. Comparer les données issues du dialogue avec le citoyen et les données
   extraites par OCR ; signaler toute incohérence avec un niveau de
   gravité (bloquant / à vérifier / mineur).
3. Identifier les champs à faible confiance OCR (< 0.8) et proposer la
   donnée du dialogue comme alternative si elle existe.
4. Vérifier la complétude du dossier au regard des règles de gestion
   applicables au cas légal identifié (dans_les_delais / tardif /
   jugement_requis).
5. Pour toute situation que tu ne peux pas résoudre avec un niveau de
   confiance suffisant, ne choisis jamais unilatéralement : formule le
   problème clairement et propose entre 1 et 3 options d'action que le
   consultant pourra choisir ou modifier.
6. Ne modifie jamais un champ du dossier directement — tu proposes, le
   consultant valide.

Ne génère aucune conclusion du type "ce dossier est valide" ou "ce
document est correct" — seul le consultant peut acter cette décision.
```

---

## 5. Points à valider avec l'encadrant

- Quelle est la **valeur légale exacte** du document généré automatiquement (assisté LLM) avant impression/signature physique éventuelle par le maire ou l'officier d'état civil — le système remplace-t-il la signature manuscrite finale, ou reste-t-elle une étape hors application ?
- Faut-il un **rôle superviseur** distinct du consultant pour les cas particuliers escaladés (cf. §2.5), ou le même consultant les traite-t-il en dernier ressort ?
- Le nombre maximal d'itérations citoyen ↔ consultant (§2.7) avant escalade — à définir précisément (proposition de départ : 3).
