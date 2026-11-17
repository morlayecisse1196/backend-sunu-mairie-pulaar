# Fiche de test — un citoyen pulaarophone, du premier bonjour au dossier

À dire au micro, dans l'ordre. L'agent pose ses questions dans cet ordre-là :
il vient de `demarche_champs.ordre`, pas d'une supposition.

**D'où vient ce pulaar.** Du projet lui-même, jamais inventé : le glossaire
validé (`services/pulaar.TERMES`), les nombres, âges et dates produits par
`services/pulaar_nombres.py`, et les mots des questions déjà relues en base.
Chaque réponse a été vérifiée : l'extracteur en tire la bonne valeur, 10 fois
sur 10 (`evaluation/banc_comprehension.py`).

---

## 1. Mode information

| Vous dites | Ce que ça veut dire | Ce que l'agent doit faire |
|---|---|---|
| `Jam tan` | salutation | Vous saluer en une phrase, et demander ce que vous voulez faire. **Pas un catalogue.** |
| `Deftere wulngo` | extrait de naissance | Citer les pièces et les conditions, dire qu'il ne connaît pas le coût, puis proposer de commencer |
| `Eey` | oui | **Basculer en collecte et poser la première question, sans dire « je n'ai pas compris »** |

> Ces trois tours vérifient d'un coup : la brièveté de la salutation, la
> compréhension du terme pulaar, et la bascule sans excuse.

---

## 2. Mode administratif — les questions, dans l'ordre

| # | L'agent demande | Vous répondez | Sens |
|---|---|---|---|
| 5 | l'âge de l'enfant | `Balɗe jeeɗiɗi` | 7 jours |
| 10 | la commune de naissance | `Ross-Béthio` | nom propre, identique dans les deux langues |
| 20 | **une photo** du certificat de naissance | *envoyez une vraie photo* — ou `Mi alaa ngal` | « je ne l'ai pas » |
| 30 | le nom complet de l'enfant | `Ibrahima Diallo` | nom propre |
| 35 | garçon ou fille | `Gorko` | garçon (`Debbo` pour une fille) |
| 40 | sa date de naissance | `ñalnde jeeɗiɗi, lewru Sattumbar, hitaande ujunaaje ɗiɗi e noogas e jeegom` | 7 septembre 2026 |
| 50 | **votre** nom, comme déclarant | `Modou Diallo` | nom propre |
| 52 | êtes-vous le père | `Eey` | oui (`Alaa` = non, et il demandera alors le nom du père) |
| 60 | **photo** CNI recto | *photo* — ou `Mi alaa ngal` | |
| 61 | **photo** CNI verso | *photo* — ou `Mi alaa ngal` | |
| 70 | le nom de la maman | `Aissatou Ba` | nom propre |
| 80 | sa date de naissance à elle | `ñalnde sappo e ɗiɗi, lewru Marse, hitaande ujunaaje ɗiɗi e teemedere e jeenayi e cappanɗe jeetati` | 12 mars 1998 |
| 90 | les parents sont-ils mariés | `Eey` | oui |
| 100 | livret de famille / certificat de mariage *(facultatif)* | *photo* — ou `Mi alaa ngal` | |
| — | **relecture** : l'agent relit tout et demande si c'est exact | `Eey` | oui → le dossier part, avec son numéro de suivi |

---

## 3. À glisser n'importe où, pour éprouver les correctifs

| Vous dites | Sens | Ce qui doit se passer |
|---|---|---|
| `Jaaraama` | merci | « Je vous en prie », **puis la question reposée** — jamais « je n'ai pas compris » |
| `Jam tan` | bonjour, en pleine collecte | Il salue et repose la question, sans compter d'échec |
| `Mi faamaani` | je n'ai pas compris | Il repose la question **telle quelle**, sans s'excuser à votre place |
| `Alaa` | non | Pour un champ oui/non, c'est une **réponse**, pas une politesse |

> Dire trois politesses d'affilée ne doit **pas** faire abandonner la question
> en cours. C'était le cas avant le 15 novembre.

---

## 4. Ce que vous devez observer

**Le temps de réponse.** Les questions relues en pulaar reviennent en
**0,8 à 1,5 s**. Celles qui passent encore par le traducteur prennent **5 à
25 s**. L'écart s'entend : c'est l'argument le plus concret pour achever la
relecture du mariage et du décès.

**La première réponse d'information est longue** — environ 20 s pour huit
phrases. L'audio arrive au fil de l'eau, donc la première phrase se fait
entendre bien avant la fin. Au second passage, le cache la rend immédiate.

**Un défaut connu, non corrigé :** `Mi alaa ngal` vient du traducteur, pas
d'une relecture. Il est compris, mais un locuteur devrait confirmer la
formulation.

**Corrigé le 17 novembre, à vérifier au passage :**

* la proposition de démarche n'est plus dite qu'**une fois**, par l'agent, qui
  nomme la démarche : « Je vais vous aider pour : Extrait de naissance.
  Voulez-vous que nous commencions maintenant ? ». Le modèle ne la pose plus
  lui-même ;
* **n'importe quelle façon de dire oui** doit lancer la collecte sans excuse —
  `Eey`, mais aussi `Eyyi mbiɗo yiɗi ɗe`. Si « Je n'ai pas bien compris »
  revient à ce moment-là, dites-le moi.

---

## 5. Si quelque chose cloche

```bash
ssh root@sunu-mairie.duckdns.org
journalctl -u sunu-backend -f
```

Une ligne `tour.duree` est écrite à chaque tour, avec le détail :
`reflexion` (le modèle), `persistance` (la base), `parole` (traduction et
synthèse). Elle dit immédiatement **où** le temps est passé.
