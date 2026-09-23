"""
Étape 1 du plan maître — qualité du pulaar.

Deux régressions verrouillées ici :

1. **Les exemples du prompt du formateur étaient écrits en français** alors
   qu'ils sont présentés au modèle comme du pulaar (« Dialogue en pulaar : »
   suivi de « Vous avez besoin de votre pièce d'identité »). Le modèle apprend
   d'un exemple bien plus que d'une consigne : on lui montrait exactement ce
   qu'on lui interdit de faire.

2. **Les mots français partaient tels quels au synthétiseur.** `mms-tts-pul`
   est monolingue pulaar : il les lit avec les règles du pulaar et les rend
   inaudibles.
"""
from __future__ import annotations

import re

import pytest

from prompts import SYSTEM_PROMPT_FORMATTER
from services.pulaar import CORPUS, TERMES, bloc_glossaire, orthographe_tts
import tts_client


def _dialogues_exemples() -> list[str]:
    """Le contenu des blocs « Dialogue en pulaar : "..." » du prompt."""
    blocs = re.findall(
        r'Dialogue en pulaar :\s*"(.*?)"',
        SYSTEM_PROMPT_FORMATTER,
        flags=re.DOTALL,
    )
    assert blocs, "le prompt ne contient plus d'exemple de dialogue : test à revoir"
    return blocs


class TestExemplesDuPrompt:
    # Mots français courants qu'aucune phrase pulaar ne contient. « Salam » est
    # volontairement absent de la liste : il ouvre le premier tour.
    MOTS_FRANCAIS = (
        "vous", "votre", "pour", "avez", "besoin", "faut", "aller", "obtenir",
        "voulez", "commencer", "cette", "avec", "dans",
    )

    def test_les_exemples_sont_bien_en_pulaar(self):
        for dialogue in _dialogues_exemples():
            mots = set(re.findall(r"\w+", dialogue.lower()))
            intrus = mots & set(self.MOTS_FRANCAIS)
            assert not intrus, (
                f"exemple donné au modèle comme du pulaar mais écrit en français : {sorted(intrus)}\n"
                f"→ {dialogue}"
            )

    def test_le_premier_exemple_ouvre_par_la_salutation(self):
        # Le prompt enseigne la règle « Salam » par l'exemple 1 uniquement.
        premier, *suivants = _dialogues_exemples()
        assert premier.startswith("Salam")
        for dialogue in suivants:
            assert "Salam" not in dialogue, "un tour suivant ne doit jamais se saluer"

    def test_le_glossaire_est_injecte(self):
        assert bloc_glossaire() in SYSTEM_PROMPT_FORMATTER

    def test_les_exemples_respectent_le_glossaire(self):
        # Un exemple qui contredirait le glossaire annulerait son effet.
        texte = " ".join(_dialogues_exemples())
        for terme in TERMES:
            if terme.francais in ("mairie", "pièce d'identité", "extrait de naissance"):
                assert terme.pulaar in texte, f"« {terme.francais} » attendu sous la forme « {terme.pulaar} »"


class TestGlossaire:
    def test_chaque_terme_est_present_une_seule_fois(self):
        francais = [t.francais for t in TERMES]
        assert len(francais) == len(set(francais))

    def test_une_entree_du_corpus_porte_son_nombre_doccurrences(self):
        # Sans ce nombre, impossible de distinguer une forme attestée 200 fois
        # d'une forme vue trois fois : la relecture ne saurait pas où insister.
        for terme in TERMES:
            if terme.source == CORPUS:
                assert terme.occurrences > 0, terme.francais
            else:
                assert terme.occurrences == 0, terme.francais

    def test_le_bloc_cite_tous_les_termes(self):
        bloc = bloc_glossaire()
        for terme in TERMES:
            assert terme.pulaar in bloc


class TestOrthographeTts:
    def test_le_terme_le_plus_long_gagne(self):
        # Le piège : « acte » seul remplacerait le début de « acte de naissance »
        # et laisserait « de naissance » en français derrière lui.
        assert orthographe_tts("Yah to acte de naissance") == "Yah to akte de nesaas"

    def test_un_terme_generique_ne_mange_pas_les_termes_composes(self):
        # « certificat » est lui-même dans le glossaire : il ne doit pas être
        # substitué AVANT « certificat de résidence », sinon il resterait
        # « sertifika de résidence », moitié pulaar moitié français.
        assert orthographe_tts("Addu certificat de résidence") == "Addu sertifika hoɗorde"
        assert orthographe_tts("Addu certificat") == "Addu sertifika"

    @pytest.mark.parametrize("terme", [t for t in TERMES if t.prononciation])
    def test_chaque_terme_du_glossaire_est_bien_substitue(self, terme):
        # Un terme long masqué par un terme plus court partirait en partie en
        # français au synthétiseur, sans que rien ne le signale.
        reecrit = orthographe_tts(f"Yah {terme.francais} jooni")
        assert terme.francais.lower() not in reecrit.lower()

    def test_insensible_a_la_casse(self):
        assert orthographe_tts("Mairie") == "meeri"

    def test_ne_coupe_pas_un_mot_plus_long(self):
        # « mairie » ne doit pas être remplacé à l'intérieur d'un autre mot.
        assert orthographe_tts("mairies") == "mairies"

    def test_laisse_le_pulaar_intact(self):
        phrase = "Aɗa jogii kaayit ganndinirgal maa?"
        assert orthographe_tts(phrase) == phrase

    def test_les_montants_ne_sont_pas_touches(self):
        assert "200" in orthographe_tts("200 francs")

    @pytest.mark.parametrize("terme", [t for t in TERMES if t.prononciation])
    def test_aucune_substitution_ne_reintroduit_du_francais(self, terme):
        # Une prononciation qui contiendrait elle-même un terme du glossaire
        # serait réécrite au tour suivant : boucle instable.
        une_fois = orthographe_tts(terme.francais)
        assert orthographe_tts(une_fois) == une_fois


@pytest.mark.asyncio
async def test_la_synthese_recoit_lorthographe_adaptee(monkeypatch):
    """Le texte envoyé au modèle vocal est réécrit ; l'appelant, lui, n'a rien à faire."""
    envoyes: list[str] = []

    class _FausseReponse:
        content = b"WAV"

        def raise_for_status(self):
            return None

    class _FauxClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            envoyes.append(json["text"])
            return _FausseReponse()

    monkeypatch.setattr(tts_client.httpx, "AsyncClient", _FauxClient)

    await tts_client.synthesize_remote("Aɗa soklii une pièce d'identité")

    assert envoyes == ["Aɗa soklii une pyees didaŋtite"]
