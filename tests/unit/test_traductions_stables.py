"""
Deux fois la même phrase française doivent donner deux fois le même pulaar.

CE QUI N'ALLAIT PAS

Le traducteur de production est `google/gemini-2.5-flash` — pas le NLLB
affiné du projet, qui n'est branché nulle part. Mesuré sur la base réelle, une
même phrase traduite trois fois de suite donnait trois pulaar différents :

    « Dans quelle commune votre enfant est-il né ? »
      -> to komin hono?    to komin yiɗi?    to komin goɗɗum?

Et sur « numéro de suivi » : `limoore jokkondiral`, `limoore maa`,
`limoore reentagol` — trois mots pour la chose que le citoyen doit retenir.

LE COÛT CACHÉ

Le cache audio est indexé sur le texte pulaar réellement prononcé. Un pulaar
qui change à chaque fois ne retombe jamais sur un fichier déjà synthétisé :
chaque tour repaie une synthèse complète, mesurée à 7,6 s.
"""
from __future__ import annotations

import pytest

from prompts import SYSTEM_PROMPT_FORMATTER
import asyncio

from services import traductions
from temps_reel import parole


@pytest.fixture(autouse=True)
def cache_isole(monkeypatch, tmp_path):
    """Chaque test a son dossier : rien ne fuit d'un test à l'autre."""
    monkeypatch.setattr(traductions, "DOSSIER", str(tmp_path / "traductions"))


class TestLaCle:
    def test_la_meme_demande_donne_la_meme_cle(self):
        a = traductions.cle("consigne", "Traduire : bonjour")
        b = traductions.cle("consigne", "Traduire : bonjour")
        assert a == b

    def test_un_contexte_different_donne_une_cle_differente(self):
        # « premier tour » fait ajouter « Salam. » : deux contextes ne doivent
        # pas se partager une entrée.
        a = traductions.cle("consigne", "Premier tour. Traduire : bonjour")
        b = traductions.cle("consigne", "Tour suivant. Traduire : bonjour")
        assert a != b

    def test_changer_la_consigne_invalide_le_cache(self):
        """
        L'empreinte porte sur TOUT ce qui est envoyé au modèle, consigne
        comprise : retoucher le prompt du traducteur périme les traductions
        d'avant, sans qu'on ait à y penser.
        """
        avant = traductions.cle(SYSTEM_PROMPT_FORMATTER, "Traduire : bonjour")
        apres = traductions.cle(SYSTEM_PROMPT_FORMATTER + "\nNouvelle règle.", "Traduire : bonjour")
        assert avant != apres


class TestLaMemoire:
    def test_ce_quon_range_se_relit(self):
        identifiant = traductions.cle("c", "u")
        traductions.ranger(identifiant, "Salam. Jam tan.")
        assert traductions.lire(identifiant) == "Salam. Jam tan."

    def test_rien_en_memoire_rend_None(self):
        assert traductions.lire(traductions.cle("c", "jamais vue")) is None

    def test_une_traduction_vide_nest_pas_rangee(self):
        # Sinon un appel raté figerait un silence pour toujours.
        identifiant = traductions.cle("c", "u")
        traductions.ranger(identifiant, "   ")
        assert traductions.lire(identifiant) is None

    def test_un_disque_en_lecture_seule_ne_fait_pas_echouer_le_tour(self, monkeypatch):
        """
        Le citoyen attend sa réponse : un cache qui ne peut pas écrire doit se
        taire, jamais interrompre la parole.
        """
        def refuse(*_a, **_k):
            raise OSError("disque plein")

        monkeypatch.setattr(traductions.os, "makedirs", refuse)
        traductions.ranger(traductions.cle("c", "u"), "Jam tan.")  # ne lève pas

    def test_une_ecriture_interrompue_ne_laisse_pas_de_moitie(self, monkeypatch):
        """
        Écriture puis renommage : un arrêt au mauvais moment laisserait sinon
        un fichier à moitié écrit, relu comme une traduction valable et dit
        au citoyen.
        """
        identifiant = traductions.cle("c", "u")

        def echoue_au_renommage(*_a, **_k):
            raise OSError("coupure")

        monkeypatch.setattr(traductions.os, "replace", echoue_au_renommage)
        traductions.ranger(identifiant, "Moitié de phrase")
        assert traductions.lire(identifiant) is None


class TestLeTourCompletUtiliseLaMemoire:
    """Le vrai comportement, en appelant `parole.dire` comme le serveur."""

    class EmetteurMemoire:
        def __init__(self):
            self.evenements = []

        async def envoyer_json(self, message):
            self.evenements.append(("json", message))

        async def envoyer_octets(self, octets):
            self.evenements.append(("audio", octets))

    @staticmethod
    def _flux(morceaux, appels):
        async def flux(messages, **kwargs):
            appels.append(True)
            for morceau in morceaux:
                yield morceau

        return flux

    @staticmethod
    async def _synthetiser(phrase):
        return phrase.encode()

    def _dire(self, appels, emetteur=None):
        emetteur = emetteur or self.EmetteurMemoire()
        return asyncio.run(parole.dire(
            emetteur,
            texte_fr="C'est noté. Dans quelle commune votre enfant est-il né ?",
            contexte_question="", premier_tour=False, turn_id="t1",
            flux_traduction=self._flux(["Mi faamii. ", "Ɓiɗɗo maa jibinaa to komin hono?"], appels),
            synthetiser=self._synthetiser,
        ))

    def test_le_premier_tour_appelle_le_modele_et_garde_le_resultat(self):
        appels = []
        pulaar = self._dire(appels)
        assert appels, "le modèle aurait dû être appelé la première fois"
        assert "Ɓiɗɗo maa jibinaa" in pulaar

    def test_le_second_tour_ne_rappelle_plus_le_modele(self):
        """
        Le cœur du correctif : même demande, même pulaar, sans nouvel appel —
        donc sans nouvelle synthèse non plus, puisque le cache audio est
        indexé sur le texte réellement prononcé.
        """
        premiers, seconds = [], []
        attendu = self._dire(premiers)
        obtenu = self._dire(seconds)
        assert premiers and not seconds, "le modèle a été rappelé pour la même demande"
        assert obtenu == attendu, "le pulaar a changé entre deux tours identiques"
