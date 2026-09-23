"""
Script de diagnostic — teste la qualité RÉELLE de l'ASR pulaar déployé
(ASR_API_URL, asr_client.transcribe_audio) SANS microphone : synthétise de
vraies phrases pulaar avec le VRAI service TTS déjà utilisé en production
(tts_client.synthesize_remote — un Space HF distinct de l'ASR), puis renvoie
cet audio à l'ASR et compare la transcription obtenue au texte pulaar
d'origine.

Limite honnête : une voix synthétique est plus propre qu'une vraie voix
humaine (accent, bruit de fond, débit) — un échec ICI est donc un signal
FORT (le modèle a du mal même dans des conditions idéales), mais un succès
ICI ne garantit pas la même qualité sur de la vraie parole enregistrée au
téléphone. Sert à trancher : si même ces phrases synthétiques bien
prononcées sont mal transcrites, un nouveau fine-tuning (ou un modèle de
base différent) est clairement justifié plutôt qu'un simple doute.

Phrases réelles reprises de dataset_fra_pulaar.jsonl (fourni par
l'utilisateur, corpus d'entraînement du modèle) — jamais inventées, donc
représentatives du vrai vocabulaire/register attendu.
"""
import asyncio
import difflib
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from tts_client import synthesize_remote, TTSError
from asr_client import transcribe_audio

# Phrases réelles du corpus d'entraînement (dataset_fra_pulaar.jsonl), courtes
# à moyennes — comparables à ce qu'un citoyen dirait pendant le dialogue.
PHRASES_PULAAR = [
    "hande ina moƴƴi",
    "nabta ɗum hato galle to",
    "mi sikki aɗa foti hen ɓamde bache",
    "tooɓɓo ngo no hewiri ni",
    "ko ɗum ko hunde fotade rentede",
]


def similarite(a: str, b: str) -> float:
    """Ratio de similarité brut (difflib) — indicatif, pas un vrai WER (jiwer
    non disponible ici), mais suffisant pour juger d'un coup d'œil."""
    return difflib.SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


async def main_test():
    print("=" * 90)
    print("Test round-trip RÉEL : texte pulaar -> synthèse TTS (Space distant) -> ASR (Space distant)")
    print("=" * 90)

    resultats = []
    for i, phrase in enumerate(PHRASES_PULAAR, start=1):
        print(f"\n--- Phrase {i}/{len(PHRASES_PULAAR)} ---")
        print(f"  Texte pulaar d'origine : {phrase!r}")
        try:
            audio_bytes = await synthesize_remote(phrase)
        except TTSError as e:
            print(f"  ⚠️ Synthèse TTS échouée : {e} — phrase ignorée.")
            continue
        print(f"  Audio synthétisé : {len(audio_bytes)} octets")

        resultat_asr = await transcribe_audio(audio_bytes)
        if not resultat_asr.get("success"):
            print(f"  ❌ Transcription ASR échouée : {resultat_asr.get('error')}")
            resultats.append((phrase, None, 0.0))
            continue

        transcription = resultat_asr.get("transcription", "")
        score = similarite(phrase, transcription)
        print(f"  Transcription ASR obtenue : {transcription!r}")
        print(f"  Similarité (indicative) : {score:.0%}")
        resultats.append((phrase, transcription, score))

    print("\n" + "=" * 90)
    print("RÉCAPITULATIF")
    print("=" * 90)
    for phrase, transcription, score in resultats:
        etat = "✅" if score >= 0.6 else ("⚠️" if score >= 0.3 else "❌")
        print(f"{etat} [{score:.0%}] {phrase!r} -> {transcription!r}")

    scores_valides = [s for _, t, s in resultats if t is not None]
    if scores_valides:
        moyenne = sum(scores_valides) / len(scores_valides)
        print(f"\nSimilarité moyenne : {moyenne:.0%} sur {len(scores_valides)} phrase(s) transcrite(s).")
        if moyenne < 0.35:
            print("\n⚠️  Similarité très faible même sur de l'audio synthétique propre —")
            print("   signal fort en faveur d'un nouveau fine-tuning (ou d'un modèle de base différent).")
        elif moyenne < 0.6:
            print("\n⚠️  Similarité moyenne/mitigée — le modèle reconnaît une partie du vocabulaire")
            print("   mais se trompe souvent ; un fine-tuning supplémentaire (ou plus de données/étapes)")
            print("   aiderait probablement.")
        else:
            print("\n✅ Similarité correcte sur de l'audio synthétique propre — le modèle semble")
            print("   fonctionner raisonnablement dans des conditions idéales. Le problème remonté")
            print("   par le citoyen vient alors plus probablement du bruit/accent/débit réel,")
            print("   pas d'un modèle fondamentalement mal entraîné.")
    else:
        print("\n❌ Aucune transcription n'a pu être obtenue — vérifier ASR_API_URL / la disponibilité du Space.")


if __name__ == "__main__":
    asyncio.run(main_test())
