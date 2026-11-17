# Bancs de mesure du pulaar

Mesures reproductibles, faites sur le VPS de production le 2026-11-17. Chaque
script s'exécute seul et n'écrit rien dans la base.

```bash
cd /opt/sunu/backend
runuser -u sunu -- venv/bin/python evaluation/<script>.py
```

---

## Ce qui a été mesuré, et ce qui en est ressorti

### `banc_comprehension.py` — le pulaar que l'agent COMPREND

Il n'existe **aucun traducteur pulaar → français** dans ce projet : le pulaar du
citoyen est lu directement par le modèle de dialogue, à l'intérieur de prompts
rédigés en français.

Dix réponses en pulaar, une par type de champ, toutes tirées du vocabulaire
validé du projet (glossaire, `pulaar_nombres`, questions déjà relues) :

| Type | Message | Extrait |
|---|---|---|
| âge | `balɗe jeeɗiɗi` | `{valeur: 7, unite: jours}` |
| âge | `duuɓi tati` | `{valeur: 3, unite: annees}` |
| booléen | `eey` / `alaa` | `True` / `False` |
| énumération | `gorko` / `debbo` | `masculin` / `feminin` |
| date | `ñalnde jeeɗiɗi, lewru Sattumbar, hitaande ujunaaje ɗiɗi e noogas e jeegom` | `2026-09-07` |

**10/10.** La compréhension n'est pas le point faible.

### `inspecter_poids_nllb.py` — les quatre matrices divergent-elles ?

Les modèles affinés pèsent 5,6 Go parce qu'ils stockent quatre fois la matrice
d'embeddings (262 M paramètres chacune). Si elles étaient identiques, on
pourrait n'en garder qu'une.

Elles ne le sont pas :

```
model.encoder.embed_tokens.weight   DIFFÈRE sur 100 % des lignes, écart max 1,6e-02
model.decoder.embed_tokens.weight   DIFFÈRE sur 100 % des lignes, écart max 1,7e-02
lm_head.weight                      DIFFÈRE sur 100 % des lignes, écart max 1,2e-01
```

Le *fine-tuning* les a bien mises à jour séparément, faute de liaison. **La
déduplication n'est donc pas applicable** : relier ces poids rendrait un autre
modèle, surtout `lm_head`, la projection de sortie.

### `alleger_nllb.py` — fp32 → bfloat16

bfloat16 garde 8 bits de mantisse : sur des poids de l'ordre de 0,03, l'erreur
d'arrondi est de l'ordre de 1e-4, soit cent fois moins que les écarts entre
matrices qu'il faut préserver.

**5,61 Go → 2,80 Go**, les quatre matrices conservées. Le modèle charge en
4,6 s et occupe **1,99 Go** de mémoire résidente — là où l'évaluation
précédente échouait sur une *segmentation fault*.

### `banc_glossaire.py` — les 78 termes validés, isolés

| Mesure | Résultat |
|---|---|
| rendus à l'identique du glossaire | 3/78 (4 %) |
| mot français laissé tel quel | 36/78 (46 %) |

Avec des répétitions caractéristiques : `mairie mairie`, `bureau bureau bureau`.

> ⚠️ **Ce banc est injuste et doit être lu comme tel.** Un modèle affiné sur des
> phrases est mis en difficulté par des mots isolés. Le banc suivant corrige
> cette impression.

### `banc_phrases_reelles.py` — les vraies questions de l'agent

Les onze questions de l'extrait de naissance, telles qu'elles sont en base,
avec leur pulaar relu par un locuteur comme point de comparaison.

| Mesure | Résultat |
|---|---|
| sorties contenant encore du français | **0/11** |
| sorties ayant ajouté une phrase | **0/11** |
| temps | 12 s pour 11 phrases (~1,1 s chacune) |

```
FR     « Votre enfant est-il un garçon ou une fille ? »
NLLB   « Ɓiɗɗo maa on ko ɓiɗɗo gorko maa debbo ? »
RELU   « Ɓiɗɗo maa ko gorko walla ko debbo? »
```

Sur le domaine pour lequel il a été entraîné — les questions administratives —
le modèle tient. Hors de ce domaine, il laisse du français : `« Bonjour ! Hol
démarche a faalaa waɗde hannde ? »`, et `déclarant` reste tel quel dans une des
onze questions.

---

## Ce qu'un traducteur dédié apporte, et que le LLM n'apporte pas

Le traducteur de production est `google/gemini-2.5-flash` (`MODEL_FORMATTER`).
Mesuré avant stabilisation : trois traductions différentes pour une même
phrase, et une phrase ajoutée à chaque réponse — parce que son prompt lui
demande de *réécrire en dialogue* et d'*ajouter une question*.

NLLB en recherche par faisceau est **déterministe** (vérifié : identique sur
deux appels) et **n'ajoute rien** (0/11). C'est un avantage de nature, pas de
degré.

À cela s'ajoute la souveraineté : le récapitulatif porte le nom de l'enfant,
sa date de naissance et les noms des parents. Pour `constatation_mariage` et
`declaration_deces`, dont le gabarit n'est pas relu, il part aujourd'hui chez
un tiers à chaque conversation.

## Réserve qui demeure

`fuv_Latn` désigne le fulfulde nigérian. Aucun code NLLB n'existe pour le
pulaar du Fuuta Tooro. Les *fine-tunes* partent donc d'une langue voisine mais
distincte — à expliciter dans le mémoire.

Et aucune de ces mesures ne dit si le pulaar produit est BON : cela demande un
locuteur. Elles disent seulement ce qui est vérifiable sans en être un.
