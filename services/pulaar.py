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

from services import pulaar_nombres

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
    Terme("mairie", "meeri", "meeri", statut=VALIDE, note="le corpus garde « mairie » ou écrit « maayri » — "
          "écriture retenue ici : « meeri », trop proche de « maayde » (décès) autrement"),
    Terme("commune", "komin", "komin", statut=VALIDE, source=CORPUS, occurrences=24),
    Terme("état civil", "etaa siwil", "etaa siwil",statut=VALIDE, note="corpus : « état civil » gardé en français"),
    Terme("centre d'état civil", "santar etaa siwil", "santar etaa siwil", statut=VALIDE, source=CORPUS, occurrences=30),
    Terme("arrondissement", "arondismaa", "arondismaa", statut=VALIDE),
    Terme("tribunal", "ñaawirdu", None, statut=VALIDE, source=CORPUS, occurrences=36),
    Terme("hôpital", "opitaal", "opitaal", statut=VALIDE, source=CORPUS, occurrences=32),
    Terme("école", "ékole", None, statut=VALIDE, source=CORPUS, occurrences=91),
    Terme("quartier", "leegal", None, statut=VALIDE, source=CORPUS, occurrences=60),
    Terme("chef de quartier", "mawɗo leegal", None, statut=VALIDE, source=CORPUS, occurrences=60,
          note="variante du corpus : « jooma saare »"),
    Terme("bureau", "biroo", "biroo", statut=VALIDE),

    # ---------- Pièces et documents ----------
    Terme("acte de naissance", "deftere wulngo", "akte de nesaas", statut=VALIDE, source=CORPUS, occurrences=92,
          note="variante écartée : « kaayit jibinannde »"),
    Terme(
        "extrait de naissance",
        "deftere wulngo",
        "ekstere de nesaas", statut=VALIDE,
        source=CORPUS,
        occurrences=84,
        note="le corpus ne distingue pas l'extrait de l'acte ; si la mairie les distingue, "
        "il faudra deux termes",
    ),
    Terme("acte de décès", "deftere maayde", "akte de desee", statut=VALIDE, source=CORPUS, occurrences=72),
    Terme("acte de mariage", "deftere dewgal", "akte de mariyaas", statut=VALIDE, source=CORPUS, occurrences=44,
          note="corpus : « acte de mariage » souvent gardé en français"),
    Terme("certificat", "sertifika", "sertifika", statut=VALIDE, source=CORPUS, occurrences=127),
    Terme("certificat de naissance", "sertifika jibineede", "sertifika de nesaas", statut=VALIDE),
    Terme("certificat de mariage", "sertifika dewgal", "sertifika de mariyaas", statut=VALIDE),
    Terme("certificat de décès", "sertifika maayde", "sertifika de desee", statut=VALIDE),
    Terme("certificat médical", "sertifika doktoor", "sertifika medikal",statut=VALIDE),
    Terme("certificat de résidence", "sertifika hoɗorde", "sertifika hoɗorde", statut=VALIDE, source=CORPUS, occurrences=72),
    Terme("certificat de vie", "sertifika wuurgol", "sertifika wuurgol", statut=VALIDE, source=CORPUS, occurrences=72),
    Terme("certificat d'indigence", "sertifika talla", "sertifika talla", statut=VALIDE, source=CORPUS, occurrences=96),
    Terme("certificat de déménagement", "sertifika dille", "sertifika dille", statut=VALIDE, source=CORPUS, occurrences=54),
    Terme("certificat de célibat", "sertifika resaani", "sertifika de selibaa", statut=VALIDE,
          note="corpus : « célibat » gardé en français ; « a resaani » = « tu n'es pas marié »"),
    Terme("livret de famille", "deftere ɓesngu", "liwure de famiy", statut=VALIDE, source=CORPUS, occurrences=44,
          note="corpus : « livret de famille » aussi gardé en français"),
    Terme("bulletin scolaire", "deftere janngirdu", None, statut=VALIDE, source=CORPUS, occurrences=18),
    Terme("permis de construire", "permis de construire", "permi de konstiruwiir", statut=VALIDE, source=CORPUS,
          occurrences=100, note="corpus : toujours gardé en français"),
    Terme("autorisation", "yamiroore", None, statut=VALIDE, source=CORPUS, occurrences=96),
    Terme("jugement", "ñaawoore", "juusmaa", statut=VALIDE, note="corpus : « jugement » gardé en français"),
    Terme("pièce d'identité", "kaayit ganndinirgal", "pyees didaŋtite", statut=VALIDE,
          note="corpus : gardé en français, ou « jaaynirɗe » (les papiers)"),
    Terme("carte d'identité", "seedee ngenndiijo", "karte didaŋtite", statut=VALIDE, source=CORPUS, occurrences=12,
          note="littéralement « preuve nationale » — peu attesté, à confirmer"),
    Terme("photocopie", "fotokopi", "fotokopi", statut=VALIDE, source=CORPUS, occurrences=66),
    Terme("copie certifiée conforme", "fotokopi laamu", "fotokopi laamu", statut=VALIDE, source=CORPUS, occurrences=60),
    Terme("original", "original", None, source=CORPUS, occurrences=30,statut=VALIDE, note="corpus : gardé en français"),
    Terme("légalisation", "muɗɗugol", "legalisasyoŋ", statut=VALIDE, note="corpus : « légalisation » gardé en français"),
    Terme("signature", "siif", None, statut=VALIDE, source=CORPUS, occurrences=24),
    Terme("timbre", "tembere", "tembere", statut=VALIDE, source=CORPUS, occurrences=30),
    Terme("dossier", "dosiye", "dosiye", statut=VALIDE),
    Terme("papier", "deftere", None, statut=VALIDE, source=CORPUS, occurrences=175),
    Terme("document", "deftere", None, statut=VALIDE, source=CORPUS, occurrences=157),
    Terme("photo", "fotoo", "fotoo", statut=VALIDE),
    Terme("numéro", "limoore", "nimeroo", statut=VALIDE, source=CORPUS, occurrences=54),
    Terme("plan", "plan", "plaŋ", statut=VALIDE, source=CORPUS, occurrences=98),

    # ---------- Actes de la vie civile ----------
    # `prononciation` renseignée même quand le mot pulaar existe : si le modèle
    # laisse échapper le mot français, la synthèse doit quand même le dire.
    Terme("naissance", "wulngo", "nesaas", statut=VALIDE, source=CORPUS, occurrences=290),
    Terme("né", "jibinaa", None, statut=VALIDE, source=CORPUS, occurrences=30),
    Terme("date de naissance", "ñalnde jibineede", None, statut=VALIDE, source=CORPUS, occurrences=12),
    Terme("mariage", "dewgal", "mariyaas", statut=VALIDE, source=CORPUS, occurrences=114),
    Terme("marié", "resii", None, statut=VALIDE, source=CORPUS, occurrences=36, note="« a resaani » = « tu n'es pas marié »"),
    Terme("divorce", "ceergal", "diwors", statut=VALIDE, source=CORPUS, occurrences=30),
    Terme("décès", "maayde", "desee", statut=VALIDE, source=CORPUS, occurrences=105),
    Terme("déclaration", "winnditaare", None, statut=VALIDE, source=CORPUS, occurrences=108,
          note="même mot que l'enregistrement au registre"),
    Terme("enregistrement", "winnditaare", None, statut=VALIDE, source=CORPUS, occurrences=42),
    Terme("demande", "ɗaɓɓoore", None, statut=VALIDE, source=CORPUS, occurrences=121, note="verbe : « ɗaɓɓude »"),
    Terme("témoin", "seede", None, statut=VALIDE, source=CORPUS, occurrences=42, note="pluriel : seedeeɓe"),
    Terme("héritage", "ndonu", None, statut=VALIDE, source=CORPUS, occurrences=18),
    Terme("démarche", "golle", None, statut=VALIDE, note="littéralement « les travaux », le mot usuel"),

    # ---------- Personnes ----------
    Terme("nom", "innde", None, statut=VALIDE, source=CORPUS, occurrences=92),
    Terme("père", "baaba", None, statut=VALIDE),
    Terme("mère", "neene", None, statut=VALIDE),
    Terme("enfant", "ɓiɗɗo", None, statut=VALIDE, source=CORPUS, occurrences=217),
    Terme("famille", "ɓesngu", None, statut=VALIDE, source=CORPUS, occurrences=90),
    Terme("époux", "gorko", None, statut=VALIDE, note="litt. « homme »"),
    Terme("épouse", "debbo", None, statut=VALIDE, source=CORPUS, occurrences=42, note="litt. « femme »"),
    Terme("défunt", "maayɗo", None, statut=VALIDE, source=CORPUS, occurrences=60),
    Terme("maire", "jooma meeri", "jooma meeri", statut=VALIDE, source=CORPUS, occurrences=16),

    # ---------- Lieux de vie, biens ----------
    Terme("maison", "galle", None, statut=VALIDE, source=CORPUS, occurrences=82),
    Terme("terrain", "leydi", None, statut=VALIDE, source=CORPUS, occurrences=63),
    Terme("construction", "mahdi", None, statut=VALIDE, source=CORPUS, occurrences=60),
    Terme("résidence", "hoɗorde", None, statut=VALIDE, source=CORPUS, occurrences=102),

    # ---------- Argent ----------
    Terme("franc CFA", "faraŋ seefaa", "faraŋ seefaa", statut=VALIDE, source=CORPUS, occurrences=120),
    Terme("francs", "faraŋ", "faraŋ", statut=VALIDE),
    Terme("argent", "kaalis", None, statut=VALIDE, source=CORPUS, occurrences=135),
    Terme("payer", "yoɓde", None, statut=VALIDE, source=CORPUS, occurrences=117),
    Terme("impôts", "njaartu", None, statut=VALIDE, source=CORPUS, occurrences=42),
    Terme("budget", "budget", "budsee", statut=VALIDE, source=CORPUS, occurrences=102, note="corpus : gardé en français"),

    # ---------- Temps ----------
    Terme("aujourd'hui", "hannde", None, statut=VALIDE, source=CORPUS, occurrences=165),
    Terme("demain", "janngo", None, statut=VALIDE, source=CORPUS, occurrences=37),
    Terme("jours", "balɗe", None, statut=VALIDE, source=CORPUS, occurrences=128),
    Terme("semaine", "yontere", None, statut=VALIDE, source=CORPUS, occurrences=19),
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


def bloc_comprehension() -> str:
    """
    Le glossaire dans l'AUTRE SENS : pour COMPRENDRE le citoyen.

    POURQUOI IL A FALLU L'ÉCRIRE

    `bloc_glossaire()` n'est injecté que dans le prompt du traducteur, qui va
    du français vers le pulaar. L'agent savait donc DIRE « deftere wulngo »
    sans savoir le COMPRENDRE. Joué en pulaar de bout en bout, le dialogue
    répondait ceci au deuxième tour :

        citoyen : « Deftere wulngo »
        agent   : « Je ne comprends pas ce que tu veux dire par "Deftere
                    wulngo". Peux-tu me dire quelle démarche tu souhaites
                    faire ? »

    — à propos du terme qui figure dans son propre glossaire validé. Douze
    tours en pulaar, zéro champ rempli : un locuteur pulaar ne pouvait même
    pas commencer une démarche.

    Les nombres, le oui/non et les unités de durée viennent de
    `services/pulaar_nombres.py`, c'est-à-dire de ce que l'agent PRONONCE
    lui-même. Il doit au minimum reconnaître ce qu'il dit.
    """
    # Plusieurs termes français partagent un même mot pulaar (« acte de
    # naissance » et « extrait de naissance » se disent tous deux « deftere
    # wulngo »). On les regroupe plutôt que de donner au modèle deux lignes
    # qui se contredisent.
    par_pulaar: dict[str, list[str]] = {}
    for terme in TERMES:
        if terme.pulaar.lower() == terme.francais.lower():
            continue  # mot gardé en français : rien à expliquer
        par_pulaar.setdefault(terme.pulaar, []).append(terme.francais)

    lignes = [f"- « {mot} » = {' / '.join(sens)}" for mot, sens in sorted(par_pulaar.items())]

    from services import pulaar_nombres as nombres  # local : évite un cycle d'import

    chiffres = ", ".join(f"« {mot} » = {valeur}"
                         for valeur, mot in sorted(nombres.UNITES.items()) if valeur > 0)
    # Même regroupement que pour les termes : « duuɓi » traduit « ans »,
    # « année » et « années ». Trois lignes séparées diraient au modèle trois
    # choses pour un seul mot.
    durees_par_mot: dict[str, set[str]] = {}
    for francais, mot in nombres.UNITES_AGE.items():
        durees_par_mot.setdefault(mot, set()).add(francais)
    durees = ", ".join(f"« {mot} » = {' / '.join(sorted(sens))}"
                       for mot, sens in sorted(durees_par_mot.items()))

    return "\n".join([
        "LE CITOYEN PEUT PARLER PULAAR. Sa parole arrive par une transcription "
        "automatique, donc parfois approximative. Voici de quoi la comprendre : ne "
        "réponds JAMAIS que tu ne comprends pas un mot qui figure ci-dessous.",
        "",
        "Mots pulaar et leur sens :",
        *lignes,
        "",
        f"Oui / non : « {nombres.OUI} » = oui, « {nombres.NON} » = non.",
        f"Chiffres : {chiffres} ; « {nombres.DIX} » = 10, « {nombres.VINGT} » = 20, "
        f"« {nombres.DIZAINES} » = les dizaines, « {nombres.CENT} » = 100, "
        f"« {nombres.MILLE} » = 1000 ; « {nombres.ET} » relie les nombres.",
        f"Durées : {durees}.",
        "Sexe : « gorko » = masculin (garçon, homme), « debbo » = féminin (fille, femme).",
        "Dates : « ñalnde » = le jour, « lewru » = le mois, « hitaande » = l'année.",
        "Un nom de personne ou de lieu se dit tel quel dans les deux langues.",
    ])


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

# ---------------------------------------------------------------------------
# Caractères que le modèle vocal ne connaît pas
# ---------------------------------------------------------------------------
#
# Le vocabulaire de `rnjema-unima/mms-tts-pul-baseline` compte 41 entrées :
#
#     ' ' ' 0..9 a b c d e f g h i j k l m n o p r s t u w y | ŋ ƴ ɓ ɗ ‐ —
#
# Tout caractère absent est SILENCIEUSEMENT SUPPRIMÉ par le tokeniseur — pas
# de `<unk>`, pas d'erreur. Mesuré : « ñalnde jeeɗiɗi » donne 27 jetons,
# « nalnde jeedidi » en donne 29 ; le « ñ » n'en produit aucun.
#
# C'est grave ici parce que « ñ » est dans « ñalnde » (jour) et « ñalawma »,
# donc dans CHAQUE date énoncée par `pulaar_nombres.date_pulaar` : sans cette
# table, la correction des nombres resterait à moitié inaudible.
#
# ⚠️ Ne couvre volontairement QUE ce que le code pulaar produit lui-même. Les
# voyelles accentuées du français (« à », « é »…) et les lettres q, v, x, z
# manquent aussi au vocabulaire et sont donc muettes elles aussi — mais les
# remplacer relève du glossaire (`TERMES` ci-dessus), terme par terme et relu,
# pas d'une table de correspondance devinée.
CARACTERES_ABSENTS: tuple[tuple[str, str], ...] = (
    # « ny » est l'autre graphie courante de la même nasale palatale en
    # pulaar : ce n'est pas une approximation, c'est la même lettre écrite
    # autrement. « n » et « y » sont tous deux dans le vocabulaire.
    ("ñ", "ny"),
    ("Ñ", "ny"),
    # Le tiret ASCII est absent (le vocabulaire n'a que « ‐ » U+2010 et
    # « — » U+2014) : un espace sépare au moins les deux mots, là où le tiret
    # supprimé les collait.
    ("-", " "),
)

_ESPACES = re.compile(r"\s{2,}")


def caracteres_tts(texte: str) -> str:
    """Remplace les caractères absents du vocabulaire du modèle vocal."""
    for absent, remplacement in CARACTERES_ABSENTS:
        texte = texte.replace(absent, remplacement)
    return _ESPACES.sub(" ", texte).strip()


def texte_pour_synthese(texte: str) -> str:
    """
    Le texte tel qu'il part RÉELLEMENT au modèle vocal.

    Point d'entrée unique de la préparation : `tts_client.synthesize_remote`
    l'applique avant l'envoi, et `services.catalogue_audio.cle_phrase` s'en
    sert pour l'empreinte du cache. Les deux DOIVENT passer par ici, sinon le
    fichier rangé sur le disque ne correspond plus à sa clé.

    L'ordre des trois étapes n'est pas indifférent :

    1. `enoncer_nombres` — les chiffres d'abord, parce qu'un montant se
       reconnaît à son unité française (« 200 francs CFA »). Après
       `orthographe_tts`, cette unité serait déjà devenue « faraŋ CFA » et la
       règle produirait « teemedde ɗiɗi faraŋ seefaa CFA », avec un « CFA » en
       trop.
    2. `orthographe_tts` — les mots français restants.
    3. `caracteres_tts` — en dernier, sur le texte définitif : les deux étapes
       précédentes produisent elles-mêmes des caractères à corriger
       (« ñalnde » vient de l'étape 1).
    """
    return caracteres_tts(orthographe_tts(pulaar_nombres.enoncer_nombres(texte or "")))
