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

from tts_client import synthesize_remote, TTSError, NARRATION_TIMEOUT_SECONDS


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
        """
        sentences = self.split_sentences(text)
        if not sentences:
            return

        total_phrases = len(sentences)

        for idx, sentence in enumerate(sentences):
            try:
                audio_bytes = await synthesize_remote(sentence)
            except TTSError as e:
                # Une phrase en échec ne doit pas interrompre tout le tour de
                # conversation : on prévient le client et on tente la suivante.
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "content": f"Erreur de synthèse vocale : {e}"
                }))
                continue

            await websocket.send_bytes(audio_bytes)
            await websocket.send_text(json.dumps({
                "type": "tts_progress",
                "current": idx + 1,
                "total": total_phrases
            }))

        await websocket.send_text(json.dumps({"type": "tts_end"}))


# Instance globale — plus aucun modèle à charger, instanciation immédiate et légère.
tts_service = PulaarTTSService()
