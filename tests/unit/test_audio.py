import io
import math
import subprocess
import wave

import pytest

from temps_reel import audio


def _wav(duree_s: float, frequence=16000) -> bytes:
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as fichier:
        fichier.setnchannels(1)
        fichier.setsampwidth(2)
        fichier.setframerate(frequence)
        echantillons = bytearray()
        for i in range(int(duree_s * frequence)):
            valeur = int(8000 * math.sin(2 * math.pi * 440 * i / frequence))
            echantillons += valeur.to_bytes(2, "little", signed=True)
        fichier.writeframes(bytes(echantillons))
    return tampon.getvalue()


def test_detection_des_formats():
    assert audio.detecter_format(_wav(0.5)) == "wav"
    assert audio.detecter_format(b"OggS" + b"\x00" * 20) == "ogg"
    assert audio.detecter_format(b"\x1a\x45\xdf\xa3" + b"\x00" * 20) == "webm"
    assert audio.detecter_format(b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 20) == "m4a"
    assert audio.detecter_format(b"ID3" + b"\x00" * 20) == "mp3"
    assert audio.detecter_format(b"n'importe quoi") == "inconnu"


def test_duree_wav():
    assert audio.duree_wav_secondes(_wav(2.0)) == pytest.approx(2.0, abs=0.01)


async def test_wav_valide_accepte_tel_quel():
    octets = _wav(1.0)
    assert await audio.preparer_pour_asr(octets) is octets


@pytest.mark.parametrize(
    "octets, code",
    [
        (b"", "audio_vide"),
        (b"pas de l'audio du tout", "format_audio_inconnu"),
    ],
)
async def test_audio_rejete(octets, code):
    with pytest.raises(audio.ErreurAudio) as exc:
        await audio.preparer_pour_asr(octets)
    assert exc.value.code == code
    assert exc.value.message_fr


async def test_appui_accidentel_trop_court():
    with pytest.raises(audio.ErreurAudio) as exc:
        await audio.preparer_pour_asr(_wav(0.1))
    assert exc.value.code == "audio_trop_court"


async def test_format_compresse_sans_ffmpeg(monkeypatch):
    monkeypatch.setattr(audio, "chemin_ffmpeg", lambda: None)
    with pytest.raises(audio.ErreurAudio) as exc:
        await audio.preparer_pour_asr(b"OggS" + b"\x00" * 100)
    assert exc.value.code == "format_audio_non_supporte"


@pytest.mark.skipif(audio.chemin_ffmpeg() is None, reason="ffmpeg absent de cette machine")
async def test_conversion_opus_vers_wav_16k(tmp_path):
    source = tmp_path / "source.wav"
    source.write_bytes(_wav(1.5, frequence=44100))
    opus = tmp_path / "message.ogg"
    subprocess.run([audio.chemin_ffmpeg(), "-loglevel", "error", "-y", "-i", str(source), "-c:a", "libopus", str(opus)], check=True)

    resultat = await audio.preparer_pour_asr(opus.read_bytes())
    assert audio.detecter_format(resultat) == "wav"
    with wave.open(io.BytesIO(resultat)) as fichier:
        assert fichier.getframerate() == 16000 and fichier.getnchannels() == 1
    assert audio.duree_wav_secondes(resultat) == pytest.approx(1.5, abs=0.1)
