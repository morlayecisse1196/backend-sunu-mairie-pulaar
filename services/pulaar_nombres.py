"""
Nombres, dates, âges et montants énoncés en pulaar, sans modèle (étape 3.2).

POURQUOI

Le récapitulatif est le moment le plus important du dialogue : le citoyen y
confirme des informations qui finiront sur un acte d'état civil. Il contient
forcément des valeurs — une date, un nom, un âge — qu'aucune phrase figée ne
peut contenir d'avance.

Jusqu'ici, tout partait au traducteur, y compris les chiffres. Le modèle
lisait « 2026-09-07 » comme il pouvait, différemment à chaque fois, et la
synthèse vocale prononçait ce qu'elle voulait de « 07 ». Un citoyen qui ne lit
pas doit ENTENDRE « ñalnde jeeɗiɗi, lewru Sattumbar, hitaande ujunaaje ɗiɗi e
noogas e jeegom » — pas une suite de chiffres.

Ces fonctions sont déterministes : même entrée, même sortie, toujours. Aucun
appel réseau, aucun modèle.

⚠️ STATUT
Les noms de nombres suivent le pulaar du Fuuta Tooro et sont corroborés par le
corpus de traduction (`teemedde ɗiɗi` pour 200, `lebbi tati` pour trois mois).
Les NOMS DE MOIS, eux, sont les emprunts français usuels au Sénégal : ils
doivent être relus comme le reste (`scripts/atelier_pulaar.py`).
"""
from __future__ import annotations

import re
from datetime import date, datetime

# ---------------------------------------------------------------------------
# Nombres
# ---------------------------------------------------------------------------

UNITES = {
    0: "meere",
    1: "go'o",
    2: "ɗiɗi",
    3: "tati",
    4: "nayi",
    5: "joyi",
    6: "jeegom",
    7: "jeeɗiɗi",
    8: "jeetati",
    9: "jeenayi",
}

DIX = "sappo"
VINGT = "noogas"
#: 30 à 90 : « cappanɗe » (dizaines) suivi du chiffre.
DIZAINES = "cappanɗe"
CENT = "teemedere"
CENTS = "teemedde"
MILLE = "ujunere"
MILLES = "ujunaaje"

ET = "e"


def _sous_cent(nombre: int) -> str:
    if nombre < 10:
        return UNITES[nombre]
    if nombre < 20:
        reste = nombre - 10
        return DIX if reste == 0 else f"{DIX} {ET} {UNITES[reste]}"
    dizaine, reste = divmod(nombre, 10)
    tete = VINGT if dizaine == 2 else f"{DIZAINES} {UNITES[dizaine]}"
    return tete if reste == 0 else f"{tete} {ET} {UNITES[reste]}"


def _sous_mille(nombre: int) -> str:
    centaines, reste = divmod(nombre, 100)
    if centaines == 0:
        return _sous_cent(reste)
    tete = CENT if centaines == 1 else f"{CENTS} {UNITES[centaines]}"
    return tete if reste == 0 else f"{tete} {ET} {_sous_cent(reste)}"


def nombre(valeur: int) -> str:
    """
    Un entier énoncé en pulaar, de 0 à 999 999.

    Au-delà, les chiffres sont rendus tels quels plutôt qu'approximés : un
    numéro d'acte à dix-neuf chiffres ne se dit pas, il s'épelle (voir
    `chiffre_par_chiffre`).
    """
    entier = int(valeur)
    if entier < 0:
        return f"{'les'} {nombre(-entier)}"  # cas théorique : aucun champ n'accepte de négatif
    if entier < 1000:
        return _sous_mille(entier)
    if entier >= 1_000_000:
        return str(entier)
    milliers, reste = divmod(entier, 1000)
    tete = MILLE if milliers == 1 else f"{MILLES} {_sous_mille(milliers)}"
    return tete if reste == 0 else f"{tete} {ET} {_sous_mille(reste)}"


def chiffre_par_chiffre(valeur: str | int) -> str:
    """
    Chaque chiffre dit séparément — pour un numéro de suivi ou un numéro
    d'acte, que personne n'énonce comme une quantité.
    """
    return " ".join(UNITES[int(c)] for c in str(valeur) if c.isdigit())


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

#: Emprunts français usuels au Sénégal, écrits comme le pulaar les prononce.
#: À relire comme le reste des phrases.
MOIS = {
    1: "Sanwiye", 2: "Feebariye", 3: "Marse", 4: "Awril",
    5: "Me", 6: "Suwe", 7: "Sulet", 8: "Ut",
    9: "Sattumbar", 10: "Oktoobar", 11: "Nowammbar", 12: "Desammbar",
}

JOUR = "ñalnde"
LEWRU = "lewru"
HITAANDE = "hitaande"


def comme_date(valeur) -> date | None:
    """Les dates sont stockées en ISO par `slot_controller.valider_valeur`."""
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    if isinstance(valeur, str):
        try:
            return date.fromisoformat(valeur.strip()[:10])
        except ValueError:
            return None
    return None


def date_pulaar(valeur) -> str | None:
    """
    Une date énoncée en entier : jour, mois, année.

    `None` si la valeur n'est pas une date lisible — à l'appelant de décider,
    plutôt que de faire dire n'importe quoi au citoyen.
    """
    jour = comme_date(valeur)
    if jour is None:
        return None
    return (
        f"{JOUR} {nombre(jour.day)}, {LEWRU} {MOIS[jour.month]}, "
        f"{HITAANDE} {nombre(jour.year)}"
    )


# ---------------------------------------------------------------------------
# Âges et montants
# ---------------------------------------------------------------------------

#: Pluriels du corpus : « lebbi tati » (trois mois), « balɗe » (jours).
UNITES_AGE = {
    "jour": "ñalawma", "jours": "balɗe",
    "semaine": "yontere", "semaines": "jonte",
    "mois": "lebbi",
    "an": "hitaande", "ans": "duuɓi", "annee": "hitaande", "annees": "duuɓi",
    "année": "hitaande", "années": "duuɓi",
}


def age_pulaar(valeur) -> str | None:
    """Un âge `{"valeur": 3, "unite": "mois"}` énoncé en pulaar."""
    if not isinstance(valeur, dict):
        return None
    quantite, unite = valeur.get("valeur"), (valeur.get("unite") or "").strip().lower()
    if quantite is None or unite not in UNITES_AGE:
        return None
    try:
        entier = int(float(quantite))
    except (TypeError, ValueError):
        return None
    # Le singulier est employé quand la quantité vaut un : « ñalawma go'o »
    # plutôt que « balɗe go'o ».
    if entier == 1:
        singulier = {"balɗe": "ñalawma", "jonte": "yontere", "lebbi": "lewru", "duuɓi": "hitaande"}
        mot = singulier.get(UNITES_AGE[unite], UNITES_AGE[unite])
        return f"{mot} {nombre(1)}"
    return f"{UNITES_AGE[unite]} {nombre(entier)}"


MONNAIE = "faraŋ seefaa"


def montant_pulaar(valeur) -> str | None:
    """Un montant en francs CFA."""
    try:
        entier = int(float(str(valeur).replace(",", ".")))
    except (TypeError, ValueError):
        return None
    return f"{nombre(entier)} {MONNAIE}"


OUI = "eey"
NON = "alaa"


def booleen_pulaar(valeur) -> str:
    return OUI if valeur else NON


# ---------------------------------------------------------------------------
# Texte libre : les chiffres qui restent dans une phrase
# ---------------------------------------------------------------------------
#
# POURQUOI CETTE COUCHE EXISTE
#
# Les fonctions ci-dessus supposent qu'on connaît le TYPE de la valeur : une
# date, un âge, un montant. C'est le cas dans un gabarit à trous
# (`services/gabarits.py`), qui lit `demarche_champs.type_valeur`.
#
# Mais l'essentiel de ce que l'agent dit ne passe pas par un gabarit : la
# réponse française part au traducteur (`temps_reel/parole.py`), qui a pour
# consigne de NE PAS traduire les nombres (`prompts.SYSTEM_PROMPT_FORMATTER`).
# Le pulaar qui arrive au synthétiseur contient donc « 200 », « 2026-09-07 »,
# « SM-2026-000452 » en chiffres, sans aucun type pour les qualifier.
#
# Or le modèle vocal ne sait pas dire un chiffre. Les dix caractères sont bien
# dans son vocabulaire — donc rien ne plante et rien n'est ignoré, ce qui rend
# le défaut discret — mais les transcriptions qui l'ont entraîné écrivent les
# nombres en lettres : ces dix plongements n'ont quasiment jamais été vus.
# Mesuré sur `rnjema-unima/mms-tts-pul-baseline` : « 2026 » produit 0,21 s
# d'audio, « ujunaaje ɗiɗi e noogas e jeegom » en produit 3,09 s. Le modèle
# n'énonce pas le nombre, il émet une brève salve.
#
# `enoncer_nombres` comble donc le manque à la seule place qui voit TOUT ce qui
# est synthétisé : la chaîne de `services.pulaar.texte_pour_synthese`, appelée
# par `tts_client.synthesize_remote`. Le texte affiché au citoyen et celui
# enregistré en base gardent leurs chiffres — un agent de mairie doit lire
# « 07/09/2026 », pas « ñalnde jeeɗiɗi ».

#: Au-delà de cette longueur, une suite de chiffres n'est plus une quantité
#: mais un identifiant : elle s'épelle. C'est l'arbitrage central de cette
#: couche. Personne n'énonce un numéro de dossier comme un nombre, et personne
#: n'épelle un âge. Quatre chiffres restent une quantité (une année, un
#: montant) ; cinq ou plus, c'est un numéro.
SEUIL_EPELLATION = 5

#: UN SEUL motif, parcouru en UNE passe, les règles les plus spécifiques
#: d'abord (l'alternation Python retient la première qui accroche).
#:
#: Pourquoi une passe unique plutôt que six substitutions enchaînées : une
#: règle qui renonce (date impossible, valeur illisible) laisse ses chiffres
#: en place. Enchaînées, la règle suivante — « un entier quelconque » — les
#: reprenait et en faisait une bouillie : « 31/02/2026 » devenait
#: « cappanɗe tati e go'o/ɗiɗi/ujunaaje... ». En une passe, ce qu'une règle a
#: vu n'est plus réexaminé : un renoncement reste un renoncement.
_MOTIFS = re.compile(
    r"(?P<date_iso>\b\d{4}-\d{2}-\d{2}\b)"
    r"|(?P<date_fr>\b(?P<jour>\d{1,2})/(?P<mois>\d{1,2})/(?P<annee>\d{4})\b)"
    # Une référence alphanumérique : au moins un chiffre, au moins une LETTRE,
    # au moins un tiret — « SM-2026-000452 » (`dossiers_repo.generer_numero_suivi`).
    # La lettre est exigée pour que « 2026-09-07 » ne tombe jamais ici : une
    # date s'énonce, un numéro s'épelle.
    r"|(?P<reference>\b(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z0-9]+(?:-[A-Z0-9]+)+\b)"
    r"|(?P<heure>\b(?P<heures>\d{1,2})\s*[hH:]\s*(?P<minutes>\d{2})\b)"
    # Les séparateurs de milliers vus en français : espace, espace insécable,
    # espace fine insécable, point. L'insensibilité à la casse est limitée à
    # l'unité monétaire : l'appliquer à tout le motif ferait accrocher
    # `reference` sur des minuscules.
    r"|(?P<montant>\b(?P<somme>\d[\d\s.\u202f\u00a0]*\d|\d)\s*"
    r"(?i:francs?\s+cfa|francs?|fcfa|f\s*cfa|cfa|faraŋ(?:\s+seefaa)?)\b)"
    r"|(?P<entier>\d+)"
)

_GROUPES = re.compile(r"[\s.\u202f\u00a0]")

#: ⚠️ À VALIDER — « waktu » est attesté dans le corpus comme nom de l'heure
#: (« waktu kala », « Waktuuji ɓeydaaɗi »), mais aucune paire du corpus
#: n'énonce une heure précise : le corpus laisse les chiffres tels quels, ce
#: qui est précisément la cause du défaut corrigé ici. « minute » est gardé en
#: français, comme le fait le corpus (« caggal 5 minute »). À relire comme les
#: noms de mois.
HEURE = "waktu"
MINUTE = "minute"


def _contient_un_chiffre(texte: str | None) -> bool:
    return bool(texte) and any(c.isdigit() for c in texte)


def _enoncer_ou_epeler(entier: int, brut: str) -> str:
    """
    Un entier énoncé comme quantité, ou épelé s'il ne peut pas l'être.

    `nombre()` rend les chiffres tels quels au-delà d'un million : les laisser
    passer ici remettrait le défaut en place. Dans ce cas, on épelle — c'est
    long, mais audible, et aucun champ de l'état civil n'attend un million.
    """
    dit = nombre(entier)
    return chiffre_par_chiffre(brut) if _contient_un_chiffre(dit) else dit


#: « ñalnde » déjà présent juste avant la date, dans l'une ou l'autre de ses
#: deux graphies — « ny » est la même nasale palatale écrite autrement (cf.
#: `services.pulaar.CARACTERES_ABSENTS`), et le modèle de traduction emploie
#: les deux.
_JOUR_DEJA_DIT = re.compile(r"(?<!\w)(?:ñalnde|nyalnde)\s*$", re.IGNORECASE)


def _sans_jour_en_double(m: re.Match, dit: str) -> str:
    """
    Évite « ñalnde ñalnde » quand le texte annonçait déjà le jour.

    `date_pulaar` préfixe toujours sa sortie par « ñalnde ». Or le traducteur
    écrit volontiers « ñalnde 1967-10-14 » — le corpus dit « ñalnde jibineede »
    pour « date de naissance », donc le mot précède naturellement la date. Le
    citoyen entendait alors « jour jour quatorze ».

    On retire le préfixe de NOTRE sortie plutôt que le mot du texte : celui
    d'origine est peut-être porteur d'une accentuation ou d'une casse voulue,
    et le résultat est le même — « ñalnde » suivi du quantième.
    """
    if dit.startswith(JOUR + " ") and _JOUR_DEJA_DIT.search(m.string[:m.start()]):
        return dit[len(JOUR) + 1:]
    return dit


def _dire_date_iso(m: re.Match) -> str:
    dit = date_pulaar(m.group("date_iso"))
    return _sans_jour_en_double(m, dit) if dit else m.group(0)


def _dire_date_fr(m: re.Match) -> str:
    jour, mois, annee = int(m.group("jour")), int(m.group("mois")), m.group("annee")
    if not (1 <= mois <= 12 and 1 <= jour <= 31):
        return m.group(0)
    dit = date_pulaar(f"{annee}-{mois:02d}-{jour:02d}")
    return _sans_jour_en_double(m, dit) if dit else m.group(0)


def _dire_reference(m: re.Match) -> str:
    # Les blocs de lettres restent tels quels : « S M » se dirait comme deux
    # consonnes sans voyelle, inaudible. « SM » passe au moins comme un mot.
    # Seuls les chiffres, qui portent l'information, sont épelés.
    return " ".join(
        chiffre_par_chiffre(bloc) if bloc.isdigit() else bloc
        for bloc in m.group("reference").split("-")
        if bloc
    )


def _dire_heure(m: re.Match) -> str:
    heures, minutes = int(m.group("heures")), int(m.group("minutes"))
    if heures > 23 or minutes > 59:
        return m.group(0)
    if minutes == 0:
        return f"{HEURE} {nombre(heures)}"
    return f"{HEURE} {nombre(heures)} e {MINUTE} {nombre(minutes)}"


def _dire_montant(m: re.Match) -> str:
    brut = m.group("somme")
    dit = montant_pulaar(int(_GROUPES.sub("", brut)))
    if dit is None or _contient_un_chiffre(dit):
        return f"{chiffre_par_chiffre(brut)} {MONNAIE}"
    return dit


def _dire_entier(m: re.Match) -> str:
    brut = m.group("entier")
    if len(brut) >= SEUIL_EPELLATION:
        return chiffre_par_chiffre(brut)
    return _enoncer_ou_epeler(int(brut), brut)


#: Le groupe nommé qui a accroché décide de la fonction qui parle.
_DIRE = {
    "date_iso": _dire_date_iso,
    "date_fr": _dire_date_fr,
    "reference": _dire_reference,
    "heure": _dire_heure,
    "montant": _dire_montant,
    "entier": _dire_entier,
}


def enoncer_nombres(texte: str) -> str:
    """
    Réécrit en mots pulaar tous les chiffres d'un texte libre.

    Une règle dont la valeur n'est pas interprétable laisse le texte d'origine
    EN PLACE plutôt que de produire une énonciation fausse — même principe que
    le `None` des fonctions typées ci-dessus. Le citoyen entendra alors des
    chiffres mal dits, ce qui est mauvais ; il n'entendra jamais une date qui
    n'est pas la sienne, ce qui serait pire sur un acte d'état civil.
    """
    if not texte:
        return texte
    return _MOTIFS.sub(_remplacer, texte)


def _remplacer(m: re.Match) -> str:
    """
    Fait parler la règle qui a accroché.

    Le groupe est cherché par son nom, et non via `m.lastgroup` : celui-ci
    donne le DERNIER sous-groupe rencontré (« annee » pour une date française),
    pas la règle de premier niveau.
    """
    for nom, dire in _DIRE.items():
        if m.group(nom) is not None:
            return dire(m)
    raise AssertionError(f"aucune règle pour {m.group(0)!r}")  # inatteignable
