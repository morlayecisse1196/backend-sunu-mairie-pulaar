"""
Terminologie pulaar de l'état civil, et orthographe adaptée à la synthèse vocale.

Deux problèmes distincts, deux réponses dans ce même module :

1. **Le modèle invente le vocabulaire administratif.** Rien ne lui dit comment
   se disent « extrait de naissance » ou « pièce d'identité » en pulaar : il
   improvise, et improvise différemment d'un tour à l'autre. Le citoyen entend
   trois mots différents pour la même chose dans une seule conversation.
   → `bloc_glossaire()` est injecté dans le prompt du formateur : le
   vocabulaire est imposé, plus deviné.

2. **La synthèse vocale écorche les mots français.** `mms-tts-pul` est un
   modèle *monolingue pulaar* : il applique les règles de lecture du pulaar à
   « mairie » ou « certificat », qui deviennent inaudibles. Les garder en
   français à l'écrit reste juste (c'est le mot officiel) ; ce qui est envoyé
   au synthétiseur, lui, doit être écrit comme le pulaar l'écrirait.
   → `orthographe_tts()`, appliquée dans `tts_client.synthesize_remote`,
   juste avant l'envoi au modèle — jamais sur le texte affiché ou enregistré.

D'OÙ VIENNENT CES TRADUCTIONS
Le champ `source` le dit pour chaque entrée :

- `CORPUS` — tirée de `RESOURCES/MODEL TRADUCTION/dataset_ful_fr_ameliorer.jsonl`
  (6 458 paires français/peul, dont 1 092 d'état civil). La forme retenue est
  celle qui domine nettement le corpus, et le nombre d'occurrences est noté.
  S'aligner dessus garde l'agent cohérent avec le corpus de traduction.
- `PROPOSITION` — écrite ici, sans attestation dans le corpus.

⚠️ Dans les deux cas, ce n'est pas une référence : le corpus a ses propres
erreurs (il traduit par exemple « FCFA » par « dirham »). Chaque entrée porte
donc aussi un `statut`. Tant qu'une entrée est `A_VALIDER`, elle est utilisée
— mieux vaut un mot constant qu'une invention par tour — mais elle reste une
hypothèse. Fiche de relecture : `python scripts/glossaire_pulaar.py`.

Variété visée : pulaar du Fuuta Tooro (Sénégal).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Statut = Literal["valide", "a_valider"]
Source = Literal["corpus", "proposition"]

VALIDE: Statut = "valide"
A_VALIDER: Statut = "a_valider"

CORPUS: Source = "corpus"
PROPOSITION: Source = "proposition"


@dataclass(frozen=True)
class Terme:
    """Un terme administratif et la façon de le dire en pulaar."""

    francais: str
    pulaar: str
    #: Orthographe envoyée au synthétiseur quand le mot français est conservé
    #: tel quel dans la phrase. `None` = rien à corriger (mot déjà pulaar).
    prononciation: str | None = None
    statut: Statut = A_VALIDER
    source: Source = PROPOSITION
    #: Nombre d'occurrences dans le corpus, quand `source == CORPUS`.
    occurrences: int = 0
    note: str = ""


# Ordre indifférent : `orthographe_tts` trie elle-même par longueur décroissante
# pour que « acte de naissance » l'emporte sur « acte ».
TERMES: tuple[Terme, ...] = (
    # ---------- Lieux et institutions ----------
    Terme("mairie", "meeri", "meeri", note="le corpus garde « mairie » ou écrit « maayri » — "
          "écriture retenue ici : « meeri », trop proche de « maayde » (décès) autrement"),
    Terme("commune", "komin", "komin", source=CORPUS, occurrences=24),
    Terme("état civil", "etaa siwil", "etaa siwil", note="corpus : « état civil » gardé en français"),
    Terme("centre d'état civil", "santar etaa siwil", "santar etaa siwil", source=CORPUS, occurrences=30),
    Terme("arrondissement", "arondismaa", "arondismaa"),
    Terme("tribunal", "ñaawirdu", None, source=CORPUS, occurrences=36),
    Terme("hôpital", "opitaal", "opitaal", source=CORPUS, occurrences=32),
    Terme("école", "duɗal", None, source=CORPUS, occurrences=91),
    Terme("quartier", "leegal", None, source=CORPUS, occurrences=60),
    Terme("chef de quartier", "mawɗo leegal", None, source=CORPUS, occurrences=60,
          note="variante du corpus : « jooma saare »"),
    Terme("bureau", "biroo", "biroo"),

    # ---------- Pièces et documents ----------
    Terme("acte de naissance", "deftere wulngo", "akte de nesaas", source=CORPUS, occurrences=92,
          note="variante écartée : « kaayit jibinannde »"),
    Terme(
        "extrait de naissance",
        "deftere wulngo",
        "ekstere de nesaas",
        source=CORPUS,
        occurrences=84,
        note="le corpus ne distingue pas l'extrait de l'acte ; si la mairie les distingue, "
        "il faudra deux termes",
    ),
    Terme("acte de décès", "deftere maayde", "akte de desee", source=CORPUS, occurrences=72),
    Terme("acte de mariage", "deftere dewgal", "akte de mariyaas", source=CORPUS, occurrences=44,
          note="corpus : « acte de mariage » souvent gardé en français"),
    Terme("certificat", "sertifika", "sertifika", source=CORPUS, occurrences=127),
    Terme("certificat de naissance", "sertifika jibineede", "sertifika de nesaas"),
    Terme("certificat de mariage", "sertifika dewgal", "sertifika de mariyaas"),
    Terme("certificat de décès", "sertifika maayde", "sertifika de desee"),
    Terme("certificat médical", "sertifika doktoor", "sertifika medikal"),
    Terme("certificat de résidence", "sertifika hoɗorde", "sertifika hoɗorde", source=CORPUS, occurrences=72),
    Terme("certificat de vie", "sertifika wuurgol", "sertifika wuurgol", source=CORPUS, occurrences=72),
    Terme("certificat d'indigence", "sertifika talla", "sertifika talla", source=CORPUS, occurrences=96),
    Terme("certificat de déménagement", "sertifika dille", "sertifika dille", source=CORPUS, occurrences=54),
    Terme("certificat de célibat", "sertifika resaani", "sertifika de selibaa",
          note="corpus : « célibat » gardé en français ; « a resaani » = « tu n'es pas marié »"),
    Terme("livret de famille", "deftere ɓesngu", "liwure de famiy", source=CORPUS, occurrences=44,
          note="corpus : « livret de famille » aussi gardé en français"),
    Terme("bulletin scolaire", "deftere janngirdu", None, source=CORPUS, occurrences=18),
    Terme("permis de construire", "permis de construire", "permi de konstiruwiir", source=CORPUS,
          occurrences=100, note="corpus : toujours gardé en français"),
    Terme("autorisation", "yamiroore", None, source=CORPUS, occurrences=96),
    Terme("jugement", "ñaawoore", "juusmaa", note="corpus : « jugement » gardé en français"),
    Terme("pièce d'identité", "kaayit ganndinirgal", "pyees didaŋtite",
          note="corpus : gardé en français, ou « jaaynirɗe » (les papiers)"),
    Terme("carte d'identité", "seedee ngenndiijo", "karte didaŋtite", source=CORPUS, occurrences=12,
          note="littéralement « preuve nationale » — peu attesté, à confirmer"),
    Terme("photocopie", "fotokopi", "fotokopi", source=CORPUS, occurrences=66),
    Terme("copie certifiée conforme", "fotokopi laamu", "fotokopi laamu", source=CORPUS, occurrences=60),
    Terme("original", "asli", None, source=CORPUS, occurrences=30),
    Terme("légalisation", "muɗɗugol", "legalisasyoŋ", note="corpus : « légalisation » gardé en français"),
    Terme("signature", "siif", None, source=CORPUS, occurrences=24),
    Terme("timbre", "tembere", "tembere", source=CORPUS, occurrences=30),
    Terme("dossier", "dosiye", "dosiye"),
    Terme("papier", "deftere", None, source=CORPUS, occurrences=175),
    Terme("document", "deftere", None, source=CORPUS, occurrences=157),
    Terme("photo", "fotoo", "fotoo"),
    Terme("numéro", "limoore", "nimeroo", source=CORPUS, occurrences=54),
    Terme("plan", "plan", "plaŋ", source=CORPUS, occurrences=98),

    # ---------- Actes de la vie civile ----------
    # `prononciation` renseignée même quand le mot pulaar existe : si le modèle
    # laisse échapper le mot français, la synthèse doit quand même le dire.
    Terme("naissance", "wulngo", "nesaas", source=CORPUS, occurrences=290),
    Terme("né", "jibinaa", None, source=CORPUS, occurrences=30),
    Terme("date de naissance", "ñalnde jibineede", None, source=CORPUS, occurrences=12),
    Terme("mariage", "dewgal", "mariyaas", source=CORPUS, occurrences=114),
    Terme("marié", "resii", None, source=CORPUS, occurrences=36, note="« a resaani » = « tu n'es pas marié »"),
    Terme("divorce", "ceergal", "diwors", source=CORPUS, occurrences=30),
    Terme("décès", "maayde", "desee", source=CORPUS, occurrences=105),
    Terme("déclaration", "winnditaare", None, source=CORPUS, occurrences=108,
          note="même mot que l'enregistrement au registre"),
    Terme("enregistrement", "winnditaare", None, source=CORPUS, occurrences=42),
    Terme("demande", "ɗaɓɓoore", None, source=CORPUS, occurrences=121, note="verbe : « ɗaɓɓude »"),
    Terme("témoin", "seede", None, source=CORPUS, occurrences=42, note="pluriel : seedeeɓe"),
    Terme("héritage", "ndonu", None, source=CORPUS, occurrences=18),
    Terme("démarche", "golle", None, note="littéralement « les travaux », le mot usuel"),

    # ---------- Personnes ----------
    Terme("nom", "innde", None, statut=VALIDE, source=CORPUS, occurrences=92),
    Terme("père", "baaba", None, statut=VALIDE),
    Terme("mère", "neene", None, statut=VALIDE),
    Terme("enfant", "ɓiɗɗo", None, statut=VALIDE, source=CORPUS, occurrences=217),
    Terme("famille", "ɓesngu", None, statut=VALIDE, source=CORPUS, occurrences=90),
    Terme("époux", "gorko", None, statut=VALIDE, note="litt. « homme »"),
    Terme("épouse", "debbo", None, statut=VALIDE, source=CORPUS, occurrences=42, note="litt. « femme »"),
    Terme("défunt", "maayɗo", None, source=CORPUS, occurrences=60),
    Terme("maire", "jooma meeri", "jooma meeri", source=CORPUS, occurrences=16),

    # ---------- Lieux de vie, biens ----------
    Terme("maison", "galle", None, source=CORPUS, occurrences=82),
    Terme("terrain", "leydi", None, source=CORPUS, occurrences=63),
    Terme("construction", "mahdi", None, source=CORPUS, occurrences=60),
    Terme("résidence", "hoɗorde", None, source=CORPUS, occurrences=102),

    # ---------- Argent ----------
    Terme("franc CFA", "faraŋ seefaa", "faraŋ seefaa"),
    Terme("francs", "faraŋ", "faraŋ"),
    Terme("argent", "kaalis", None, source=CORPUS, occurrences=135),
    Terme("payer", "yoɓde", None, source=CORPUS, occurrences=117),
    Terme("impôts", "njaartu", None, source=CORPUS, occurrences=42),
    Terme("budget", "budget", "budsee", source=CORPUS, occurrences=102, note="corpus : gardé en français"),

    # ---------- Temps ----------
    Terme("aujourd'hui", "hannde", None, statut=VALIDE, source=CORPUS, occurrences=165),
    Terme("demain", "janngo", None, statut=VALIDE, source=CORPUS, occurrences=37),
    Terme("jours", "balɗe", None, statut=VALIDE, source=CORPUS, occurrences=128),
    Terme("semaine", "yontere", None, source=CORPUS, occurrences=19),
    Terme("mois", "lewru", None, statut=VALIDE, source=CORPUS, occurrences=58, note="pluriel : lebbi"),
    Terme("année", "hitaande", None, statut=VALIDE, source=CORPUS, occurrences=180),
)

#: Les entrées encore à relire. Sert à la fiche de validation et, plus tard, à
#: l'atelier pulaar de l'interface admin (étape 4.2 du plan maître).
TERMES_A_VALIDER: tuple[Terme, ...] = tuple(t for t in TERMES if t.statut == A_VALIDER)


def bloc_glossaire() -> str:
    """Le glossaire tel qu'il est injecté dans le prompt du formateur."""
    lignes = [f"- « {t.francais} » se dit « {t.pulaar} »" for t in TERMES]
    return (
        "GLOSSAIRE IMPOSÉ (utilise EXACTEMENT ces mots, n'en invente pas d'autres,\n"
        "et garde le même mot d'un bout à l'autre de la conversation) :\n"
        + "\n".join(lignes)
    )


# Construit une seule fois : les mots les plus longs d'abord, sinon « acte »
# remplacerait le début de « acte de naissance » et laisserait « de naissance »
# derrière lui.
_SUBSTITUTIONS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (
        re.compile(r"(?<!\w)" + re.escape(t.francais) + r"(?!\w)", re.IGNORECASE),
        t.prononciation,
    )
    for t in sorted(TERMES, key=lambda t: len(t.francais), reverse=True)
    if t.prononciation is not None and t.prononciation.lower() != t.francais.lower()
)


def orthographe_tts(texte: str) -> str:
    """
    Réécrit les mots français d'un texte pulaar comme le synthétiseur sait les lire.

    N'est appliqué qu'au texte *envoyé au synthétiseur*. Le texte affiché à
    l'écran et celui enregistré en base gardent l'orthographe officielle : un
    citoyen qui montre son écran à un agent de mairie doit y lire
    « extrait de naissance », pas « ekstere de nesaas ».
    """
    for motif, remplacement in _SUBSTITUTIONS:
        texte = motif.sub(remplacement, texte)
    return texte
