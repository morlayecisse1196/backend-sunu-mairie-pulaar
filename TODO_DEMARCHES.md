# TODO — Démarches paramétrables et pulaar validé

Objectif : **ajouter une démarche sans toucher au code**, et **supprimer le pulaar
généré à la volée** partout où la phrase est connue d'avance.

Méthode habituelle : une tâche est cochée seulement après vérification.

## Décisions

| Sujet | Décision | État |
|---|---|---|
| Validation du pulaar | Par vous-même, depuis l'interface admin | ✅ |
| Démarches visées | Extrait de naissance, certificat de mariage, certificat de décès | ✅ |
| Fournisseur LLM configurable | Abandonné : ce n'était pas la cause du problème | ✅ |
| Copie d'un acte existant **ou** déclaration d'un événement ? | À trancher, par démarche (voir D0.1) | ⏳ |
| Modèles réels | Certificat de mariage constaté et certificat médical de décès reçus | ✅ |

---

## Ce que l'acte réel de Tambacounda a appris

Le schéma `templates/extrait_naissance.xsd` colle au document, **y compris** le bloc
« jugement d'autorisation d'inscription », rempli ici (enfant né en 1996, inscrit en
2003). Quatre écarts à corriger :

1. **`arrondissement` est obligatoire** dans le XSD et le modèle XML, alors que
   l'acte de Tambacounda n'affiche que Région / Département / Commune. À rendre
   optionnel, sinon la génération échouera pour ces communes.
2. **Le sexe** est stocké `M`/`F` mais s'imprime « MASCULIN » / « FÉMININ ».
3. **Le numéro d'acte à 19 chiffres reste une hypothèse** (déjà signalée dans le
   XSD). L'acte porte un code-barres et la mention « CODE REGION 12 — CODE CNI
   392.00 — TYPE CPU ». À faire confirmer par un officier d'état civil ; ne rien
   inventer d'ici là.
4. **Le dialogue ne collecte pas tout ce que le document exige** : prénom et nom de
   famille séparés pour l'enfant et pour la mère, sexe, prénom du père. Ces champs
   sont aujourd'hui saisis par le consultant (sources `formulaire.*` du modèle XML).
   À l'inverse, `date_naissance_mere` est collectée mais **n'apparaît nulle part sur
   l'acte** : à garder uniquement si elle sert à vérifier l'identité, sinon c'est une
   question de plus posée pour rien.

---

## D0 — Cadrage (avant tout code)
- [x] D0.1 Tranché : les trois démarches sont des **déclarations d'événement**, la mairie
      produit l'acte. Le certificat médical de décès est une pièce d'entrée, pas un résultat
- [x] D0.2 Modèles réels reçus : certificat de mariage constaté (Fann-Point E) et certificat
      médical de décès. **Manque encore un acte de décès délivré par une mairie** — c'est lui
      que l'application doit produire, pas le certificat du médecin
- [ ] D0.3 Lister, par démarche, les pièces exigées par la mairie (le site de Pikine
      donne surtout coût, délai et lieu ; les pièces restent à confirmer)

## D1 — Gain immédiat sur le pulaar (sans rien restructurer)
- [ ] D1.1 `SYSTEM_PROMPT_FORMATTER` : ses deux exemples « Dialogue en pulaar » sont
      **écrits en français**. Les remplacer par du vrai pulaar validé
- [ ] D1.2 Glossaire des termes administratifs (français → pulaar validé) injecté dans
      chaque demande de traduction
- [ ] D1.3 Orthographe de substitution pour les mots que la synthèse vocale prononce
      mal (`TODO` déjà noté dans `prompts.py`)

## D2 — Phrases figées : supprimer le LLM du chemin des questions
- [ ] D2.1 Migration : `demarche_champs.question_pulaar`, `audio_cle`, `exemples_reponses`
- [ ] D2.2 Table des messages de document (demande, relances) en français **et** pulaar
      — aujourd'hui figés dans `MESSAGES_DOCUMENT` (`slot_controller.py`)
- [ ] D2.3 Gabarits à trous pour les confirmations et le récapitulatif
- [ ] D2.4 Dire les dates et les nombres en pulaar sans LLM (fonction déterministe,
      validée une fois)
- [ ] D2.5 `temps_reel/parole.py` : si la phrase a un pulaar validé, **ne pas appeler
      le LLM** — servir le texte et l'audio pré-générés
- [ ] D2.6 Pré-génération et cache des audios ; invalidation quand le texte change
- [ ] D2.7 Repli explicite : phrase sans pulaar validé → traduction LLM, et la phrase
      est signalée à valider dans l'admin

## D3 — Le reste du code figé passe en données
- [ ] D3.1 Types de documents, champs de formulaire, correspondance OCR (`dialogue_engine.py`)
- [ ] D3.2 Slots initiaux et démarche par défaut (`temps_reel/etat.py`)
- [ ] D3.3 Bascule en mode administratif : drapeau par démarche, au lieu de
      `est_demarche_extrait_naissance()`
- [ ] D3.4 Règles de cas (aujourd'hui `determiner_cas_legal` : 30 jours, 1 an) →
      conditions paramétrables « si … alors cas … qui exige … »
- [ ] D3.5 Génération de document : modèle XSD/XML/HTML résolu **par démarche**
      (chemins figés sur `extrait_naissance_v1` dans `document_generator.py`)
- [ ] D3.6 Corriger les quatre écarts constatés sur l'acte réel (voir ci-dessus)

## D4 — Interface admin : éditeur de démarche
- [ ] D4.1 Identité : nom, communes, active, avec ou sans dossier
- [ ] D4.2 Séquence des étapes, réordonnable (champs et documents entrelacés)
- [ ] D4.3 Par champ : question française, **question pulaar avec bouton écouter**,
      type, règle de validation choisie dans une liste, exemples de réponses
- [ ] D4.4 Par document : obligatoire ou conditionnel, textes de demande et relances
- [ ] D4.5 Cas particuliers et leurs exigences
- [ ] D4.6 Récapitulatif et confirmation avant envoi
- [ ] D4.7 Document généré : modèle et correspondance champ par champ
- [ ] D4.8 Brouillon / publication, avec version figée pour les dialogues en cours
- [ ] D4.9 **Simulateur** : jouer la démarche entière en texte et en audio avant publication

## D5 — Atelier pulaar (votre outil de validation)
- [ ] D5.1 Écran listant toutes les phrases, avec leur état : validée, à valider, générée
- [ ] D5.2 Saisie du pulaar, écoute immédiate, correction, historique des versions
- [ ] D5.3 Toute phrase produite par le LLM est enregistrée avec sa source française et
      remonte automatiquement dans la file « à valider »
- [ ] D5.4 Export et import du corpus (sauvegarde, travail hors ligne)

## D6 — Les trois démarches
- [ ] D6.1 Extrait de naissance : reprise sur le nouveau modèle, sans régression
- [ ] D6.2 Certificat de mariage : schéma du document, champs, règles, pulaar
- [ ] D6.3 Certificat de décès : schéma du document, champs, règles, pulaar
- [ ] D6.4 Contenu du mode information (RAG) pour les trois, avec coûts et délais réels

## D7 — Vérification
- [ ] D7.1 Tests : moteur de dialogue piloté par une démarche fictive de bout en bout
- [ ] D7.2 Génération de document validée contre le XSD pour les trois démarches
- [ ] D7.3 Essai réel : une démarche créée entièrement depuis l'admin, sans une ligne de code
- [ ] D7.4 Écoute complète d'un dialogue en pulaar validé, par vous

---

## Journal de décisions

---

# Annexe — Définition des deux nouvelles démarches

⚠️ Toutes les règles ci-dessous viennent de sources publiques (voir « Sources »).
**Chacune doit être confirmée par un officier d'état civil** avant mise en service.
Une règle fausse ici produit un acte invalide.

## Nature exacte des deux démarches

| Document | Qui le produit | Rôle dans l'application |
|---|---|---|
| Certificat de mariage constaté | La mairie | **Résultat** de la démarche |
| Certificat médical de décès | Un médecin | **Pièce à fournir**, pas un résultat |
| Acte / extrait de décès | La mairie | **Résultat** de la démarche |

---

## M — Constatation de mariage (résultat : certificat de mariage constaté)

### Champs à collecter

**Pour chacun des deux époux** (donc deux fois) :
| Champ | Type | Question |
|---|---|---|
| civilite | enum (Monsieur / Madame / Mademoiselle) | — |
| prenoms | texte | « Quels sont les prénoms de l'époux ? » |
| nom | texte | « Quel est son nom de famille ? » |
| date_naissance | date | « Quelle est sa date de naissance ? » |
| lieu_naissance | texte | « Où est-il né ? » |
| profession | texte | « Quel est son métier ? » |
| domicile | texte | « Où habite-t-il ? » |
| prenom_nom_pere | texte | « Comment s'appelle son père ? » |
| prenom_nom_mere | texte | « Comment s'appelle sa mère ? » |

**Sur le mariage :**
| Champ | Type | Remarque |
|---|---|---|
| date_celebration | date | Date de la cérémonie coutumière ou religieuse |
| lieu_celebration | texte | |
| option_matrimoniale | enum : monogamie, polygamie limitée à 2, à 3, à 4 | Déclarée publiquement par l'époux |
| regime_matrimonial | enum : séparation des biens, communauté, dotal | |
| dot_montant | nombre, optionnel | À confirmer : figure sur certains actes |

**Témoins — deux, majeurs, présents à la cérémonie :**
nom, profession, domicile, numéro de pièce d'identité.

### Conditions et cas
| Condition | Conséquence |
|---|---|
| Plus de **6 mois** depuis la cérémonie | La mairie n'est plus compétente : **procédure judiciaire obligatoire**. La démarche doit s'arrêter et orienter vers le tribunal |
| Option polygamie choisie | Le régime « communauté » devient impossible : séparation des biens ou régime dotal uniquement |
| Option monogamie | En principe définitive, même après divorce : à annoncer clairement au citoyen |
| Épouse de moins de 16 ans / époux de moins de 18 ans | Dispense du président du tribunal **et** consentement des parents. ⚠️ Âge en débat (projet de relèvement à 18 ans pour les filles) : à confirmer |
| Moins de deux témoins présents à la cérémonie | Acte irrégulier : la démarche ne peut pas aboutir |

### Pièces à photographier
CNI des deux époux, actes de naissance des deux époux, CNI des deux témoins,
dispense d'âge si l'un est mineur, décision de justice si le délai de 6 mois est dépassé.

---

## D — Déclaration de décès (résultat : acte / extrait de décès)

### Champs à collecter

**Le défunt :**
prénoms, nom, sexe, date et lieu de naissance, âge, profession, domicile,
nationalité, situation matrimoniale, prénom et nom du père, prénom et nom de la mère.

**Le décès :**
date, heure, lieu (domicile, hôpital, voie publique…), cause si un certificat médical existe.

**Le déclarant :**
prénoms, nom, numéro de pièce d'identité, lien avec le défunt, domicile.

**Témoins :** deux majeurs, avec nom et numéro de pièce d'identité — **obligatoires en
l'absence de certificat médical**.

### Conditions et cas
| Condition | Conséquence |
|---|---|
| Déclaration dans les **24 heures** (hors week-ends et jours fériés) | Cas normal |
| Au-delà de 24 heures, moins d'un an | Déclaration tardive : toujours recevable en mairie. ⚠️ À confirmer |
| **Plus d'un an** après le décès | **Jugement d'autorisation d'inscription tardive** obligatoire : requête au président du tribunal départemental, certificat de non-inscription, certificat de décès ou deux témoins majeurs, 4 600 FCFA, délai d'environ un mois |
| Mort violente | Procès-verbal de constat d'un officier de police judiciaire **obligatoire** |
| Décès hors structure sanitaire | Pas de certificat médical : deux témoins majeurs obligatoires |
| Défunt étranger décédé au Sénégal | Déclaration obligatoire également |

### Pièces à photographier
Certificat médical de décès (celui du médecin), pièce d'identité du déclarant,
livret de famille s'il existe, pièce d'identité des deux témoins,
procès-verbal de police en cas de mort violente, jugement si plus d'un an.

---

## Sources

- Code de la famille du Sénégal — https://bibliothequejustice.sec.gouv.sn/?code=code_20150720143929
- Texte intégral du Code de la famille — https://www.equalrightstrust.org/ertdocumentbank/CODE_FAMILLE.pdf
- Constatation du mariage, régime juridique — https://fbavocat-sn.com/2025/06/10/la-constatation-du-mariage-dans-le-droit-senegalais-regime-juridique-et-enjeux-de-validite-des-actes/
- Inscription du mariage, délais et procédure judiciaire — https://fbavocat-sn.com/2025/07/14/linscription-du-mariage-au-senegal-delais-legaux-et-procedure-judiciaire-en-cas-domission/
- Déclarer un décès — https://senegalservices.sn/demarche/declarer-un-deces
- Jugement d'autorisation d'inscription tardive de décès — https://rufisqueouest.org/demander-un-jugement-dautorisation-dinscription-tardive-de-deces/
- Démarches de la Ville de Pikine — https://villedepikine.sn/mes-demarches/
- Organisation juridique du mariage au Sénégal — https://publication.lecames.org/index.php/jur/article/download/1851/935
- Rapport ANSD sur l'état civil — https://www.ansd.sn/sites/default/files/2023-03/RAPPORT%20ETAT%20CIVIL%20DEC%202015-BECPD_0.pdf

---

## Annexe — Le formulaire officiel de certificat de décès

Le formulaire est en **deux parties détachables** :

### Partie haute — « CERTIFICAT DE DÉCÈS »
Remplie et close par le médecin ou le personnel de santé. Mention imprimée :
« Partie à détacher et à conserver dans les mairies ». **C'est la seule partie que
l'application doit demander en photo.**

Champs : commune de décès, nom, prénom, date de naissance, sexe, adresse de domicile,
date et heure du décès, existence d'un **obstacle médico-légal** (oui / non), existence
d'un **risque épidémique ou biologique** (oui / non), lieu et date de signature.
Un cadre « RÉSERVÉ À LA MAIRIE » porte le **numéro d'ordre du décès** au registre :
il est attribué par la mairie, donc jamais demandé au citoyen.

### Partie basse — « CERTIFICAT DE CAUSES DE DÉCÈS » — ⛔ NE JAMAIS COLLECTER
Renseignements **confidentiels et anonymes** : cause immédiate, cause initiale,
autopsie, lieu précis du décès. La note du formulaire indique que ce document
« ne peut être communiqué ni en original ni en copie » et « sera détruit » par le
médecin chargé de la statistique.

Conséquences **impératives** pour l'application :
- [ ] La consigne vocale de prise de photo dit explicitement de n'envoyer que la
      partie haute, détachée
- [ ] Aucun champ « cause du décès » n'existe dans le modèle de données
- [ ] Le contrôle qualité de la photo tente de reconnaître la partie basse et la
      **refuse** avec un message clair, au lieu de l'envoyer à la mairie
- [ ] Rien de cette partie n'est stocké, ni transmis au consultant, ni journalisé

### Ce que ça change dans les règles déjà écrites
- « Mort violente » se lit sur le formulaire : **obstacle médico-légal = oui**.
  C'est ce champ, et non une question au citoyen, qui doit déclencher l'exigence du
  procès-verbal de police.
- Le **risque épidémique ou biologique** est une information de santé publique :
  à ne pas exposer dans l'application sans avis de la mairie.
