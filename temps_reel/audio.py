"""
Préparation de l'audio reçu du client avant la transcription (ASR).

L'ASR distant attend du WAV. Le WAV brut 16 kHz pèse ~1 Mo pour 30 s : trop
lourd en zone rurale (3G/EDGE). Le protocole v2 permet donc au mobile d'envoyer
un format compressé (Opus/Ogg, WebM, AAC/M4A, MP3), converti ici par ffmpeg en
WAV 16 kHz mono. Bornes : taille, durée minimale (appui accidentel) et
maximale (micro resté ouvert).
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile

DUREE_MIN_SECONDES = 0.3
DUREE_MAX_SECONDES = 60.0
OCTETS_MAX = 10 * 1024 * 1024
DELAI_CONVERSION_SECONDES = 30


class ErreurAudio(Exception):
    """Audio inutilisable — `code` stable pour le client, `message_fr` destiné à être dit au citoyen."""

    def __init__(self, code: str, message_fr: str):
        super().__init__(code)
        self.code = code
        self.message_fr = message_fr


def detecter_format(octets: bytes) -> str:
    if len(octets) >= 12 and octets[:4] == b"RIFF" and octets[8:12] == b"WAVE":
        return "wav"
    if octets[:4] == b"OggS":
        return "ogg"
    if octets[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if len(octets) >= 12 and octets[4:8] == b"ftyp":
        return "m4a"
    if octets[:3] == b"ID3" or (len(octets) >= 2 and octets[0] == 0xFF and (octets[1] & 0xE0) == 0xE0):
        return "mp3"
    return "inconnu"


def duree_wav_secondes(octets: bytes) -> float | None:
    """Durée d'un WAV PCM d'après ses en-têtes (None si illisible)."""
    if detecter_format(octets) != "wav":
        return None
    position, octets_par_seconde, taille_donnees = 12, None, None
    while position + 8 <= len(octets):
        identifiant = octets[position:position + 4]
        taille = int.from_bytes(octets[position + 4:position + 8], "little")
        debut = position + 8
        if identifiant == b"fmt " and debut + 12 <= len(octets):
            octets_par_seconde = int.from_bytes(octets[debut + 8:debut + 12], "little")
        elif identifiant == b"data":
            taille_donnees = min(taille, len(octets) - debut)
            break
        position = debut + taille + (taille % 2)
    if not octets_par_seconde or taille_donnees is None:
        return None
    return taille_donnees / octets_par_seconde


def chemin_ffmpeg() -> str | None:
    return os.getenv("FFMPEG_PATH") or shutil.which("ffmpeg")


def _convertir_sync(octets: bytes, executable: str) -> bytes:
    with tempfile.TemporaryDirectory() as dossier:
        entree = os.path.join(dossier, "entree")
        sortie = os.path.join(dossier, "sortie.wav")
        with open(entree, "wb") as fichier:
            fichier.write(octets)
        # Fichier de sortie (et non un pipe) : l'en-tête WAV contient alors la vraie taille des données.
        resultat = subprocess.run(
            [executable, "-hide_banner", "-loglevel", "error", "-y", "-i", entree,
             "-t", str(int(DUREE_MAX_SECONDES) + 1), "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", sortie],
            capture_output=True,
            timeout=DELAI_CONVERSION_SECONDES,
            check=False,
        )
        if resultat.returncode != 0 or not os.path.exists(sortie):
            raise ErreurAudio("conversion_audio_echouee", "Je n'ai pas pu lire votre message vocal. Pouvez-vous le redire ?")
        with open(sortie, "rb") as fichier:
            return fichier.read()


async def preparer_pour_asr(octets: bytes) -> bytes:
    """WAV prêt pour l'ASR, ou `ErreurAudio`."""
    if not octets:
        raise ErreurAudio("audio_vide", "Je n'ai rien entendu. Appuyez sur le micro et parlez.")
    if len(octets) > OCTETS_MAX:
        raise ErreurAudio("audio_trop_volumineux", "Votre message est trop long. Parlez un peu moins longtemps à la fois.")

    format_audio = detecter_format(octets)
    if format_audio == "inconnu":
        raise ErreurAudio("format_audio_inconnu", "Je n'ai pas pu lire votre message vocal. Pouvez-vous le redire ?")

    if format_audio != "wav":
        executable = chemin_ffmpeg()
        if not executable:
            raise ErreurAudio("format_audio_non_supporte", "Je n'ai pas pu lire votre message vocal. Pouvez-vous le redire ?")
        try:
            octets = await asyncio.to_thread(_convertir_sync, octets, executable)
        except subprocess.TimeoutExpired:
            raise ErreurAudio("conversion_audio_echouee", "Je n'ai pas pu lire votre message vocal. Pouvez-vous le redire ?")

    duree = duree_wav_secondes(octets)
    if duree is not None and duree < DUREE_MIN_SECONDES:
        raise ErreurAudio("audio_trop_court", "Je n'ai rien entendu. Gardez le doigt sur le micro pendant que vous parlez.")
    if duree is not None and duree > DUREE_MAX_SECONDES + 1:
        raise ErreurAudio("audio_trop_long", "Votre message est trop long. Parlez un peu moins longtemps à la fois.")
    return octets
