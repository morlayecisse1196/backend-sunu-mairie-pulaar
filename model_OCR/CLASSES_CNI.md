# Classes du modèle YOLO — Extraction CNI

Pipeline entraîné sur un dataset Roboflow (senegal-cards, 166 images), YOLOv8s (run3).
14 classes réparties sur les deux faces de la carte d'identité CEDEAO.

## Recto (6 champs)

| Classe | Signification | Fiabilité | Seuil de confiance |
|---|---|---|---|
| `fname` | Prénoms | ⚠️ Fragile | 0.25 |
| `lname` | Nom de famille | ⚠️ Fragile | 0.25 |
| `dob` | Date de naissance | ✅ Fiable | 0.4 |
| `sex` | Sexe (M/F) | ✅ Fiable | 0.4 |
| `id` | Numéro de la carte d'identité | ✅ Fiable | 0.4 |
| `bp` | Lieu de naissance | ⚠️ Fragile | 0.25 |

## Verso — "Informations électorales" (8 champs)

| Classe | Signification | Fiabilité | Seuil de confiance |
|---|---|---|---|
| `region` | Région | ✅ Fiable | 0.4 |
| `dp` | Département | ✅ Fiable | 0.4 |
| `annot` | Arrondissement | ✅ Fiable | 0.4 |
| `com` | Commune | ✅ Fiable | 0.4 |
| `bureau` | Numéro de bureau de vote | ✅ Fiable | 0.4 |
| `nin` | NIN (Numéro d'Identification Nationale) | ✅ Fiable | 0.4 |
| `numero` | Numéro d'électeur | ✅ Fiable | 0.4 |
| `lieu` | Lieu de vote | ⚠️ Fragile | 0.25 |

## Classes fragiles

`fname`, `lname`, `bp`, `lieu` — marquées `needs_review: true` systématiquement dans le pipeline.
Leur mAP50 mesuré est plus bas (0.63 à 0.89) que les autres classes (généralement > 0.98).
Le consultant doit prioritairement vérifier ces 4 champs dans le formulaire.

## Comportement du pipeline

- Détection sous le seuil de confiance de la classe → champ exclu, retourné `null`, à saisir manuellement.
- Une valeur incohérente pour son type (ex : une date dans un champ censé être un lieu) → `is_valid_format: false`.
- Le pipeline détecte et corrige automatiquement l'orientation de la photo (rotation + effet miroir) avant extraction.
