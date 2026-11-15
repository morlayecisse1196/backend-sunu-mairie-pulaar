"""
Catalogue audio de l'interface, en pulaar.

Pourquoi : une interface lue à voix haute est la seule façon de rendre l'app
utilisable par un citoyen analphabète. Or la synthèse prend plusieurs dizaines
de secondes : impossible de traduire et synthétiser à la volée à chaque écran.
Chaque phrase est donc synthétisée UNE fois puis servie depuis le disque
(`audio_cache/ui/`). Le script `scripts/generer_catalogue_audio.py` permet de
tout pré-générer avant une mise en production.

Le même mécanisme sert aux phrases dérivées d'un dossier (lecture d'un champ
du document) : clé = empreinte du texte.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from typing import Optional

from prompts import SYSTEM_PROMPT_FORMATTER, build_narration_statut_dossier_prompt
from services import llm
from services.journal import obtenir_logger
from services.pulaar import texte_pour_synthese
from tts_client import NARRATION_TIMEOUT_SECONDS, synthesize_remote

log = obtenir_logger("catalogue_audio")

DOSSIER_CACHE = os.path.join("audio_cache", "ui")

# Phrases d'interface (français) — traduites en pulaar puis synthétisées.
PHRASES = {
    "accueil": "Bienvenue sur SUNU-MAIRIE. Appuyez sur le micro et dites ce que vous voulez faire.",
    "micro_parler": "Appuyez sur le micro, puis parlez.",
    "micro_terminer": "Quand vous avez fini de parler, relâchez le micro.",
    "aide": "Vous pouvez demander un extrait de naissance, ou poser une question sur une démarche.",
    "photo_prendre": "Prenez la photo du document, posé bien à plat, sans ombre dessus.",
    "photo_floue": "La photo est floue. Tenez le téléphone sans bouger et reprenez la photo.",
    "photo_envoyee": "Merci, la photo est bien arrivée.",
    "dossier_envoye": "Votre demande est envoyée à la mairie. Gardez bien votre numéro de suivi.",
    "dossier_en_traitement": "Votre dossier est en cours de traitement à la mairie.",
    "document_pret": "Votre document est prêt. Écoutez-le, puis dites si tout est correct.",
    "document_valider": "Si tout est correct, appuyez sur le bouton vert.",
    "document_probleme": "Si quelque chose est faux, appuyez sur le bouton rouge et dites ce qui ne va pas.",
    "mes_demarches": "Voici vos démarches en cours.",
    "reseau_absent": "Il n'y a pas de connexion internet. Réessayez quand le réseau revient.",
    "erreur": "Une erreur est survenue. Réessayez, s'il vous plaît.",
}

_verrous: dict[str, asyncio.Lock] = {}


def _verrou(cle: str) -> asyncio.Lock:
    return _verrous.setdefault(cle, asyncio.Lock())


def chemin_fichier(cle: str) -> str:
    return os.path.join(DOSSIER_CACHE, f"{cle}.wav")


def cle_pour_texte(texte: str) -> str:
    return "txt_" + hashlib.sha1(texte.strip().lower().encode("utf-8")).hexdigest()[:16]


def existe(cle: str) -> bool:
    return os.path.exists(chemin_fichier(cle))


async def _traduire_en_pulaar(texte_fr: str) -> str:
    return await llm.completer_texte(
        [
            {"role": "system", "content": SYSTEM_PROMPT_FORMATTER},
            {"role": "user", "content": build_narration_statut_dossier_prompt(texte_fr)},
        ],
        temperature=0.3,
    )


async def audio_pour_texte(cle: str, texte_fr: str) -> bytes:
    """Audio pulaar du texte donné : lu depuis le cache, sinon traduit, synthétisé, puis mis en cache."""
    chemin = chemin_fichier(cle)
    if os.path.exists(chemin):
        return await asyncio.to_thread(lambda: open(chemin, "rb").read())

    async with _verrou(cle):
        if os.path.exists(chemin):  # généré pendant l'attente du verrou
            return await asyncio.to_thread(lambda: open(chemin, "rb").read())
        texte_pulaar = await _traduire_en_pulaar(texte_fr)
        audio = await synthesize_remote(texte_pulaar or texte_fr, timeout=NARRATION_TIMEOUT_SECONDS)
        try:
            os.makedirs(DOSSIER_CACHE, exist_ok=True)
            await asyncio.to_thread(lambda: open(chemin, "wb").write(audio))
        except OSError as exc:
            log.warning("Écriture du cache audio impossible (%s) — audio servi quand même", type(exc).__name__)
        return audio


async def audio_interface(cle: str) -> Optional[bytes]:
    texte = PHRASES.get(cle)
    if texte is None:
        return None
    return await audio_pour_texte(cle, texte)


# ============================================================================
# Étape 3.4 — audio pré-généré des phrases du dialogue
#
# LE PROBLÈME
#
# L'étape 3.3 a supprimé l'appel au traducteur pour une phrase relue. Restait
# la synthèse : le Space vocal met plusieurs dizaines de secondes à repartir
# après une inactivité, et le citoyen attend en silence devant un écran qu'il
# ne sait pas lire. Une question écrite en base depuis des mois n'a pourtant
# aucune raison d'être resynthétisée à chaque conversation.
#
# L'INVALIDATION, PAR CONSTRUCTION
#
# Servir un audio périmé est PIRE que ne pas en avoir : le citoyen entendrait
# l'ancienne phrase alors que le relecteur vient de la corriger, sans que rien
# ne le signale. La clé du fichier est donc l'EMPREINTE DU TEXTE PULAAR
# lui-même. Corriger une lettre change l'empreinte, donc la clé : l'ancien
# fichier n'est plus jamais trouvé, et la phrase repart à la synthèse. Aucun
# effacement à ne pas oublier, aucune course possible entre l'écriture du
# texte et celle du fichier.
#
# La colonne `audio` des tables reste un INDICATEUR pour l'atelier (« cette
# phrase a-t-elle déjà son audio ? »), jamais la source de ce qui est servi.
# ============================================================================

DOSSIER_PHRASES = os.path.join("audio_cache", "phrases")


def cle_phrase(texte_pulaar: str) -> str:
    """
    La clé du fichier audio d'un texte pulaar : son empreinte.

    L'empreinte porte sur le texte RÉELLEMENT ENVOYÉ au synthétiseur, c'est-à-
    dire après `texte_pour_synthese` — la MÊME fonction que celle appliquée par
    `tts_client.synthesize_remote`, et non une partie d'entre elle : sinon le
    fichier rangé sur le disque ne correspondrait plus à sa clé. Trois choses
    peuvent donc changer le son d'une phrase, et toutes trois changent la clé :
    le relecteur corrige le pulaar, un terme entre au glossaire et cesse d'être
    écorché, ou la façon d'énoncer les nombres évolue. Faire porter l'empreinte
    sur le seul texte de la base laisserait les deux dernières passer
    inaperçues — l'audio dirait encore « ekstere de nesaas » longtemps après la
    correction du glossaire.

    Volontairement SANS mise en minuscules, contrairement à `cle_pour_texte` :
    ici, la moindre retouche — une majuscule, une apostrophe — doit provoquer
    une resynthèse. Mieux vaut resynthétiser pour rien que faire entendre un
    texte corrigé avec l'ancien son.
    """
    dit = texte_pour_synthese((texte_pulaar or "").strip())
    return "pul_" + hashlib.sha1(dit.encode("utf-8")).hexdigest()[:20]


def chemin_phrase(cle: str) -> str:
    return os.path.join(DOSSIER_PHRASES, f"{cle}.wav")


def phrase_deja_generee(texte_pulaar: str) -> bool:
    """Vrai si l'audio de CE texte exact est déjà sur le disque."""
    if not (texte_pulaar or "").strip():
        return False
    return os.path.exists(chemin_phrase(cle_phrase(texte_pulaar)))


async def audio_phrase(texte_pulaar: str) -> Optional[bytes]:
    """
    L'audio pré-généré de ce texte pulaar, ou `None` s'il n'existe pas encore.

    Ne synthétise JAMAIS : en plein dialogue, c'est l'appelant qui décide quoi
    faire d'un manque — le plus souvent synthétiser ce morceau-là seulement,
    pendant que les autres partent déjà. Un disque illisible retourne `None`
    comme une absence : le dialogue continue, en payant la synthèse.
    """
    if not (texte_pulaar or "").strip():
        return None
    chemin = chemin_phrase(cle_phrase(texte_pulaar))
    try:
        if not os.path.exists(chemin):
            return None
        return await asyncio.to_thread(lambda: open(chemin, "rb").read())
    except Exception as exc:  # noqa: BLE001 — voir ci-dessous
        log.warning("Audio pré-généré illisible (%s) — synthèse à la volée.", type(exc).__name__)
        return None


async def enregistrer_phrase(texte_pulaar: str, audio: bytes) -> Optional[str]:
    """
    Range l'audio de ce texte, et retourne sa clé — ou `None` si l'écriture
    échoue.

    Appelé aussi depuis le dialogue : la première personne qui entend une
    phrase paie la synthèse, les suivantes l'entendent tout de suite. Un échec
    d'écriture (disque plein, droits) ne doit jamais interrompre un tour : il
    est journalisé, et la phrase sera simplement resynthétisée la prochaine
    fois.
    """
    if not (texte_pulaar or "").strip() or not audio:
        return None
    cle = cle_phrase(texte_pulaar)
    chemin = chemin_phrase(cle)
    try:
        os.makedirs(DOSSIER_PHRASES, exist_ok=True)
        await asyncio.to_thread(lambda: open(chemin, "wb").write(audio))
        return cle
    except Exception as exc:  # noqa: BLE001 — volontairement large
        # Ce code tourne PENDANT le tour d'un citoyen. L'écriture est un
        # confort pour les suivants ; la laisser remonter couperait la parole
        # à celui qui est en ligne, pour un cache. Tout est donc rattrapé, et
        # journalisé — un disque plein, un chemin illisible, des droits
        # manquants ont la même conséquence : une resynthèse la prochaine fois.
        log.warning("Écriture de l'audio pré-généré impossible (%s).", type(exc).__name__)
        return None
