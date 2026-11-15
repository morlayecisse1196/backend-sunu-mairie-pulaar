"""
Phase « parler » d'un tour : traduction pulaar en flux + synthèse vocale.

Deux améliorations par rapport à `emettre_reponse_pulaar_et_tts` (main.py) :

1. LATENCE — la synthèse d'une phrase démarre dès que cette phrase est
   complète dans le flux de traduction, sans attendre la fin de la traduction
   entière. Le premier son part donc plus tôt. L'ordre d'envoi reste garanti
   (file ordonnée), la synthèse parallèle bornée (sémaphore).
2. INTERRUPTION — toute la phase est annulable (le citoyen reparle ou appuie
   sur « stop ») : les requêtes de traduction et de synthèse en vol sont
   annulées, aucune tâche ne reste orpheline.
"""
from __future__ import annotations

import asyncio
import re
from typing import Awaitable, Callable, Optional, Protocol

from prompts import SYSTEM_PROMPT_FORMATTER, build_formatter_prompt
from services import catalogue_audio, llm
from services import phrases as services_phrases
from services.journal import obtenir_logger
from tts_client import TTSError, synthesize_remote

log = obtenir_logger("parole")

SYNTHESES_PARALLELES = 2
_FIN_DE_PHRASE = re.compile(r"[.!?…]+[\"»”)]*\s+")
LONGUEUR_MIN_PHRASE = 12

# Au-delà de ce délai sans un seul son, on le DIT. Même seuil que la phase
# « comprendre » (DELAI_SIGNAL_LENTEUR dans temps_reel/connexion.py) : il n'y a
# pas de raison qu'un silence soit tolérable plus longtemps ici qu'ailleurs.
#
# Pourquoi ce signal manquait, et pourquoi il compte le plus ici : `lent` ne
# couvrait que la transcription et la réflexion. Or c'est CETTE phase qui est la
# plus longue — mesuré sur ce projet, 25,3 s sur un tour de 32,4 s, dont une
# douzaine de secondes avant le premier son. Un citoyen qui ne sait pas lire
# n'avait donc aucun signe de vie pendant la partie la plus lente du tour : le
# texte français affiché entre-temps ne lui sert à rien.
DELAI_SIGNAL_LENTEUR_PAROLE = 6.0


class Emetteur(Protocol):
    async def envoyer_json(self, message: dict) -> None: ...
    async def envoyer_octets(self, octets: bytes) -> None: ...


def extraire_phrases_completes(tampon: str) -> tuple[list[str], str]:
    """Découpe les phrases terminées du tampon ; retourne (phrases, reste non terminé)."""
    phrases: list[str] = []
    debut = 0
    for correspondance in _FIN_DE_PHRASE.finditer(tampon):
        fin = correspondance.end()
        phrase = tampon[debut:fin].strip()
        if len(phrase) >= LONGUEUR_MIN_PHRASE:
            phrases.append(phrase)
            debut = fin
    return phrases, tampon[debut:]


async def dire(
    emetteur: Emetteur,
    *,
    texte_fr: str,
    contexte_question: str,
    premier_tour: bool,
    turn_id: Optional[str],
    reponse: Optional[services_phrases.Reponse] = None,
    flux_traduction: Callable[..., object] = llm.flux_texte,
    synthetiser: Callable[[str], Awaitable[bytes]] = synthesize_remote,
) -> str:
    """
    Dit la réponse en pulaar : texte et audio au fil de l'eau. Retourne le
    pulaar complet.

    ÉTAPE 3 — COURT-CIRCUIT DU TRADUCTEUR

    `reponse` porte les morceaux de la réponse et, pour chacun, le pulaar
    relu par un locuteur s'il existe. Quand TOUS les morceaux en ont un, le
    modèle n'est pas appelé du tout : la phrase part telle quelle à la
    synthèse. C'est le remède au pulaar incohérent — une question écrite en
    base depuis des mois n'a aucune raison d'être retraduite différemment à
    chaque conversation.

    Dès qu'UN SEUL morceau manque, toute la réponse repasse par le traducteur,
    comme avant. Traduire les morceaux séparément ferait perdre au modèle le
    contexte de la phrase entière — et notamment la règle du « Salam », qui ne
    s'ouvre qu'au premier tour. Le gain grandit donc au fur et à mesure que la
    relecture avance, sans jamais dégrader l'existant.

    ÉTAPE 3.4 — AUDIO PRÉ-GÉNÉRÉ

    Une phrase relue est toujours dite avec les mêmes mots : son audio est donc
    toujours le même. Quand il est déjà sur le disque, il part tel quel et la
    synthèse n'est pas appelée non plus — c'est ce qui supprime l'attente du
    démarrage à froid du Space vocal, plusieurs dizaines de secondes pendant
    lesquelles un citoyen qui ne lit pas n'a rien du tout.

    Le fichier est retrouvé par l'EMPREINTE du texte pulaar, jamais par la
    colonne `audio` de la base : un texte corrigé a une autre empreinte, donc
    aucun audio, donc une resynthèse. Faire entendre l'ancienne phrase après
    une correction serait pire que d'attendre.

    Le morceau non trouvé est synthétisé ENTIER — et non phrase par phrase
    comme sur le chemin du traducteur — puis rangé : la première personne qui
    l'entend paie la synthèse, les suivantes ne l'attendent plus.
    """
    validee = reponse is not None and reponse.entierement_validee
    if not validee and reponse is not None:
        services_phrases.signaler(reponse)  # étape 3.5 : ce qui reste à relire
    semaphore = asyncio.Semaphore(SYNTHESES_PARALLELES)
    file_audio: asyncio.Queue = asyncio.Queue()
    taches: list[asyncio.Task] = []

    async def synthese(phrase: str):
        async with semaphore:
            try:
                return await synthetiser(phrase)
            except TTSError as exc:
                return exc

    async def synthese_et_rangement(phrase: str):
        """Synthétise un morceau relu, et le garde pour les prochains citoyens."""
        resultat = await synthese(phrase)
        if not isinstance(resultat, BaseException):
            await catalogue_audio.enregistrer_phrase(phrase, resultat)
        return resultat

    async def deja_synthetise(octets: bytes) -> bytes:
        return octets

    def planifier(phrase: str, *, ranger: bool = False) -> None:
        tache = asyncio.create_task(
            synthese_et_rangement(phrase) if ranger else synthese(phrase)
        )
        taches.append(tache)
        file_audio.put_nowait(tache)

    def planifier_octets(octets: bytes) -> None:
        """Un audio déjà prêt : il passe par la même file, donc le même ordre."""
        tache = asyncio.create_task(deja_synthetise(octets))
        taches.append(tache)
        file_audio.put_nowait(tache)

    async def veiller_lenteur() -> None:
        """Dit « ça prend un peu de temps » si aucun son n'est encore parti."""
        await asyncio.sleep(DELAI_SIGNAL_LENTEUR_PAROLE)
        await emetteur.envoyer_json({"type": "lent", "turn_id": turn_id, "etape": "parole"})

    tache_veille: Optional[asyncio.Task] = asyncio.create_task(veiller_lenteur())

    async def envoyeur() -> None:
        envoyees = 0
        while True:
            tache = await file_audio.get()
            if tache is None:
                break
            resultat = await tache
            if isinstance(resultat, BaseException):
                log.warning("Synthèse d'une phrase échouée (%s)", type(resultat).__name__)
                await emetteur.envoyer_json({
                    "type": "error", "code": "synthese_vocale", "recuperable": True, "turn_id": turn_id,
                    "content": "Une partie de la réponse n'a pas pu être dite.",
                })
                continue
            if envoyees == 0:
                # Le premier son part : la veille n'a plus d'objet. Annulée
                # AVANT l'envoi, pour qu'un `lent` ne puisse pas se glisser
                # juste après le début de la parole.
                if tache_veille is not None and not tache_veille.done():
                    tache_veille.cancel()
                await emetteur.envoyer_json({"type": "status", "state": "speaking", "turn_id": turn_id})
            await emetteur.envoyer_octets(resultat)
            envoyees += 1
            await emetteur.envoyer_json({"type": "tts_progress", "current": envoyees, "total": None, "turn_id": turn_id})
        await emetteur.envoyer_json({"type": "tts_end", "turn_id": turn_id})

    tache_envoi = asyncio.create_task(envoyeur())
    pulaar = ""
    tampon = ""
    try:
        if validee:
            for rang, morceau in enumerate(reponse.morceaux):
                texte = morceau.pulaar_pret()
                delta = texte if rang == 0 else " " + texte
                pulaar += delta
                await emetteur.envoyer_json({"type": "stream_pulaar", "content": delta, "turn_id": turn_id})
                octets = await catalogue_audio.audio_phrase(texte)
                if octets is not None:
                    planifier_octets(octets)
                else:
                    planifier(texte, ranger=True)
        else:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT_FORMATTER},
                {"role": "user", "content": build_formatter_prompt(
                    contexte_question, texte_fr, premier_tour=premier_tour)},
            ]
            async for delta in flux_traduction(messages, temperature=0.3):
                pulaar += delta
                tampon += delta
                await emetteur.envoyer_json({"type": "stream_pulaar", "content": delta, "turn_id": turn_id})
                phrases_completes, tampon = extraire_phrases_completes(tampon)
                for phrase in phrases_completes:
                    planifier(phrase)
            if tampon.strip():
                planifier(tampon.strip())
        file_audio.put_nowait(None)
        await tache_envoi
        return pulaar
    finally:
        # La veille est annulée aussi sur interruption : sans cela, un citoyen
        # qui coupe la parole recevrait quelques secondes plus tard un « ça
        # prend du temps » à propos d'une réponse déjà abandonnée.
        if tache_veille is not None and not tache_veille.done():
            tache_veille.cancel()
        if not tache_envoi.done():
            tache_envoi.cancel()
        for tache in taches:
            if not tache.done():
                tache.cancel()
        await asyncio.gather(tache_envoi, tache_veille, *taches, return_exceptions=True)
