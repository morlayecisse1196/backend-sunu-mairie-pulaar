import asyncio

import pytest

from temps_reel import parole
from tts_client import TTSError


class EmetteurMemoire:
    def __init__(self):
        self.evenements = []

    async def envoyer_json(self, message):
        self.evenements.append(("json", message))

    async def envoyer_octets(self, octets):
        self.evenements.append(("audio", octets))


def _flux(morceaux, pause=0.0):
    async def flux(messages, **kwargs):
        for morceau in morceaux:
            if pause:
                await asyncio.sleep(pause)
            yield morceau

    return flux


def test_decoupage_en_phrases():
    phrases, reste = parole.extraire_phrases_completes("Salam. Mi yiɗi wallude ma hannde. Njaŋtu")
    assert phrases == ["Mi yiɗi wallude ma hannde."] or phrases == ["Salam. Mi yiɗi wallude ma hannde."]
    assert reste == "Njaŋtu"


async def test_audio_envoye_dans_l_ordre_malgre_des_syntheses_de_durees_differentes():
    emetteur = EmetteurMemoire()
    durees = {"Première phrase assez longue.": 0.05, "Deuxième phrase assez longue.": 0.0}

    async def synthetiser(phrase):
        await asyncio.sleep(durees.get(phrase, 0.0))
        return phrase.encode()

    pulaar = await parole.dire(
        emetteur, texte_fr="x", contexte_question="q", premier_tour=False, turn_id="t1",
        flux_traduction=_flux(["Première phrase assez longue. ", "Deuxième phrase assez longue."]),
        synthetiser=synthetiser,
    )
    assert pulaar == "Première phrase assez longue. Deuxième phrase assez longue."
    audios = [valeur for type_, valeur in emetteur.evenements if type_ == "audio"]
    assert audios == [b"Premi\xc3\xa8re phrase assez longue.", "Deuxième phrase assez longue.".encode()]
    types = [m.get("type") for t, m in emetteur.evenements if t == "json"]
    assert types.index("status") < types.index("tts_progress")
    assert types[-1] == "tts_end"


async def test_erreur_de_synthese_signalee_sans_interrompre_la_suite():
    emetteur = EmetteurMemoire()

    async def synthetiser(phrase):
        if phrase.startswith("Cassée"):
            raise TTSError("space indisponible")
        return b"ok"

    await parole.dire(
        emetteur, texte_fr="x", contexte_question="q", premier_tour=False, turn_id="t1",
        flux_traduction=_flux(["Cassée mais longue phrase. ", "Deuxième phrase qui passe."]),
        synthetiser=synthetiser,
    )
    erreurs = [m for t, m in emetteur.evenements if t == "json" and m["type"] == "error"]
    assert len(erreurs) == 1 and erreurs[0]["recuperable"] is True
    assert [v for t, v in emetteur.evenements if t == "audio"] == [b"ok"]


async def test_interruption_annule_tout_sans_tache_orpheline():
    emetteur = EmetteurMemoire()
    syntheses_demarrees = []

    async def synthetiser(phrase):
        syntheses_demarrees.append(phrase)
        await asyncio.sleep(10)
        return b"jamais"

    tache = asyncio.create_task(parole.dire(
        emetteur, texte_fr="x", contexte_question="q", premier_tour=False, turn_id="t1",
        flux_traduction=_flux(["Une première phrase complète. ", "Encore une autre phrase. "] * 5, pause=0.01),
        synthetiser=synthetiser,
    ))
    await asyncio.sleep(0.05)
    tache.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tache
    await asyncio.sleep(0)
    restantes = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
    assert restantes == []
    assert syntheses_demarrees  # la synthèse avait bien démarré avant la fin de la traduction
    assert not any(t == "audio" for t, _ in emetteur.evenements)
