"""
Le pulaar validé court-circuite le traducteur (plan maître, étape 3).

Le pulaar est incohérent parce que des phrases connues d'avance sont
retraduites à chaque conversation, différemment à chaque fois. Ce qui est
verrouillé ici :

  * une réponse entièrement relue ne fait AUCUN appel au modèle ;
  * un seul morceau manquant fait repasser toute la réponse par le traducteur,
    comme avant — jamais de dégradation ;
  * une traduction présente mais NON RELUE n'est jamais prononcée ;
  * ce qui a dû être traduit à la volée est signalé (étape 3.5).
"""
from __future__ import annotations

import asyncio

import pytest

from services import demarche, phrases
from temps_reel import parole


class _EmetteurEspion:
    def __init__(self):
        self.json: list[dict] = []
        self.octets: list[bytes] = []

    async def envoyer_json(self, message: dict) -> None:
        self.json.append(message)

    async def envoyer_octets(self, octets: bytes) -> None:
        self.octets.append(octets)


def _dire(reponse, *, appels: list):
    """Joue la phase de parole, en comptant les appels au traducteur."""
    emetteur = _EmetteurEspion()

    async def faux_traducteur(messages, temperature=0.3):
        appels.append(messages)
        for morceau in ("Pulaar improvisé ", "par le modèle."):
            yield morceau

    async def fausse_synthese(phrase: str) -> bytes:
        return phrase.encode()

    pulaar = asyncio.run(parole.dire(
        emetteur,
        texte_fr=reponse.francais,
        contexte_question="peu importe",
        premier_tour=False,
        turn_id="t1",
        reponse=reponse,
        flux_traduction=faux_traducteur,
        synthetiser=fausse_synthese,
    ))
    return pulaar, emetteur


VALIDEE = phrases.Phrase(
    francais="Quelle est sa date de naissance exacte ?",
    pulaar="Ñalnde jibineede makko ko honnde?",
    pulaar_valide=True,
    origine="champ:date_naissance_enfant",
)
CONFIRMATION = phrases.Phrase(
    francais="C'est noté.", pulaar="Winndaama.", pulaar_valide=True, origine="systeme:confirmation_reponse"
)
NON_RELUE = phrases.Phrase(
    francais="Quel est le nom de la maman ?",
    pulaar="TRADUCTION AUTOMATIQUE NON RELUE",
    pulaar_valide=False,
    origine="champ:nom_mere",
)


@pytest.fixture(autouse=True)
def _compteur_propre():
    phrases.reinitialiser_signalements()
    yield
    phrases.reinitialiser_signalements()


class TestCourtCircuit:
    def test_une_reponse_entierement_relue_n_appelle_pas_le_modele(self):
        appels: list = []
        pulaar, emetteur = _dire(phrases.reponse(CONFIRMATION, VALIDEE), appels=appels)

        assert appels == [], "aucun appel au traducteur"
        assert pulaar == "Winndaama. Ñalnde jibineede makko ko honnde?"
        assert emetteur.octets, "la synthèse a bien reçu quelque chose"

    def test_un_seul_morceau_manquant_fait_tout_retraduire(self):
        # Pas de traduction morceau par morceau : le modèle perdrait le
        # contexte de la phrase entière, dont la règle du « Salam ».
        appels: list = []
        pulaar, _ = _dire(phrases.reponse(CONFIRMATION, NON_RELUE), appels=appels)

        assert len(appels) == 1
        assert pulaar == "Pulaar improvisé par le modèle."

    def test_une_traduction_non_relue_n_est_jamais_dite(self):
        appels: list = []
        pulaar, _ = _dire(phrases.reponse(NON_RELUE), appels=appels)
        assert "NON RELUE" not in pulaar

    def test_sans_morceaux_le_comportement_est_celui_d_avant(self):
        # Compatibilité : un appelant qui ne fournit rien fait traduire, comme
        # avant l'étape 3.
        emetteur = _EmetteurEspion()
        appels: list = []

        async def faux_traducteur(messages, temperature=0.3):
            appels.append(messages)
            yield "Pulaar."

        async def fausse_synthese(phrase: str) -> bytes:
            return b"wav"

        asyncio.run(parole.dire(
            emetteur, texte_fr="Bonjour.", contexte_question="q", premier_tour=True, turn_id="t",
            flux_traduction=faux_traducteur, synthetiser=fausse_synthese,
        ))
        assert len(appels) == 1

    def test_le_texte_pulaar_est_bien_diffuse_au_client(self):
        _, emetteur = _dire(phrases.reponse(VALIDEE), appels=[])
        flux = [m["content"] for m in emetteur.json if m["type"] == "stream_pulaar"]
        assert "".join(flux) == VALIDEE.pulaar
        assert any(m["type"] == "tts_end" for m in emetteur.json)


class TestSignalement:
    def test_ce_qui_a_ete_traduit_a_la_volee_est_signale(self):
        # Sans ce compteur, une phrase oubliée resterait traduite par le
        # modèle pour toujours, sans que personne ne s'en aperçoive.
        _dire(phrases.reponse(CONFIRMATION, NON_RELUE), appels=[])
        assert phrases.signalements() == {"champ:nom_mere": 1}

    def test_une_reponse_validee_ne_signale_rien(self):
        _dire(phrases.reponse(CONFIRMATION, VALIDEE), appels=[])
        assert phrases.signalements() == {}


class TestAssemblage:
    def test_le_francais_reste_la_concatenation_des_morceaux(self):
        assemblee = phrases.reponse(CONFIRMATION, VALIDEE)
        assert assemblee.francais == "C'est noté. Quelle est sa date de naissance exacte ?"

    def test_les_morceaux_vides_et_absents_sont_ignores(self):
        assemblee = phrases.reponse(None, "", CONFIRMATION, "   ")
        assert len(assemblee.morceaux) == 1

    def test_une_chaine_devient_un_morceau_sans_pulaar(self):
        assemblee = phrases.reponse("Texte écrit dans le code.")
        assert assemblee.entierement_validee is False
        assert assemblee.a_valider()[0].origine == "texte_libre"

    def test_une_reponse_vide_n_est_pas_consideree_validee(self):
        # Sinon un tour sans rien à dire court-circuiterait la synthèse et le
        # citoyen n'entendrait rien, sans qu'aucune erreur ne soit levée.
        assert phrases.Reponse(()).entierement_validee is False


CHAMP_AVEC_RELANCES = {
    "type_demarche": "d", "nom_champ": "date_naissance", "type_valeur": "date", "ordre": 10,
    "obligatoire": True, "question": "Quelle est sa date de naissance ?",
    "relances": ["Je n'ai pas bien compris. Quelle est sa date de naissance ?",
                 "Reprenons doucement. Quelle est sa date de naissance ?"],
    "relances_pulaar": ["Mi faamaani. Ñalnde jibineede makko?", "En fuɗɗitto. Ñalnde jibineede makko?"],
    "pulaar_valide": True,
}


class TestRelances:
    """
    La relance était IMPROVISÉE par le modèle, donc retraduite à chaque fois —
    au moment précis où le citoyen ne comprend déjà pas la question.
    """

    def test_les_relances_sont_prises_a_tour_de_role(self):
        # Deux relances consécutives identiques mot pour mot donnent au
        # citoyen l'impression de ne pas être entendu.
        textes = [demarche.relance_champ(CHAMP_AVEC_RELANCES, n).francais for n in range(4)]
        assert textes[0] != textes[1]
        assert textes[2] == textes[0], "on boucle sur les variantes"
        assert textes[3] == textes[1]

    def test_une_relance_porte_son_pulaar_valide(self):
        assert demarche.relance_champ(CHAMP_AVEC_RELANCES, 0).pulaar_pret() == "Mi faamaani. Ñalnde jibineede makko?"

    def test_sans_relance_declaree_la_question_est_reposee(self):
        # Jamais rien d'inventé : à défaut de relance, on repose la question.
        nu = {"nom_champ": "x", "question": "La question ?", "relances": []}
        assert demarche.relance_champ(nu, 0).francais == "La question ?"

    def test_le_tour_de_collecte_dit_la_relance_de_la_base_pas_celle_du_modele(self, monkeypatch):
        import slot_controller

        monkeypatch.setattr(slot_controller, "charger_definition_demarche",
                            lambda _t, _v=None: [CHAMP_AVEC_RELANCES])
        monkeypatch.setattr(slot_controller, "charger_documents_demarche", lambda _t, _v=None: [])
        monkeypatch.setattr(slot_controller, "list_documents", lambda _id: [])

        async def modele_bavard(_headers, _payload, retries=2):
            return {
                "reponse_valide": False, "valeur": None,
                "reponse": "PHRASE INVENTÉE PAR LE MODÈLE",
            }

        monkeypatch.setattr(slot_controller, "_call_openrouter_structured_isole", modele_bavard)

        etat = {"slots": {}, "type_demarche": "d", "dossier_id": None}
        resultat = asyncio.run(slot_controller.traiter_tour_administratif(etat, "je m'appelle Moussa", {}))

        assert "INVENTÉE" not in (resultat["reponse_fr"] or "")
        assert resultat["reponse_fr"] == CHAMP_AVEC_RELANCES["relances"][0]
        # Et comme elle est relue, ce tour ne passe pas par le traducteur.
        assert resultat["reponse"].entierement_validee is True

    def test_la_reformulation_du_modele_sert_encore_a_le_recontextualiser(self, monkeypatch):
        # Elle n'est plus DITE, mais elle reste utile : au tour suivant, le
        # prompt rappelle au modèle pourquoi la réponse précédente a échoué.
        import slot_controller

        monkeypatch.setattr(slot_controller, "charger_definition_demarche",
                            lambda _t, _v=None: [CHAMP_AVEC_RELANCES])
        monkeypatch.setattr(slot_controller, "charger_documents_demarche", lambda _t, _v=None: [])
        monkeypatch.setattr(slot_controller, "list_documents", lambda _id: [])

        async def modele(_headers, _payload, retries=2):
            return {"reponse_valide": False, "valeur": None, "reponse": "Vous avez donné un nom."}

        monkeypatch.setattr(slot_controller, "_call_openrouter_structured_isole", modele)

        etat = {"slots": {}, "type_demarche": "d", "dossier_id": None}
        asyncio.run(slot_controller.traiter_tour_administratif(etat, "Moussa", {}))
        assert etat["dernieres_raisons"]["date_naissance"] == "Vous avez donné un nom."


class TestPhrasesSysteme:
    def test_une_cle_inconnue_ne_fait_pas_taire_l_agent(self):
        secours = demarche.phrase_systeme("cle_qui_n_existe_pas")
        assert secours.francais, "un silence serait pire pour quelqu'un qui ne lit pas"

    def test_le_repli_fournit_le_texte_francais_sans_pulaar(self):
        # Le conftest coupe les tables : on doit retrouver le texte figé.
        phrase = demarche.phrase_systeme("confirmation_reponse")
        assert phrase.francais == "C'est noté."
        assert phrase.pulaar_pret() is None
