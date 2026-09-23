"""
Déclaration de décès (plan maître, étapes 5.3 et 5.4, migration 028).

Comme pour le mariage, ces tests LISENT la migration et déroulent le vrai
moteur dessus.

Ce qui est verrouillé ici :

  * AUCUNE cause de décès n'est demandée, nulle part — c'est une donnée de
    santé, confidentielle et anonyme, qui n'a rien à faire dans un dossier
    d'état civil ;
  * l'exigence du procès-verbal de police vient de la case cochée par le
    médecin, jamais d'une question au citoyen sur les circonstances ;
  * sans certificat médical, deux témoins majeurs sont exigés ;
  * au-delà d'un an, la démarche s'arrête et oriente vers le tribunal ;
  * une date de décès antérieure à la naissance est refusée.
"""
from __future__ import annotations

import pathlib
import re
from datetime import date, timedelta

import pytest

from services import demarche, editeur, simulateur

SQL = (pathlib.Path(__file__).parents[2] / "migrations" / "028_declaration_deces.sql").read_text(encoding="utf-8")
T = "declaration_deces"

_TEXTE = r"(?:null|'(?:[^']|'')*')"
_SUITE = r"(?:'(?:[^']|'')*'\s*)+"


def _texte(brut: str):
    return None if brut == "null" else brut[1:-1].replace("''", "'")


def _concatene(brut: str) -> str:
    return "".join(_texte(m) for m in re.findall(r"'(?:[^']|'')*'", brut))


def _tableau(brut: str) -> list[str]:
    return [_texte(m) for m in re.findall(r"'(?:[^']|'')*'", brut)]


CHAMPS = [
    {"type_demarche": T, "ordre": int(ordre), "nom_champ": nom, "type_valeur": type_valeur,
     "question": _texte(question), "regle_validation": _texte(regle),
     "obligatoire": obligatoire == "true", "condition": _texte(condition),
     "relances": _tableau(relances), "question_pulaar": None, "pulaar_valide": False,
     "relances_pulaar": [], "relances_pulaar_valide": []}
    for ordre, nom, type_valeur, question, regle, obligatoire, condition, relances in re.findall(
        rf"\('declaration_deces',\s*(\d+),\s*'(\w+)',\s*'(\w+)',\s*({_TEXTE}),\s*({_TEXTE}),\s*"
        rf"(true|false),\s*({_TEXTE}),\s*array\[((?:[^\]])*)\]", SQL)
]

DOCUMENTS = [
    {"type_demarche": T, "ordre": int(ordre), "type_document": nom, "obligatoire": obligatoire == "true",
     "condition": _texte(condition), "apres_champ": _texte(apres), "message_demande": _concatene(message),
     "messages_rappel": _tableau(rappels), "groupe": None, "message_demande_pulaar": None,
     "pulaar_valide": False, "messages_rappel_pulaar": [], "messages_rappel_pulaar_valide": []}
    for ordre, nom, obligatoire, condition, apres, message, rappels in re.findall(
        rf"\('declaration_deces',\s*(\d+),\s*'(\w+)',\s*(true|false),\s*({_TEXTE}),\s*({_TEXTE}),\s*"
        rf"({_SUITE}),\s*array\[((?:[^\]])*)\]", SQL)
]

REGLES = [
    {"type_demarche": T, "code": code, "ordre": int(ordre), "condition": _texte(condition), "effet": effet,
     "champ_concerne": _texte(champ), "message": _concatene(message), "source": _concatene(source),
     "hypothese": hypothese == "true"}
    for code, ordre, condition, effet, champ, message, source, hypothese in re.findall(
        rf"\('declaration_deces',\s*'(\w+)',\s*(\d+),\s*({_TEXTE}),\s*'(bloquer|interdire)',\s*({_TEXTE}),\s*"
        rf"({_SUITE}),\s*({_SUITE}),\s*(true|false)\)", SQL)
]

CAS = [
    {"type_demarche": T, "code": code, "ordre": int(ordre), "condition": _texte(condition),
     "libelle": _texte(libelle)}
    for code, ordre, condition, libelle in re.findall(
        rf"\('declaration_deces',\s*'(\w+)',\s*(\d+),\s*({_TEXTE}),\s*({_TEXTE})\)", SQL)
]

_GAB = re.search(rf"values \('declaration_deces', 'recapitulatif',\s*({_SUITE}),", SQL)
GABARIT = {"type_demarche": T, "cle": "recapitulatif", "pulaar": None, "pulaar_valide": False,
           "francais": _concatene(_GAB.group(1))}

_DEF = re.search(
    rf"values \('declaration_deces', ('(?:[^']|'')*'),\s*array\[([^\]]*)\],\s*(true|false), ({_TEXTE})\)", SQL)
DEFINITION = {
    "type_demarche": T, "libelle": _texte(_DEF.group(1)), "mots_cles": _tableau(_DEF.group(2)),
    "traitable": _DEF.group(3) == "true", "champ_age": _texte(_DEF.group(4)), "version": 1,
}

TABLES = {
    "demarche_definitions": [DEFINITION], "demarche_champs": CHAMPS, "demarche_documents": DOCUMENTS,
    "demarche_regles": REGLES, "demarche_gabarits": [GABARIT], "demarche_cas": CAS,
}

AUJOURDHUI = date(2026, 9, 22)


@pytest.fixture(autouse=True)
def base(monkeypatch):
    def lire(nom, **filtres):
        return [l for l in TABLES.get(nom, []) if all(l.get(c) == v for c, v in filtres.items())]
    monkeypatch.setattr(demarche, "_table", lire)
    demarche.vider_cache()


def _scenario(**retouches):
    reponses = {c["nom_champ"]: "Ibrahima Diallo" for c in CHAMPS if c["type_valeur"] == "texte"}
    reponses.update({
        "sexe_defunt": "masculin", "situation_matrimoniale_defunt": "marie",
        "date_naissance_defunt": "1950-04-12",
        "date_deces": (AUJOURDHUI - timedelta(days=1)).isoformat(),
        "lieu_deces": "structure_sanitaire", "certificat_medical_existe": "oui",
        "obstacle_medico_legal": "non",
    })
    reponses.update({d["type_document"]: True for d in DOCUMENTS})
    reponses.update(retouches)
    return reponses


def _jouer(**retouches):
    return simulateur.jouer(_scenario(**retouches), T, aujourdhui=AUJOURDHUI)


def _questions(rapport):
    return [t.cle for t in rapport.tours if t.genre == simulateur.QUESTION]


def _pieces(rapport):
    return [t.cle for t in rapport.tours if t.genre == simulateur.PIECE]


class TestAucuneDonneeDeSante:
    """
    Étape 5.4. La cause du décès figure sur un document que le formulaire
    lui-même déclare incommunicable et destiné à la destruction.
    """

    @pytest.mark.parametrize("interdit", ["cause", "maladie", "autopsie", "symptome", "diagnostic"])
    def test_aucun_champ_ne_porte_sur_la_sante(self, interdit):
        for champ in CHAMPS:
            assert interdit not in champ["nom_champ"].lower()

    @pytest.mark.parametrize("interdit", ["de quoi", "cause du décès", "de quelle maladie", "autopsie"])
    def test_aucune_question_ne_demande_la_cause(self, interdit):
        for champ in CHAMPS:
            assert interdit not in champ["question"].lower()
            for relance in champ["relances"]:
                assert interdit not in relance.lower()

    def test_le_recapitulatif_ne_relit_aucune_cause(self):
        recap = next(t for t in _jouer().tours if t.genre == simulateur.RECAPITULATIF).dit
        for interdit in ("cause", "maladie", "autopsie"):
            assert interdit not in recap.lower()

    def test_la_consigne_de_photo_dit_de_ne_pas_envoyer_la_partie_basse(self):
        certificat = next(d for d in DOCUMENTS if d["type_document"] == "certificat_deces")
        message = certificat["message_demande"].lower()
        assert "partie du haut" in message
        assert "confidentielle" in message
        assert any("partie du haut" in r.lower() or "partie haute" in r.lower()
                   for r in certificat["messages_rappel"])


class TestParcours:
    def test_un_deces_recent_avec_certificat_va_jusqu_au_bout(self):
        rapport = _jouer()
        assert rapport.termine, rapport.arret
        assert rapport.cas == "dans_les_delais"

    def test_une_declaration_de_deux_mois_reste_recevable(self):
        rapport = _jouer(date_deces=(AUJOURDHUI - timedelta(days=60)).isoformat())
        assert rapport.termine and rapport.cas == "tardive"

    def test_le_recapitulatif_relit_le_defunt_et_le_declarant(self):
        recap = next(t for t in _jouer().tours if t.genre == simulateur.RECAPITULATIF).dit
        assert "survenu le" in recap and "La déclaration est faite par" in recap

    def test_le_scenario_type_de_l_editeur_passe(self):
        scenario = simulateur.scenario_type(T, aujourdhui=AUJOURDHUI)
        assert simulateur.jouer(scenario, T, aujourdhui=AUJOURDHUI).termine


class TestTemoinsEtCertificat:
    def test_avec_certificat_aucun_temoin_n_est_demande(self):
        rapport = _jouer()
        assert "nom_temoin_1" not in _questions(rapport)
        assert "certificat_deces" in _pieces(rapport)

    def test_sans_certificat_deux_temoins_sont_exiges(self):
        rapport = _jouer(certificat_medical_existe="non")
        for attendu in ("nom_temoin_1", "piece_temoin_1", "nom_temoin_2", "piece_temoin_2"):
            assert attendu in _questions(rapport)
        assert "cni_temoin_1" in _pieces(rapport) and "cni_temoin_2" in _pieces(rapport)

    def test_sans_certificat_le_certificat_n_est_pas_reclame(self):
        assert "certificat_deces" not in _pieces(_jouer(certificat_medical_existe="non"))

    def test_l_obstacle_medico_legal_n_est_demande_qu_avec_un_certificat(self):
        # C'est une case du formulaire du médecin : sans formulaire, pas de case.
        assert "obstacle_medico_legal" not in _questions(_jouer(certificat_medical_existe="non"))


class TestProcesVerbalDePolice:
    def test_exige_quand_le_medecin_a_signale_un_obstacle(self):
        rapport = _jouer(obstacle_medico_legal="oui")
        assert "pv_police" in _pieces(rapport)

    def test_pas_exige_sinon(self):
        assert "pv_police" not in _pieces(_jouer())

    def test_la_mort_violente_ne_se_demande_pas_au_citoyen(self):
        # La question porte sur une case cochée par le médecin, pas sur les
        # circonstances de la mort : on n'interroge pas un endeuillé là-dessus,
        # et sa réponse ne serait pas une donnée médicale fiable.
        champ = next(c for c in CHAMPS if c["nom_champ"] == "obstacle_medico_legal")
        assert "médico-légal" in champ["question"]
        assert "violente" not in champ["question"].lower()


class TestDelais:
    def test_au_dela_d_un_an_la_demarche_s_arrete(self):
        rapport = _jouer(date_deces=(AUJOURDHUI - timedelta(days=400)).isoformat())
        assert not rapport.termine
        blocage = next(t for t in rapport.tours if t.genre == simulateur.BLOCAGE)
        assert "tribunal" in blocage.dit.lower()

    def test_juste_avant_un_an_elle_continue(self):
        assert _jouer(date_deces=(AUJOURDHUI - timedelta(days=300)).isoformat()).termine

    def test_un_deces_anterieur_a_la_naissance_est_refuse(self):
        rapport = _jouer(date_naissance_defunt="2000-01-01", date_deces="1990-01-01")
        assert not rapport.termine
        assert "date_deces" in (rapport.arret or "")


class TestSanteDeLaDemarche:
    def test_aucun_probleme_bloquant(self):
        problemes = editeur._verifier(DEFINITION, CHAMPS, DOCUMENTS, CAS, REGLES, [GABARIT])
        assert [p.en_dict() for p in problemes if p.gravite == editeur.BLOQUANT] == []

    def test_la_regle_du_delai_reste_une_hypothese(self):
        assert all(r["hypothese"] for r in REGLES)
        assert all(len(r["source"]) > 30 for r in REGLES)

    @pytest.mark.parametrize("nom", ["Déclaration de décès", "acte de décès", "extrait de deces"])
    def test_le_dialogue_la_reconnait_a_son_nom(self, nom):
        trouvee = demarche.reconnaitre_demarche(nom)
        assert trouvee is not None and trouvee.type_demarche == T
