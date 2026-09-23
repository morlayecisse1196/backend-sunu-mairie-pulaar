"""
Audio pré-généré des phrases relues (plan maître, étape 3.4).

Le Space vocal met plusieurs dizaines de secondes à repartir après une
inactivité. Le premier citoyen de la matinée pose sa question et n'entend
rien, devant un écran qu'il ne sait pas lire. Ce qui est verrouillé ici :

  * une phrase relue dont l'audio existe n'est NI traduite NI synthétisée ;
  * une phrase relue sans audio est synthétisée une fois, puis gardée —
    la personne suivante ne l'attend plus ;
  * un texte corrigé n'est JAMAIS dit avec l'ancien son : faire entendre la
    phrase d'avant après une correction serait pire que de faire attendre ;
  * un disque en panne ne coupe pas le dialogue.
"""
from __future__ import annotations

import asyncio

import pytest

from services import catalogue_audio, phrases
from temps_reel import parole


class _EmetteurEspion:
    def __init__(self):
        self.json: list[dict] = []
        self.octets: list[bytes] = []

    async def envoyer_json(self, message: dict) -> None:
        self.json.append(message)

    async def envoyer_octets(self, octets: bytes) -> None:
        self.octets.append(octets)


def _phrase(pulaar: str, *, valide: bool = True, origine: str = "champ:x") -> phrases.Phrase:
    return phrases.Phrase(
        francais="Peu importe, c'est le pulaar qui est dit.",
        pulaar=pulaar,
        pulaar_valide=valide,
        origine=origine,
    )


def _dire(reponse) -> tuple[_EmetteurEspion, list[str], list]:
    """Joue la phase de parole ; retourne (émetteur, textes synthétisés, appels au modèle)."""
    emetteur = _EmetteurEspion()
    synthetises: list[str] = []
    traductions: list = []

    async def fausse_synthese(texte: str) -> bytes:
        synthetises.append(texte)
        return f"SYNTHESE[{texte}]".encode()

    async def faux_traducteur(messages, temperature=0.3):
        traductions.append(messages)
        yield "Pulaar du modèle."

    asyncio.run(parole.dire(
        emetteur,
        texte_fr=reponse.francais,
        contexte_question="peu importe",
        premier_tour=False,
        turn_id="t1",
        reponse=reponse,
        flux_traduction=faux_traducteur,
        synthetiser=fausse_synthese,
    ))
    return emetteur, synthetises, traductions


QUESTION = "Ñalnde jibineede makko ko honnde?"
CONFIRMATION = "Winndaama."


class TestCleParEmpreinte:
    def test_deux_textes_differents_ont_des_cles_differentes(self):
        assert catalogue_audio.cle_phrase(QUESTION) != catalogue_audio.cle_phrase(CONFIRMATION)

    def test_la_meme_phrase_donne_toujours_la_meme_cle(self):
        # C'est ce qui rend le cache utile d'une conversation à l'autre.
        assert catalogue_audio.cle_phrase(QUESTION) == catalogue_audio.cle_phrase(" " + QUESTION + " ")

    def test_une_majuscule_corrigee_change_la_cle(self):
        # Volontairement plus strict que `cle_pour_texte` : toute retouche du
        # relecteur doit provoquer une resynthèse.
        assert catalogue_audio.cle_phrase("Winndaama.") != catalogue_audio.cle_phrase("winndaama.")

    def test_un_terme_qui_entre_au_glossaire_change_la_cle(self, monkeypatch):
        # L'empreinte porte sur le texte RÉELLEMENT envoyé au synthétiseur.
        # Sans cela, l'audio continuerait de dire « extrait de naissance » à la
        # française longtemps après l'entrée du terme au glossaire, et personne
        # ne s'en apercevrait : le texte en base, lui, n'a pas bougé.
        import re

        from services import pulaar

        texte = "Mi yiɗi extrait de naissance."
        avant = catalogue_audio.cle_phrase(texte)
        monkeypatch.setattr(pulaar, "_SUBSTITUTIONS", [
            (re.compile(r"extrait de naissance", re.IGNORECASE), "deftere wulngo"),
        ])
        assert catalogue_audio.cle_phrase(texte) != avant

    def test_un_texte_vide_n_a_pas_d_audio(self):
        assert asyncio.run(catalogue_audio.audio_phrase("")) is None
        assert catalogue_audio.phrase_deja_generee("   ") is False


class TestEnregistrement:
    def test_ce_qui_est_range_est_relu_tel_quel(self):
        cle = asyncio.run(catalogue_audio.enregistrer_phrase(QUESTION, b"DES OCTETS WAV"))
        assert cle is not None
        assert catalogue_audio.phrase_deja_generee(QUESTION) is True
        assert asyncio.run(catalogue_audio.audio_phrase(QUESTION)) == b"DES OCTETS WAV"

    def test_un_disque_en_panne_ne_leve_pas(self, monkeypatch):
        # Le dialogue doit continuer : la phrase sera simplement resynthétisée
        # la prochaine fois.
        monkeypatch.setattr(catalogue_audio, "DOSSIER_PHRASES", "\0chemin impossible")
        assert asyncio.run(catalogue_audio.enregistrer_phrase(QUESTION, b"x")) is None


class TestDialogue:
    def test_une_phrase_deja_generee_n_est_ni_traduite_ni_synthetisee(self):
        asyncio.run(catalogue_audio.enregistrer_phrase(QUESTION, b"AUDIO PRE-GENERE"))

        emetteur, synthetises, traductions = _dire(phrases.reponse(_phrase(QUESTION)))

        assert traductions == [], "aucun appel au traducteur (étape 3.3)"
        assert synthetises == [], "aucun appel à la synthèse (étape 3.4)"
        assert emetteur.octets == [b"AUDIO PRE-GENERE"]

    def test_une_phrase_relue_sans_audio_est_synthetisee_puis_gardee(self):
        emetteur, synthetises, _ = _dire(phrases.reponse(_phrase(QUESTION)))
        assert synthetises == [QUESTION], "la première personne paie la synthèse"
        assert emetteur.octets == [f"SYNTHESE[{QUESTION}]".encode()]

        # La personne suivante ne l'attend plus.
        emetteur2, synthetises2, _ = _dire(phrases.reponse(_phrase(QUESTION)))
        assert synthetises2 == []
        assert emetteur2.octets == [f"SYNTHESE[{QUESTION}]".encode()]

    def test_un_texte_corrige_n_est_jamais_dit_avec_l_ancien_son(self):
        asyncio.run(catalogue_audio.enregistrer_phrase(QUESTION, b"ANCIEN SON"))
        corrige = QUESTION.replace("honnde", "ndeye")

        emetteur, synthetises, _ = _dire(phrases.reponse(_phrase(corrige)))

        assert synthetises == [corrige], "le texte corrigé repart à la synthèse"
        assert b"ANCIEN SON" not in emetteur.octets

    def test_les_morceaux_gardent_leur_ordre_meme_quand_un_seul_est_en_cache(self):
        # Le confirmateur vient du disque, la question de la synthèse : le
        # citoyen doit quand même entendre « C'est noté. » en premier.
        asyncio.run(catalogue_audio.enregistrer_phrase(CONFIRMATION, b"AUDIO CONFIRMATION"))

        emetteur, synthetises, _ = _dire(
            phrases.reponse(_phrase(CONFIRMATION, origine="systeme:x"), _phrase(QUESTION))
        )

        assert synthetises == [QUESTION]
        assert emetteur.octets == [b"AUDIO CONFIRMATION", f"SYNTHESE[{QUESTION}]".encode()]

    def test_une_phrase_non_relue_n_utilise_jamais_l_audio_pre_genere(self):
        # Même si un audio traîne pour ce texte : il n'a pas été relu, donc il
        # n'a jamais dû être généré, et il ne doit surtout pas être dit.
        asyncio.run(catalogue_audio.enregistrer_phrase(QUESTION, b"AUDIO NON RELU"))

        emetteur, _, traductions = _dire(phrases.reponse(_phrase(QUESTION, valide=False)))

        assert len(traductions) == 1, "toute la réponse repasse par le traducteur"
        assert b"AUDIO NON RELU" not in emetteur.octets

    def test_un_echec_de_synthese_ne_coupe_pas_le_tour(self):
        from tts_client import TTSError

        emetteur = _EmetteurEspion()

        async def synthese_en_panne(texte: str) -> bytes:
            raise TTSError("Space injoignable")

        async def faux_traducteur(messages, temperature=0.3):
            yield "rien"

        asyncio.run(parole.dire(
            emetteur, texte_fr="fr", contexte_question="q", premier_tour=False, turn_id="t",
            reponse=phrases.reponse(_phrase(QUESTION)),
            flux_traduction=faux_traducteur, synthetiser=synthese_en_panne,
        ))

        assert any(m["type"] == "tts_end" for m in emetteur.json)
        assert catalogue_audio.phrase_deja_generee(QUESTION) is False, \
            "un échec n'est pas rangé comme s'il était un audio"


class TestPreGeneration:
    """Ce que le script pré-génère, et surtout ce qu'il ne pré-génère pas."""

    @staticmethod
    def _phrase(identifiant, pulaar, valide, table, colonne, index=None):
        from services import atelier

        return atelier.Phrase(
            identifiant=identifiant, francais="Peu importe.", pulaar=pulaar,
            valide=valide, contexte="c",
            cible=atelier.Cible(table, "cle", "x", colonne, index),
        )

    @pytest.fixture
    def script(self, monkeypatch):
        from services import atelier

        import scripts.pregenerer_audio as pregenerer

        lignes = [
            self._phrase("champ:nom:question", QUESTION, True, "demarche_champs", "question_pulaar"),
            self._phrase("systeme:confirmation", CONFIRMATION, False, "phrases_systeme", "pulaar"),
            self._phrase("gabarit:recapitulatif", "Ko {nom_enfant}.", True, "demarche_gabarits", "pulaar"),
            self._phrase("champ:vide:question", "", True, "demarche_champs", "question_pulaar"),
        ]
        monkeypatch.setattr(atelier, "collecter", lambda _t=None: lignes)
        return pregenerer

    def test_seules_les_phrases_relues_sont_generees(self, script):
        retenues, en_attente = script._a_generer("extrait_naissance")
        assert [p.identifiant for p in retenues] == ["champ:nom:question"]
        assert en_attente == 1, "la phrase traduite mais non relue est signalée, pas générée"

    def test_un_gabarit_a_trous_n_est_jamais_pre_genere(self, script):
        # Son texte final dépend du dossier du citoyen.
        retenues, _ = script._a_generer("extrait_naissance")
        assert all(p.cible.table != "demarche_gabarits" for p in retenues)

    def test_le_nettoyage_ne_garde_que_les_audios_encore_dits(self, script):
        asyncio.run(catalogue_audio.enregistrer_phrase(QUESTION, b"encore dit"))
        asyncio.run(catalogue_audio.enregistrer_phrase("Texte supprimé depuis.", b"perime"))

        retenues, _ = script._a_generer("extrait_naissance")
        script._nettoyer(retenues)

        assert catalogue_audio.phrase_deja_generee(QUESTION) is True
        assert catalogue_audio.phrase_deja_generee("Texte supprimé depuis.") is False

    def test_une_relance_n_a_pas_de_colonne_d_audio_a_renseigner(self, script):
        # Son audio se retrouve par empreinte : aucune colonne à tenir à jour,
        # donc aucun tableau de drapeaux à garder aligné.
        relance = self._phrase("champ:nom:relance0", "Texte.", True,
                               "demarche_champs", "relances_pulaar", 0)
        script._noter_la_cle(relance, "pul_quelconque")  # ne doit rien tenter d'écrire
