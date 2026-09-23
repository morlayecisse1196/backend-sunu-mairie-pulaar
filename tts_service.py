# tts_service.py
#
# Orchestration de la synthèse pulaar : découpage en phrases + appel au Space
# HF dédié (tts_client.py) pour chaque phrase. Ne charge plus aucun modèle en
# local — la synthèse tourne sur le GPU du Space, pas sur ce serveur (voir
# ANCIEN_CODE_HF_SPACE/ pour le code du Space). L'interface publique
# (synthesize_stream, synthesize_text) est inchangée : aucun appelant
# (main.py) n'a besoin de changer sa façon d'utiliser tts_service.
import re
import json
import asyncio

from tts_client import synthesize_remote, TTSError, NARRATION_TIMEOUT_SECONDS

# Nombre de phrases synthétisées EN PARALLÈLE par synthesize_stream (cf. son
# docstring) — borné plutôt qu'illimité : le Space TTS distant tourne parfois
# sur CPU (cf. tts_client.py), inutile de lui envoyer toutes les phrases
# d'une longue réponse d'un coup, 2 en vol suffit à combler le trou entre
# deux phrases sans le surcharger.
TTS_PREFETCH_CONCURRENCY = 2


class PulaarTTSService:

    def split_sentences(self, text: str) -> list:
        """Découpe le texte en phrases (par . ! ?)."""
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        return [s for s in sentences if s]

    async def synthesize_text(self, text: str) -> bytes:
        """
        Synthétise un texte complet en un seul appel au Space (pas de découpage).
        Utilisé pour les narrations longues (POST /demarches/{id}/audio) : timeout
        plus généreux que pour les phrases courtes de synthesize_stream.
        """
        return await synthesize_remote(text, timeout=NARRATION_TIMEOUT_SECONDS)

    async def synthesize_stream(self, text: str, websocket):
        """
        Synthétise phrase par phrase et envoie l'audio en streaming via
        WebSocket, une phrase à la fois — comportement inchangé pour
        l'appelant, seule la source de la synthèse a changé (Space distant
        au lieu du modèle chargé localement).

        Pipeline (correctif du 2026-09-11, retour terrain avatar 3D) : au
        lieu de synthétiser chaque phrase l'une après l'autre (chaque
        `await synthesize_remote(...)` attendant la fin — réseau + synthèse,
        jusqu'à TTS_TIMEOUT_SECONDS=60s, Space potentiellement sur CPU — de
        la précédente avant même de COMMENCER la suivante), un petit pool de
        `TTS_PREFETCH_CONCURRENCY` synthèses tourne en permanence en arrière-
        plan pendant que les phrases déjà prêtes sont envoyées dans l'ordre.
        Ce silence entre phrases est un vrai silence côté client (l'intensity
        retombe à 0, cf. AudioPlaybackService) : sur une réponse à plusieurs
        phrases, l'avatar semblait "s'arrêter de parler" entre chacune.

        Attention à une fausse bonne idée testée puis abandonnée ici : créer
        UNE SEULE tâche d'avance (phrase N+1 lancée juste avant d'attendre la
        phrase N) donne l'impression de chevaucher, mais dégénère en réalité
        en paires (0+1 démarrent ensemble, puis 2+3 ensemble, etc.) — dès que
        la tâche N a fini avant même d'être consommée, la tâche N+2 est
        lancée au même instant que N+1, sans aucun décalage réel. Un pool
        borné par un vrai sémaphore (ci-dessous) n'a pas ce défaut : dès
        qu'une place se libère, la synthèse suivante démarre immédiatement,
        peu importe laquelle des phrases précédentes vient de finir — vérifié
        par test_tts_pipeline_synthesis.py (chevauchement sur CHAQUE
        frontière, avec des délais volontairement différents par phrase).
        """
        sentences = self.split_sentences(text)
        if not sentences:
            return

        total_phrases = len(sentences)
        semaphore = asyncio.Semaphore(TTS_PREFETCH_CONCURRENCY)

        async def _synthetiser(sentence: str):
            async with semaphore:
                try:
                    return await synthesize_remote(sentence)
                except TTSError as e:
                    return e

        # Toutes les tâches sont créées tout de suite, mais le sémaphore
        # borne à `TTS_PREFETCH_CONCURRENCY` celles qui synthétisent
        # RÉELLEMENT en parallèle à un instant donné — les suivantes
        # attendent simplement qu'une place se libère.
        taches = [asyncio.create_task(_synthetiser(s)) for s in sentences]

        for idx, tache in enumerate(taches):
            resultat = await tache

            if isinstance(resultat, TTSError):
                # Une phrase en échec ne doit pas interrompre tout le tour de
                # conversation : on prévient le client et on passe à la
                # suivante (déjà en cours de synthèse dans le pool ci-dessus).
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "content": f"Erreur de synthèse vocale : {resultat}"
                }))
                continue

            await websocket.send_bytes(resultat)
            await websocket.send_text(json.dumps({
                "type": "tts_progress",
                "current": idx + 1,
                "total": total_phrases
            }))

        await websocket.send_text(json.dumps({"type": "tts_end"}))


# Instance globale — plus aucun modèle à charger, instanciation immédiate et légère.
tts_service = PulaarTTSService()
