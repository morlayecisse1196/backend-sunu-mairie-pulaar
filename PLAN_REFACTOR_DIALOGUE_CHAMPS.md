# Plan — Contrôleur de champ générique pour le dialogue administratif

> Document de conception, **rien n'est codé**. Répond à la limite discutée : le LLM pilote aujourd'hui
> seul les 8 slots d'un coup, sans validation déterministe ni garantie qu'il traite le bon champ, et le
> schéma est codé en dur pour l'extrait de naissance seul. Objectif : un contrôleur **codé** qui pilote
> champ par champ, valide chaque réponse avant d'avancer, bloque réellement sur les documents attendus, et
> se généralise à une future démarche par de la donnée, pas du code.

---

## 1. Principe

**Aujourd'hui** : un appel LLM par tour reçoit l'état complet des 8 slots et décide seul quoi faire.
**Cible** : le code détermine, à chaque tour, un **champ courant unique** (le premier champ obligatoire
encore vide, dans un ordre défini pour la démarche), et n'interroge le LLM que sur *ce champ précis* — il
ne peut structurellement plus écrire ailleurs. Le code valide la valeur extraite avant de l'accepter ; en
cas d'échec, il reformule et reboucle sur le **même** champ plutôt que d'avancer.

```
tant que la démarche n'est pas complète :
    étape_courante = première étape non satisfaite (champ OU document, ordre défini par la démarche)
    si étape_courante est un CHAMP :
        poser la question du champ (reformulée si tentative précédente invalide)
        extraction = LLM_ciblé(champ, message du citoyen)   # ne voit QUE ce champ
        (valide, valeur, raison) = valider_valeur(champ.type, extraction.valeur, champ.regle_validation)
        si valide : enregistrer, avancer
        sinon : compteur_echecs[champ] += 1 ; si seuil atteint -> cas particulier ; sinon reformuler
    si étape_courante est un DOCUMENT :
        si document déjà reçu (vérifié en base, pas juste "déjà demandé à voix haute") : avancer
        sinon : rappeler la demande (ou proposer "je ne l'ai pas" -> cas particulier, pas de blocage infini)
```

---

## 2. Nouveau modèle de données (migrations)

```sql
-- Définition ordonnée des champs d'une démarche (remplace le schéma Python codé en dur)
create table public.demarche_champs (
    id                 uuid primary key default gen_random_uuid(),
    type_demarche      text not null,
    ordre              integer not null,
    nom_champ          text not null,          -- garde les noms actuels (nom_mere, date_naissance_mere, ...)
    type_valeur        text not null
        check (type_valeur in ('texte', 'date', 'nombre', 'booleen', 'age', 'enum')),
    question           text not null,          -- question par défaut posée au citoyen
    regle_validation   text,                   -- nom d'un validateur enregistré (ex. "date_iso_passee")
    obligatoire        boolean not null default true,
    unique (type_demarche, nom_champ)
);

-- Documents attendus, intercalés dans le même flux ordonné
create table public.demarche_documents (
    id                 uuid primary key default gen_random_uuid(),
    type_demarche      text not null,
    ordre              integer not null,       -- même espace d'ordre que demarche_champs (entrelacés)
    type_document      text not null,          -- ex. "certificat_naissance"
    obligatoire        boolean not null default true,
    condition_champ    text,                   -- ex. "parents_maries" — document non demandé si ce champ est faux
    apres_champ        text                    -- nom_champ après lequel ce document doit être demandé
);
```

**Seed pour `extrait_naissance`** : les 7 champs de `SLOTS_REQUIS_RELECTURE` actuels + `age_enfant`
(type `age`, structure `{valeur, unite}` — validateur dédié réutilisant `normaliser_age` existant), dans
le même ordre que les exemples de dialogue déjà utilisés pour les tests ; `certificat_naissance` après
`commune_naissance`, `cni_declarant` après `nom_declarant`, `livret_famille`/`certificat_mariage`
optionnel après `parents_maries` (condition : `parents_maries = true`, sinon sauté).

Ajouter une démarche future = insérer des lignes dans ces deux tables, aucune modification de code.

---

## 3. Nouveau module : contrôleur de champ (`slot_controller.py`)

Fonctions pures/repo, testables indépendamment du LLM et du WebSocket :

- `charger_definition_demarche(type_demarche) -> list[ChampDefinition]` — lit `demarche_champs` ordonné.
- `charger_documents_demarche(type_demarche) -> list[DocumentDefinition]` — lit `demarche_documents`.
- `determiner_etape_courante(slots, documents_recus, definition) -> Etape | None` — premier champ **ou**
  document non satisfait dans l'ordre combiné ; `None` si tout est complet (déclenche RG7).
- `valider_valeur(type_valeur, valeur_brute, regle_validation) -> (bool, valeur_normalisee, raison_erreur)`
  — un validateur par type :
  - `texte` : non vide, longueur raisonnable.
  - `date` : parsable, cohérente (ex. `date_naissance_enfant` pas dans le futur).
  - `nombre` : numérique, plage plausible.
  - `booleen` : oui/non/vrai/faux détecté sans ambiguïté.
  - `age` : réutilise `dialogue_engine.normaliser_age` (déjà existant) — valeur + unité reconnue.
  - `enum` : valeur dans une liste autorisée (`regle_validation` = liste séparée par `|`).

Ces validateurs sont du **code déterministe pur**, zéro appel LLM — testables unitairement sans dépendre
d'OpenRouter (contrairement à tout le reste du dialogue aujourd'hui).

---

## 4. Prompt LLM ciblé par champ (`prompts.py`)

Remplace `SYSTEM_PROMPT_GENERATOR_ADMINISTRATIF` (monolithique, 8 slots à la fois) par :

- **Un seul système prompt générique** (indépendant de la démarche) : *"Tu poses une question précise
  fournie ci-dessous. Extrais une valeur SEULEMENT si la réponse du citoyen y répond clairement ; si ce
  n'est pas le cas (hors sujet, ambigu, réponse à une autre question), renvoie `valeur: null` et
  `reponse_valide: false` avec une reformulation qui explique *pourquoi* tu reposes la question — jamais
  la même phrase mot pour mot deux fois de suite."*
- **Un schéma de sortie structuré scopé à un seul champ** : `{valeur, reponse_valide: bool, reponse: string}`
  — impossible pour le LLM d'écrire dans un autre slot, il n'en voit aucun autre.
- `build_prompt_champ_cible(champ: ChampDefinition, message: str, derniere_raison_invalide: str|None) -> str`
  — injecte la question du champ courant, le message du citoyen, et (si tentative précédente échouée) la
  raison, pour que la reformulation ait du contexte au lieu de boucler à l'identique.

C'est exactement ce qui règle ton scénario (date de la mère vs. date du père donnée par erreur) : le LLM
ne reçoit **que** la question sur la mère, il ne peut plus structurellement "caser" la réponse ailleurs —
et le validateur de date, côté code, peut aussi être renforcé (cohérence d'âge : mère née avant l'enfant,
etc.) sans dépendre du LLM du tout.

---

## 5. Document réellement bloquant

Différence clé avec l'existant : un document n'est plus marqué "demandé" dès qu'il est mentionné à voix
haute, mais l'étape correspondante n'est validée que lorsque `list_documents(dossier_id)` **contient
effectivement** une ligne de ce type — vérifié à **chaque tour suivant**, pas une seule fois. Si rien n'est
arrivé, l'agent relance (reformulé, pas répété mot pour mot) au lieu d'avancer.

Garde-fou anti-blocage infini : après N rappels sans réception, proposer explicitement "je ne l'ai pas
sous la main" comme réponse valide → crée un `cas_particulier` (`type_incident="document_inattendu"` ou
un nouveau type `"document_indisponible"`) et avance quand même si le document n'est pas strictement
bloquant pour le `cas_legal` en cours (RG6, déjà la logique existante de `document_generator.py` pour les
champs obligatoires) — jamais une boucle sans issue.

---

## 6. Intégration dans la boucle WebSocket (`main.py`)

Le bloc actuel `elif etat["mode"] == "administratif":` (la plus grosse portion du handler WS) est remplacé
par un appel à un nouvel orchestrateur unique :

```python
resultat = await traiter_tour_administratif(etat, message, headers)
# resultat : { reponse_fr, document_attendu?, phase_suivante, cas_particulier_cree? }
```

qui encapsule toute la boucle de contrôle (§1). `main.py` ne fait plus que du "plumbing" WebSocket (statuts,
envoi des messages, TTS) — la logique de contrôle vit dans `slot_controller.py`, testable sans WebSocket.

La bascule information→administratif (Tâche B.3), la relecture RG7 (`construire_recapitulatif`,
inchangée pour l'instant — §9 ci-dessous), la confirmation finale et le statut `bloque` (Tâche G.3) restent
telles quelles : ce refactor ne touche que la **collecte** des champs, pas ce qui l'entoure.

---

## 7. Compatibilité avec l'existant (important — zéro régression visée)

- **Les noms de champs restent identiques** pour `extrait_naissance` (`nom_mere`, `date_naissance_mere`,
  etc.) — seule la *définition* de la liste des champs déménage du Python vers la table
  `demarche_champs`, avec les mêmes clés. `dossiers.slots` (JSONB) ne change pas de forme.
- **C.3** (pré-remplissage formulaire consultant), **D.2** (résolution XSD), **E.2** (analyse assistant)
  lisent `dossiers.slots` par nom de clé — aucun changement requis de leur côté.
- `dossier_complet()`/`slots_manquants()` (`dialogue_engine.py`) : réécrites pour lire
  `demarche_champs` au lieu de la constante `SLOTS_REQUIS_RELECTURE` codée en dur, mais retournent le même
  résultat pour `extrait_naissance` (mêmes champs, même sémantique) — aucune régression fonctionnelle
  attendue, à vérifier par les tests existants (`test_relecture_confirmation.py`, `test_bascule_administratif.py`)
  qui doivent continuer à passer sans modification.

---

## 8. Découpage en tâches (même format que le roadmap existant)


| Tâche                | Contenu                                                                                                                     | Validation manuelle                                                                                       |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| **H.1**               | Migration + seed`demarche_champs`/`demarche_documents` pour `extrait_naissance`                                             | Les deux tables contiennent exactement les 8 champs + 2-3 documents actuels, dans le bon ordre            |
| **H.2**               | `valider_valeur()` par type, testé unitairement sans LLM                                                                   | Cas valides/invalides couverts pour chaque type (date future rejetée, âge incohérent rejeté, etc.)    |
| **H.3**               | Prompt LLM ciblé par champ (nouveau schéma structuré à 1 champ)                                                         | Un appel réel sur un champ isolé retourne bien`reponse_valide=false` sur une réponse hors sujet        |
| **H.4**               | `slot_controller.py` — orchestrateur complet (boucle §1, y compris document bloquant)                                     | Test bout en bout : dossier complété champ par champ, reformulation vérifiée sur réponse invalide    |
| **H.5**               | Intégration dans`main.py` (remplace le bloc existant)                                                                      | `test_relecture_confirmation.py`/`test_bascule_administratif.py` repassent sans modification              |
| **H.6**               | Escalade : seuil d'échecs par champ → cas particulier + reformulation progressive (pas la même phrase 2x)                | 3 réponses invalides de suite sur un champ → cas particulier créé, dialogue ne boucle pas à l'infini |
| **H.7** *(optionnel)* | Génère`construire_recapitulatif()` dynamiquement depuis `demarche_champs` (aujourd'hui figé pour l'extrait de naissance) | La relecture RG7 fonctionne aussi pour une démarche test à 2 champs fictifs                             |

---

## 9. Risques et points d'attention

- **Latence** : un appel LLM ciblé par champ au lieu d'un gros appel par tour peut faire *plus* d'appels
  au total sur un dossier complexe, mais chaque appel est plus petit (schéma réduit, moins de tokens) — à
  mesurer à l'usage, pas évident a priori dans quel sens ça penche.
- **Naturel de la reformulation** : éviter de répéter la question mot pour mot après un échec (agaçant à
  l'oral) — le prompt ciblé (§4) doit varier la formulation à partir de la raison d'échec, pas juste
  renvoyer le même gabarit.
- **Sessions en cours au déploiement** : l'état de dialogue est en mémoire (`dossier_sessions`), jamais
  persisté — un redémarrage serveur les perd déjà aujourd'hui, donc pas de migration de session à prévoir,
  juste un redémarrage propre.
- **RG7 reste figée pour l'instant** (§7, Tâche H.7 optionnelle) — ce refactor rend la *collecte*
  générique, pas encore la *relecture finale*, qui reste un gabarit `extrait_naissance` tant que H.7 n'est
  pas faite. À ne pas présenter comme "100% générique" tant que H.7 n'est pas construite.
