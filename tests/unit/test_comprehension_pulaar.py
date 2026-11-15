"""
L'agent doit COMPRENDRE le pulaar, pas seulement le dire.

CE QUI N'ALLAIT PAS

`bloc_glossaire()` n'était injecté que dans le prompt du traducteur, qui va du
français VERS le pulaar. Les deux prompts qui LISENT le citoyen — mode
information et extraction de champ — n'en voyaient rien.

Joué de bout en bout en pulaar, avec le seul vocabulaire validé du projet, le
dialogue était bloqué du premier au dernier tour : douze tours, zéro champ
rempli. Au deuxième :

    citoyen : « Deftere wulngo »
    agent   : « Je ne comprends pas ce que tu veux dire par "Deftere wulngo" »

— à propos du terme de son propre glossaire pour « extrait de naissance ».

Et la recherche sémantique restait aveugle : le modèle d'embeddings ne connaît
pas le pulaar, donc une demande explicite tombait dans la même bande de
similarité que les salutations, et le prompt annonçait au modèle que
l'information trouvée était « probablement SANS RAPPORT ».
"""
from __future__ import annotations

import pytest

from prompts import SYSTEM_PROMPT_CHAMP_CIBLE, SYSTEM_PROMPT_FORMATTER, SYSTEM_PROMPT_GENERATOR
from services import pulaar, pulaar_nombres
from services.pulaar import TERMES, VALIDE, bloc_comprehension, vers_francais


class TestLeGlossaireEstDansLesDeuxSens:
    def test_le_traducteur_a_toujours_le_sien(self):
        # Français -> pulaar : ce qui existait déjà, et qui ne doit pas bouger.
        assert pulaar.bloc_glossaire() in SYSTEM_PROMPT_FORMATTER

    @pytest.mark.parametrize("prompt,nom", [
        (SYSTEM_PROMPT_GENERATOR, "mode information"),
        (SYSTEM_PROMPT_CHAMP_CIBLE, "extraction de champ"),
    ])
    def test_les_prompts_qui_LISENT_le_citoyen_ont_le_leur(self, prompt, nom):
        assert bloc_comprehension() in prompt, f"{nom} ne sait pas lire le pulaar"

    def test_le_terme_qui_bloquait_tout_y_figure(self):
        bloc = bloc_comprehension()
        assert "deftere wulngo" in bloc
        assert "extrait de naissance" in bloc

    def test_le_oui_le_non_et_les_chiffres_y_sont(self):
        bloc = bloc_comprehension()
        # L'agent prononce ces mots lui-même : il doit les reconnaître.
        assert pulaar_nombres.OUI in bloc and pulaar_nombres.NON in bloc
        for valeur in (1, 7, 10):
            mot = pulaar_nombres.nombre(valeur)
            assert mot in bloc, f"« {mot} » ({valeur}) est dit par l'agent mais absent du bloc"

    def test_un_mot_pulaar_ne_recoit_pas_deux_sens_contradictoires(self):
        """
        « acte de naissance » et « extrait de naissance » se disent tous deux
        « deftere wulngo ». Deux lignes séparées donneraient au modèle deux
        définitions pour un même mot.
        """
        lignes = [l for l in bloc_comprehension().splitlines() if l.startswith("- « ")]
        mots = [l.split("»")[0].removeprefix("- « ").strip() for l in lignes]
        assert len(mots) == len(set(mots)), "un mot pulaar apparaît sur deux lignes"


class TestLaRechercheVoitEnfinLePulaar:
    @pytest.mark.parametrize("pulaar_dit,francais_attendu", [
        ("deftere wulngo", "acte de naissance"),
        ("deftere maayde", "acte de décès"),
        ("deftere dewgal", "acte de mariage"),
        ("sertifika hoɗorde", "certificat de résidence"),
    ])
    def test_les_termes_valides_sont_reecrits(self, pulaar_dit, francais_attendu):
        assert vers_francais(pulaar_dit) == francais_attendu

    def test_le_terme_long_lemporte_sur_le_court(self):
        # « deftere » seul veut dire « document » : sans l'ordre par longueur,
        # « deftere wulngo » deviendrait « document wulngo », à moitié traduit.
        assert vers_francais("deftere wulngo") == "acte de naissance"

    @pytest.mark.parametrize("message", ["jam tan", "jaaraama", "Ibrahima Diallo", "Ross-Béthio"])
    def test_ce_qui_nest_pas_du_glossaire_nest_pas_touche(self, message):
        # Les salutations doivent RESTER sous le seuil de confiance : c'est ce
        # qui rend les deux bandes disjointes.
        assert vers_francais(message) == message

    def test_la_reecriture_ne_sapplique_quà_la_recherche(self):
        """
        Le message du citoyen n'est réécrit NULLE PART ailleurs : il a parlé
        pulaar, et c'est son message qui reste au dossier et à l'historique.
        """
        import services.rag as rag_module
        import inspect

        source = inspect.getsource(rag_module._rechercher_sync)
        assert "vers_francais" in source, "la réécriture doit se faire dans la recherche"

    def test_un_terme_garde_en_francais_nest_pas_reecrit(self):
        # Certains termes du glossaire sont identiques dans les deux langues
        # (« original », « plan »…) : les réécrire ne ferait rien, les inclure
        # ne ferait qu'alourdir la table.
        identiques = [t for t in TERMES if t.statut == VALIDE
                      and t.pulaar.lower() == t.francais.lower()]
        for terme in identiques:
            assert vers_francais(terme.pulaar) == terme.pulaar
