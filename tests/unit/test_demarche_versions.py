"""
Une démarche modifiée ne change pas sous les pieds du citoyen (étape 2.4).

À partir de l'étape 4, un agent modifiera une démarche depuis le web, en
pleine journée, pendant que des citoyens y répondent. Sans version figée, la
modification prendrait effet au tour suivant, pour tout le monde :

  * une question ajoutée ressurgit APRÈS le récapitulatif que le citoyen vient
    de confirmer ;
  * une question retirée laisse une valeur orpheline dans le dossier ;
  * un seuil de cas légal modifié reclasse un dossier déjà constitué.

Une session retient donc le numéro de version sous lequel elle a commencé.
"""
from __future__ import annotations

import pytest

import slot_controller
from services import demarche

DEFINITION = {
    "type_demarche": "extrait_naissance", "libelle": "Extrait de naissance", "traitable": True,
    "actif": True, "champ_age": "age_enfant", "version": 2, "mots_cles": ["extrait de naissance"],
}

# La version 1 : deux questions. La version vivante (2) : une de plus, et un
# seuil de cas légal différent.
CHAMPS_V1 = [
    {"type_demarche": "extrait_naissance", "nom_champ": "nom_enfant", "type_valeur": "texte",
     "ordre": 10, "obligatoire": True, "question": "Le nom de l'enfant ?"},
    {"type_demarche": "extrait_naissance", "nom_champ": "age_enfant", "type_valeur": "age",
     "ordre": 20, "obligatoire": True, "question": "Quel âge ?"},
]
CHAMPS_VIVANTS = CHAMPS_V1 + [
    {"type_demarche": "extrait_naissance", "nom_champ": "profession_pere", "type_valeur": "texte",
     "ordre": 15, "obligatoire": True, "question": "La profession du père ?"},
]

CAS_V1 = [{"type_demarche": "extrait_naissance", "code": "dans_les_delais", "ordre": 10,
           "condition": "age_jours(age_enfant) <= 30", "libelle": "Dans les délais"},
          {"type_demarche": "extrait_naissance", "code": "tardif", "ordre": 20,
           "condition": None, "libelle": "Tardif"}]
CAS_VIVANTS = [{"type_demarche": "extrait_naissance", "code": "dans_les_delais", "ordre": 10,
                "condition": "age_jours(age_enfant) <= 45", "libelle": "Dans les délais"},
               {"type_demarche": "extrait_naissance", "code": "tardif", "ordre": 20,
                "condition": None, "libelle": "Tardif"}]

VERSION_1 = {
    "type_demarche": "extrait_naissance", "version": 1, "publiee_par": "migration_019",
    "contenu": {
        "definition": {"libelle": "Extrait de naissance", "mots_cles": ["extrait de naissance"],
                       "traitable": True, "champ_age": "age_enfant"},
        "champs": CHAMPS_V1, "documents": [], "regles": [], "cas": CAS_V1,
    },
}


@pytest.fixture
def base(monkeypatch):
    tables = {
        "demarche_definitions": [DEFINITION],
        "demarche_champs": CHAMPS_VIVANTS,
        "demarche_documents": [],
        "demarche_regles": [],
        "demarche_cas": CAS_VIVANTS,
        "demarche_versions": [VERSION_1],
        "demarche_gabarits": [],
    }

    def lire(nom, **filtres):
        lignes = tables.get(nom, [])
        for colonne, valeur in filtres.items():
            lignes = [l for l in lignes if l.get(colonne) == valeur]
        return lignes

    monkeypatch.setattr(demarche, "_table", lire)
    monkeypatch.setattr(demarche, "lire_strictement", lire)
    demarche.vider_cache()
    return tables


class TestInstantane:
    def test_la_version_publiee_ignore_les_modifications_en_cours(self, base):
        fige = demarche.instantane(version=1)
        assert fige.fige is True
        assert [c["nom_champ"] for c in fige.champs] == ["nom_enfant", "age_enfant"]

    def test_la_version_vivante_montre_les_modifications(self, base):
        vivant = demarche.instantane()
        assert vivant.fige is False
        assert "profession_pere" in [c["nom_champ"] for c in vivant.champs]

    def test_une_version_introuvable_retombe_sur_le_vivant_sans_couper_le_dialogue(self, base):
        # Compromis assumé : des questions légèrement différentes valent mieux
        # qu'un citoyen coupé au milieu de sa démarche.
        secours = demarche.instantane(version=99)
        assert secours.fige is False
        assert secours.champs


class TestCeQueLaVersionProtege:
    def test_une_question_ajoutee_ne_ressurgit_pas_dans_un_dialogue_en_cours(self, base):
        # Le citoyen a répondu aux deux questions de la version 1. Sous la
        # version vivante, `profession_pere` serait redemandée — après le
        # récapitulatif qu'il vient de confirmer.
        slots = {"nom_enfant": "Ibrahima", "age_enfant": {"valeur": 7, "unite": "jours"}}

        etape_figee = slot_controller.determiner_etape_courante(
            slots, set(), demarche.champs(version=1), demarche.documents(version=1)
        )
        assert etape_figee is None, "la version 1 est complète"

        etape_vivante = slot_controller.determiner_etape_courante(
            slots, set(), demarche.champs(), demarche.documents()
        )
        assert etape_vivante["definition"]["nom_champ"] == "profession_pere"

    def test_un_seuil_modifie_ne_reclasse_pas_un_dossier_en_cours(self, base):
        slots = {"age_enfant": {"valeur": 40, "unite": "jours"}}
        assert demarche.determiner_cas(slots, version=1) == "tardif"
        assert demarche.determiner_cas(slots) == "dans_les_delais", "le seuil vivant est à 45 jours"

    def test_les_slots_initiaux_suivent_la_version(self, base):
        assert set(demarche.slots_vides(version=1)) == {"nom_enfant", "age_enfant"}
        assert "profession_pere" in demarche.slots_vides()


class TestLeDialogueUtiliseSaVersion:
    """Le maillon qui compte : le tour de collecte lit la version de la session."""

    def test_le_tour_de_collecte_lit_les_champs_de_la_version_figee(self, base, monkeypatch):
        import asyncio

        demandes: list[str] = []

        async def faux_llm(_headers, _payload, retries=2):
            # Le prompt cite la question du champ courant : c'est par là qu'on
            # voit quelle version le tour a réellement chargée.
            demandes.append(_payload["messages"][1]["content"])
            return {"reponse_valide": False, "valeur": None, "reponse": "Pardon ?"}

        monkeypatch.setattr(slot_controller, "_call_openrouter_structured_isole", faux_llm)
        monkeypatch.setattr(slot_controller, "list_documents", lambda _id: [])

        # `profession_pere` (ordre 15) passe AVANT `age_enfant` : sous la
        # version vivante, c'est elle qui serait demandée.
        etat = {
            "slots": {"nom_enfant": "Ibrahima"},
            "type_demarche": "extrait_naissance",
            "dossier_id": None,
            "demarche_version": 1,
        }
        asyncio.run(slot_controller.traiter_tour_administratif(etat, "peu importe", {}))
        assert "Quel âge ?" in demandes[-1]
        assert "profession du père" not in demandes[-1]

        etat["demarche_version"] = None  # session d'avant le versionnement
        asyncio.run(slot_controller.traiter_tour_administratif(etat, "peu importe", {}))
        assert "profession du père" in demandes[-1]


class TestSessionPersistee:
    def test_une_session_reprise_retrouve_les_champs_de_sa_version(self, base):
        from temps_reel import etat as etat_module

        ligne = {
            "id": "s1", "cle_client": "c1", "citoyen_id": "u1", "type_demarche": "extrait_naissance",
            "etat": {"demarche_version": 1, "slots": {"nom_enfant": "Ibrahima"}},
        }
        repris = etat_module.deserialiser(ligne)

        assert repris["demarche_version"] == 1
        assert set(repris["slots"]) == {"nom_enfant", "age_enfant"}
        assert "profession_pere" not in repris["slots"], "question ajoutée après le début du dialogue"

    def test_une_session_d_avant_le_versionnement_repart_du_vivant(self, base):
        from temps_reel import etat as etat_module

        ligne = {
            "id": "s0", "cle_client": "c0", "citoyen_id": "u0", "type_demarche": "extrait_naissance",
            "etat": {"slots": {"nom_enfant": "Awa"}},  # aucune version : enregistrée avant l'étape 2.4
        }
        repris = etat_module.deserialiser(ligne)

        assert repris["demarche_version"] is None
        assert "profession_pere" in repris["slots"]


class TestPublication:
    def test_publier_fige_le_vivant_et_incremente(self, base, monkeypatch):
        ecrits = {}

        class _Table:
            def __init__(self, nom):
                self.nom = nom

            def insert(self, donnees):
                ecrits["insert"] = (self.nom, donnees)
                return self

            def update(self, donnees):
                ecrits["update"] = (self.nom, donnees)
                return self

            def eq(self, *_a):
                return self

            def execute(self):
                return None

        monkeypatch.setattr(demarche, "get_supabase_client", lambda: type("C", (), {"table": staticmethod(_Table)})())

        assert demarche.publier(par="agent@mairie.sn") == 3

        table, donnees = ecrits["insert"]
        assert table == "demarche_versions"
        assert donnees["version"] == 3
        assert donnees["publiee_par"] == "agent@mairie.sn"
        # L'instantané publié contient bien la démarche ENTIÈRE.
        assert set(donnees["contenu"]) == {"definition", "champs", "documents", "regles", "cas", "gabarits"}
        assert "profession_pere" in [c["nom_champ"] for c in donnees["contenu"]["champs"]]
        assert ecrits["update"] == ("demarche_definitions", {"version": 3})

    def test_une_lecture_ratee_ne_publie_pas_une_demarche_vide(self, base, monkeypatch):
        # Avec la lecture tolérante du dialogue, une panne réseau rendait
        # « aucun champ », et la publication figeait une démarche vide : tous
        # les dialogues suivants démarraient sans une seule question.
        ecrits = []

        def en_panne(nom, **_f):
            if nom == "demarche_champs":
                raise demarche.LectureImpossible("demarche_champs : réseau")
            return base.get(nom, [])

        monkeypatch.setattr(demarche, "lire_strictement", en_panne)
        monkeypatch.setattr(demarche, "get_supabase_client", lambda: ecrits.append("ecriture"))
        with pytest.raises(demarche.LectureImpossible):
            demarche.publier(par="agent@mairie.sn")
        assert ecrits == []

    def test_une_demarche_sans_champ_ne_se_publie_pas(self, base, monkeypatch):
        base["demarche_champs"] = []
        monkeypatch.setattr(demarche, "get_supabase_client", lambda: pytest.fail("écriture"))
        with pytest.raises(demarche.LectureImpossible):
            demarche.publier()


class TestGabaritsFiges:
    """
    Le récapitulatif n'était pas figé : le modifier touchait tout de suite les
    dialogues en cours, qui le remplissaient avec les champs de LEUR version.
    """

    GABARIT_V3 = {"type_demarche": "extrait_naissance", "cle": "recapitulatif",
                  "francais": "Enfant : {nom_enfant}.", "pulaar": None, "pulaar_valide": False}
    GABARIT_BROUILLON = {**GABARIT_V3, "francais": "Enfant : {nom_enfant}, père : {profession_pere}."}

    def test_la_version_publiee_garde_son_recapitulatif(self, base):
        base["demarche_versions"].append({
            **VERSION_1, "version": 3,
            "contenu": {**VERSION_1["contenu"], "gabarits": [self.GABARIT_V3]},
        })
        base["demarche_gabarits"] = [self.GABARIT_BROUILLON]
        rendu = demarche.rendre_gabarit("recapitulatif", {"nom_enfant": "Awa"}, version=3)
        assert rendu.francais == "Enfant : Awa."

    def test_une_version_d_avant_le_gel_retombe_sur_le_brouillon(self, base):
        # La v1 ne contient pas de gabarits : on ne sait pas ce qu'ils
        # disaient, le brouillon est le seul texte disponible.
        base["demarche_gabarits"] = [self.GABARIT_V3]
        assert demarche.instantane(version=1).gabarits is None
        rendu = demarche.rendre_gabarit("recapitulatif", {"nom_enfant": "Awa"}, version=1)
        assert rendu.francais == "Enfant : Awa."

    def test_la_publication_fige_les_gabarits(self, base, monkeypatch):
        base["demarche_gabarits"] = [self.GABARIT_BROUILLON]
        ecrits = {}

        class _Table:
            def __init__(self, nom):
                self.nom = nom

            def insert(self, donnees):
                ecrits[self.nom] = donnees
                return self

            def update(self, _d):
                return self

            def eq(self, *_a):
                return self

            def execute(self):
                return None

        monkeypatch.setattr(demarche, "get_supabase_client", lambda: type("C", (), {"table": staticmethod(_Table)})())
        demarche.publier()
        assert ecrits["demarche_versions"]["contenu"]["gabarits"] == [self.GABARIT_BROUILLON]


class TestLectureStricte:
    """La lecture qui sert à ÉCRIRE ne confond jamais panne et table vide."""

    def test_une_panne_leve(self, monkeypatch):
        def injoignable():
            raise OSError("getaddrinfo failed")
        monkeypatch.setattr(demarche, "get_supabase_client", injoignable)
        with pytest.raises(demarche.LectureImpossible, match="demarche_champs"):
            demarche.lire_strictement("demarche_champs", type_demarche="extrait_naissance")

    def test_la_lecture_du_dialogue_reste_tolerante(self, monkeypatch):
        # Le dialogue, lui, préfère un repli à un citoyen coupé.
        def injoignable():
            raise OSError("getaddrinfo failed")
        monkeypatch.setattr(demarche, "get_supabase_client", injoignable)
        assert demarche._table("demarche_champs") == []
