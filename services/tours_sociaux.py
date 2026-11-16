"""
Les tours qui ne répondent pas à la question — et qui n'ont rien de fautif.

LE PROBLÈME

Une fois le dialogue en mode administratif, TOUT message partait au modèle
ciblé sur le champ en cours. Ce qui n'y répondait pas était compté comme un
échec. Mesuré sur le vrai modèle, quatre messages sur quatre :

    « Bonjour »            -> « Je n'ai pas compris. Quel âge a votre enfant ? »
    « Salaam alaikum »     -> « Je n'ai pas compris. … »
    « Merci »              -> « Je n'ai pas compris. … »
    « Attends un instant » -> « Je n'ai pas compris. … »

Et ce n'était pas qu'un désagrément : chaque échec incrémente un compteur, et
au troisième le champ est ABANDONNÉ avec ouverture d'un cas particulier. Dire
« bonjour, merci, attends » suffisait à saboter sa propre demande.

POURQUOI DÉTERMINISTE, ET PAS UN APPEL AU MODÈLE

Un modèle coûte une seconde et peut se tromper sur « bonjour ». Une liste de
formulations est instantanée, gratuite, et son comportement se lit dans le
code. Elle rate des tournures ; c'est acceptable, puisque le repli est le
comportement d'avant — la relance.

LA PROPRIÉTÉ QUI COMPTE : NE JAMAIS AVALER UNE VRAIE RÉPONSE

« Bonjour, il a trois jours » contient la réponse. La classer comme une
salutation perdrait l'information et ferait reposer la question. On exige donc
qu'il ne reste RIEN de substantiel une fois la formule retirée : ni chiffre,
ni mot qui ne soit pas de la politesse. Dans le doute, on ne classe pas.

LE PULAAR

Les formules pulaar listées ici sont celles dont la graphie est sûre. La liste
est volontairement courte : reconnaître de travers un mot pulaar ferait taire
une vraie réponse, ce qui est bien pire que de ne pas le reconnaître. Elle doit
être complétée par un locuteur, comme le reste du pulaar de ce projet.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

#: Les natures reconnues. L'appelant décide quoi répondre à chacune.
SALUTATION = "salutation"
REMERCIEMENT = "remerciement"
PATIENCE = "patience"
REPETITION = "repetition"

#: Mots qui peuvent entourer une formule sans rien y ajouter.
_REMPLISSAGE = {
    "a", "ah", "ai", "allez", "alors", "as", "au", "avez", "beaucoup", "bien",
    "bon", "ca", "c", "comment", "d", "de", "des", "donc",
    "du", "eh", "en", "est", "et", "euh", "hein", "hmm", "il", "je", "ju", "la",
    "le", "les", "ma", "mais", "me", "mon", "monsieur", "madame", "n", "ne", "non",
    "nous", "o", "oh", "ok", "on", "oui", "ouais", "par", "pas", "peu", "plait",
    "plus", "pour", "que", "qui", "s", "si", "sil", "sur", "ta", "te", "toi", "ton",
    "tout", "tres", "tu", "un", "une", "va", "vas", "vous", "votre", "y",
}

#: Formules, en mots normalisés. Une entrée à plusieurs mots doit apparaître
#: telle quelle, dans l'ordre, dans le message.
_FORMULES: list[tuple[str, tuple[str, ...]]] = [
    # --- Salutations ---------------------------------------------------
    (SALUTATION, ("bonjour",)),
    (SALUTATION, ("bonsoir",)),
    (SALUTATION, ("salut",)),
    (SALUTATION, ("salam",)),
    (SALUTATION, ("salaam",)),
    (SALUTATION, ("assalamu", "alaykum")),
    (SALUTATION, ("assalam", "alaykum")),
    (SALUTATION, ("salam", "alaikum")),
    (SALUTATION, ("salaam", "alaikum")),
    (SALUTATION, ("asalamu", "alaikum")),
    (SALUTATION, ("coucou",)),
    # Pulaar : salutation d'usage. « jam » = la paix.
    (SALUTATION, ("jam",)),
    (SALUTATION, ("jam", "tan")),
    (SALUTATION, ("jam", "waali")),
    (SALUTATION, ("jam", "nalli")),

    # --- Remerciements -------------------------------------------------
    (REMERCIEMENT, ("merci",)),
    (REMERCIEMENT, ("mercie",)),       # transcription vocale approximative
    (REMERCIEMENT, ("jerejef",)),      # wolof, très courant au Sénégal
    (REMERCIEMENT, ("jaaraama",)),     # pulaar
    (REMERCIEMENT, ("jaraama",)),

    # --- Demandes de pause ---------------------------------------------
    (PATIENCE, ("attends",)),
    (PATIENCE, ("attendez",)),
    (PATIENCE, ("attend",)),
    (PATIENCE, ("instant",)),
    (PATIENCE, ("minute",)),
    (PATIENCE, ("patiente",)),
    (PATIENCE, ("patientez",)),
    (PATIENCE, ("seconde",)),

    # --- Demandes de répétition ----------------------------------------
    (REPETITION, ("repete",)),
    (REPETITION, ("repetez",)),
    (REPETITION, ("redis",)),
    (REPETITION, ("redites",)),
    (REPETITION, ("entendu",)),        # « je n'ai pas entendu »
    (REPETITION, ("compris",)),        # « je n'ai pas compris »
    (REPETITION, ("comprends",)),
    (REPETITION, ("pardon",)),
    (REPETITION, ("question",)),       # « quelle est la question ? »
]

_SEPARATEURS = re.compile(r"[^a-z0-9ɓɗƴŋ]+")

#: Tous les mots qui composent une formule : ils ne portent jamais une réponse.
_MOTS_DE_FORMULE = {mot for _nature, formule in _FORMULES for mot in formule}


def _normaliser(texte: str) -> list[str]:
    """Mots du message, sans accents, sans ponctuation, en minuscules.

    Les lettres propres au pulaar (ɓ ɗ ƴ ŋ ñ) sont conservées : les retirer
    collerait deux mots différents l'un sur l'autre.
    """
    # Les signes combinants sautent : « é » devient « e », « ñ » devient « n ».
    # Les lettres pulaar ɓ ɗ ƴ ŋ, elles, sont des lettres de base et survivent.
    # Les formules sont écrites de la même façon, donc les deux côtés de la
    # comparaison subissent le même sort.
    sans_accent = "".join(
        c for c in unicodedata.normalize("NFD", (texte or "").lower())
        if unicodedata.category(c) != "Mn"
    )
    return [mot for mot in _SEPARATEURS.split(sans_accent) if mot]


def _sequence_presente(mots: list[str], formule: tuple[str, ...]) -> Optional[tuple[int, int]]:
    """Position (début, fin) de la formule dans les mots, ou None."""
    taille = len(formule)
    for debut in range(len(mots) - taille + 1):
        if tuple(mots[debut:debut + taille]) == formule:
            return debut, debut + taille
    return None


def est_sans_substance(texte: str) -> bool:
    """
    Vrai si le texte ne porte aucune information : que du remplissage ou des
    mots de politesse, aucun chiffre, aucun mot porteur.

    Sert à répondre à la question « ce message dit-il AUTRE CHOSE que la
    formule qu'on vient d'y reconnaître ? ». Un « oui » tout seul n'ajoute
    rien ; « oui, il a trois jours » ajoute une réponse qu'il serait grave de
    jeter.
    """
    return all(
        not mot.isdigit() and (mot in _REMPLISSAGE or mot in _MOTS_DE_FORMULE)
        for mot in _normaliser(texte)
    )


def classer(message: str) -> Optional[str]:
    """
    La nature du tour, ou `None` si le message porte autre chose.

    `None` est le cas normal : c'est une réponse à la question posée, et le
    dialogue suit son cours habituel.
    """
    mots = _normaliser(message)
    if not mots:
        return None
    # Un message long n'est pas une simple formule de politesse. La borne est
    # large : « bonjour monsieur comment allez vous » fait six mots.
    if len(mots) > 8:
        return None

    for nature, formule in _FORMULES:
        position = _sequence_presente(mots, formule)
        if position is None:
            continue
        restant = mots[:position[0]] + mots[position[1]:]
        # Ce qui reste doit être sans substance : un chiffre ou un mot porteur
        # signifie que le citoyen a dit autre chose — et cette autre chose est
        # peut-être SA RÉPONSE. Dans ce cas on ne classe pas.
        #
        # Les mots des autres formules comptent comme sans substance : « attends
        # un instant » ou « merci beaucoup, bonjour » restent de la politesse.
        if any(mot.isdigit() or (mot not in _REMPLISSAGE and mot not in _MOTS_DE_FORMULE)
               for mot in restant):
            continue
        return nature
    return None
