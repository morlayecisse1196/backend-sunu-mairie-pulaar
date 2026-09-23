"""
Édition d'une démarche (plan maître, étape 4.1).

Une démarche est le script d'une conversation avec quelqu'un qui ne sait pas
lire. Une modification fautive ne fait pas planter le serveur : elle DÉRAILLE
un dialogue, en silence, devant un citoyen qui n'a aucun moyen de comprendre
ce qui se passe ni de le signaler.

Ce qui est verrouillé ici : chaque façon connue de casser un dialogue est
refusée AVANT l'écriture, sur la démarche telle qu'elle SERAIT.
"""
from __future__ import annotations

import pytest

from services import demarche, editeur

CHAMPS = [
    {"type_demarche": "d", "nom_champ": "nom_enfant", "ordre": 10, "type_valeur": "texte",
     "question": "Quel est le nom ?", "obligatoire": True, "condition": None,
     "relances": ["Le nom ?"], "pulaar_valide": True, "question_pulaar": "Innde?"},
    {"type_demarche": "d", "nom_champ": "age_enfant", "ordre": 20, "type_valeur": "age",
     "question": "Quel âge ?", "obligatoire": True, "condition": None,
     "relances": ["L'âge ?"], "pulaar_valide": False},
    {"type_demarche": "d", "nom_champ": "parents_maries", "ordre": 30, "type_valeur": "booleen",
     "question": "Les parents sont-ils mariés ?", "obligatoire": True, "condition": None,
     "relances": ["Mariés ?"], "pulaar_valide": False},
    # Cité par RIEN : ni condition, ni gabarit, ni champ_age. C'est le seul
    # champ de ce jeu d'essai qu'on puisse renommer ou supprimer librement.
    {"type_demarche": "d", "nom_champ": "commune_naissance", "ordre": 35, "type_valeur": "texte",
     "question": "Dans quelle commune ?", "obligatoire": True, "condition": None,
     "relances": ["La commune ?"], "pulaar_valide": False},
]
DOCUMENTS = [
    {"type_demarche": "d", "type_document": "livret_famille", "ordre": 40,
     "message_demande": "Une photo du livret.", "apres_champ": "parents_maries",
     "condition": "parents_maries = oui", "obligatoire": True,
     "messages_rappel": ["Toujours pas reçue."], "pulaar_valide": False},
]
CAS = [
    {"type_demarche": "d", "code": "dans_les_delais", "ordre": 10,
     "condition": "age_jours(age_enfant) <= 30", "libelle": "Dans les délais"},
    {"type_demarche": "d", "code": "tardif", "ordre": 20, "condition": None, "libelle": "Tardif"},
]
GABARITS = [
    {"type_demarche": "d", "cle": "recapitulatif", "francais": "{nom_enfant}, exact ?",
     "pulaar": "{nom_enfant}, goonga?", "pulaar_valide": True, "contexte": "RG7"},
]
DEFINITION = {"libelle": "Extrait de naissance", "champ_age": "age_enfant", "traitable": True,
              "mots_cles": ["extrait de naissance"]}


def _verifier(**remplacements):
    base = {
        "definition": DEFINITION, "champs": CHAMPS, "documents": DOCUMENTS,
        "cas": CAS, "regles": [], "lignes_gabarits": GABARITS,
    }
    base.update(remplacements)
    return editeur._verifier(
        base["definition"], base["champs"], base["documents"],
        base["cas"], base["regles"], base["lignes_gabarits"],
    )


def _bloquants(problemes):
    return [p for p in problemes if p.gravite == editeur.BLOQUANT]


def _messages(problemes):
    return " | ".join(p.message for p in problemes)


class TestDemarcheSaine:
    def test_une_demarche_correcte_ne_bloque_rien(self):
        assert _bloquants(_verifier()) == []


class TestConditions:
    def test_une_condition_illisible_est_refusee(self):
        casse = [{**DOCUMENTS[0], "condition": "parents_maries = = oui"}]
        assert _bloquants(_verifier(documents=casse))

    def test_une_condition_qui_cite_un_champ_inexistant_est_refusee(self):
        # Le piège : `evaluer()` ne lève JAMAIS. Un champ inexistant rend
        # INCONNU, la condition ne se déclenche jamais, et rien ne le signale —
        # la pièce ne serait tout simplement plus demandée à personne.
        casse = [{**DOCUMENTS[0], "condition": "parents_marie = oui"}]
        problemes = _bloquants(_verifier(documents=casse))
        assert problemes and "parents_marie" in _messages(problemes)

    def test_la_condition_d_un_cas_est_verifiee_aussi(self):
        casse = [{**CAS[0], "condition": "age_jours(age_inexistant) <= 30"}, CAS[1]]
        assert _bloquants(_verifier(cas=casse))


class TestChamps:
    def test_un_champ_sans_question_est_refuse(self):
        # L'agent resterait muet en arrivant dessus.
        casse = [{**CHAMPS[0], "question": "  "}, *CHAMPS[1:]]
        assert _bloquants(_verifier(champs=casse))

    def test_deux_champs_de_meme_nom_sont_refuses(self):
        casse = [*CHAMPS, {**CHAMPS[0], "ordre": 99}]
        problemes = _bloquants(_verifier(champs=casse))
        assert problemes and "nom_enfant" in _messages(problemes)

    def test_un_nom_incitable_dans_une_condition_est_refuse(self):
        casse = [{**CHAMPS[0], "nom_champ": "nom-enfant"}, *CHAMPS[1:]]
        assert _bloquants(_verifier(champs=casse))

    def test_un_type_de_valeur_inconnu_est_refuse(self):
        casse = [{**CHAMPS[0], "type_valeur": "couleur"}, *CHAMPS[1:]]
        assert _bloquants(_verifier(champs=casse))

    def test_deux_champs_au_meme_rang_sont_signales_sans_bloquer(self):
        ambigus = [CHAMPS[0], {**CHAMPS[1], "ordre": 10}, CHAMPS[2]]
        problemes = _verifier(champs=ambigus)
        assert _bloquants(problemes) == []
        assert any(p.gravite == editeur.AVERTISSEMENT for p in problemes)


class TestCasLegaux:
    def test_sans_cas_par_defaut_l_edition_est_refusee(self):
        # `determiner_cas` s'arrête au premier cas certainement vrai. Sans
        # repli, un dossier qui ne remplit aucune condition n'a PAS de cas
        # légal — et les pièces à fournir en dépendent.
        sans_defaut = [CAS[0], {**CAS[1], "condition": "age_jours(age_enfant) <= 365"}]
        problemes = _bloquants(_verifier(cas=sans_defaut))
        assert problemes and "défaut" in _messages(problemes)

    def test_aucun_cas_du_tout_est_refuse(self):
        assert _bloquants(_verifier(cas=[]))

    def test_un_cas_place_apres_le_defaut_est_signale(self):
        inatteignable = [
            {**CAS[1], "ordre": 10},
            {**CAS[0], "ordre": 20},
        ]
        problemes = _verifier(cas=inatteignable)
        assert any("jamais atteint" in p.message for p in problemes)

    def test_deux_cas_de_meme_code_sont_refuses(self):
        assert _bloquants(_verifier(cas=[*CAS, CAS[0]]))


class TestRecapitulatif:
    def test_un_trou_qui_ne_correspond_a_aucun_champ_est_refuse(self):
        # La phrase ne pourrait pas être dite DU TOUT, au moment précis où le
        # citoyen doit confirmer ce qui ira sur un acte d'état civil.
        casse = [{**GABARITS[0], "francais": "{nom_enfnat}, exact ?"}]
        problemes = _bloquants(_verifier(lignes_gabarits=casse))
        assert problemes and "nom_enfnat" in _messages(problemes)

    def test_le_gabarit_pulaar_est_verifie_aussi(self):
        casse = [{**GABARITS[0], "pulaar": "{champ_fantome}, goonga?"}]
        assert _bloquants(_verifier(lignes_gabarits=casse))


class TestDocuments:
    def test_une_piece_demandee_apres_un_champ_inexistant_est_refusee(self):
        # Elle ne serait jamais réclamée, sans erreur visible.
        casse = [{**DOCUMENTS[0], "apres_champ": "champ_disparu"}]
        assert _bloquants(_verifier(documents=casse))

    def test_une_piece_sans_message_est_refusee(self):
        casse = [{**DOCUMENTS[0], "message_demande": ""}]
        assert _bloquants(_verifier(documents=casse))


class TestDefinition:
    def test_un_champ_d_age_inexistant_est_refuse(self):
        assert _bloquants(_verifier(definition={**DEFINITION, "champ_age": "fantome"}))

    def test_une_demarche_traitable_sans_mots_cles_est_refusee(self):
        # Le dialogue ne saurait jamais la reconnaître quand on la demande.
        assert _bloquants(_verifier(definition={**DEFINITION, "mots_cles": []}))


# ============================================================================
# Écriture
# ============================================================================


class _Table:
    def __init__(self, journal, nom):
        self.journal, self.nom, self._op, self._donnees, self._filtres = journal, nom, None, None, []

    def insert(self, donnees):
        self._op, self._donnees = "insert", donnees
        return self

    def update(self, donnees):
        self._op, self._donnees = "update", donnees
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, colonne, valeur):
        self._filtres.append((colonne, valeur))
        return self

    def execute(self):
        self.journal.append((self.nom, self._op, self._donnees, self._filtres))
        return type("R", (), {"data": []})()


@pytest.fixture
def base(monkeypatch):
    journal: list = []
    tables = {
        "demarche_champs": CHAMPS, "demarche_documents": DOCUMENTS,
        "demarche_cas": CAS, "demarche_gabarits": GABARITS, "demarche_regles": [],
        "demarche_definitions": [{"type_demarche": "d", "libelle": "Démarche", "version": 1,
                                  "traitable": True, "champ_age": "age_enfant",
                                  "mots_cles": ["extrait de naissance"]}],
    }

    def lire(nom, **filtres):
        lignes = tables.get(nom, [])
        for colonne, valeur in filtres.items():
            lignes = [l for l in lignes if l.get(colonne) == valeur]
        return lignes

    monkeypatch.setattr(demarche, "_table", lire)
    monkeypatch.setattr(editeur, "get_supabase_client",
                        lambda: type("C", (), {"table": lambda _s, nom: _Table(journal, nom)})())
    demarche.vider_cache()
    return journal


class TestEcriture:
    def test_une_modification_saine_passe(self, base):
        editeur.enregistrer("champ", "age_enfant", {"question": "Quel âge exactement ?"},
                            type_demarche="d")
        assert base, "l'écriture a bien eu lieu"

    def test_une_modification_qui_casse_une_condition_n_ecrit_rien(self, base):
        # Renommer `parents_maries` laisserait la condition du livret de
        # famille parler d'un champ qui n'existe plus.
        with pytest.raises(editeur.EditionRefusee):
            editeur.enregistrer("champ", "parents_maries", {"nom_champ": "maries"},
                                type_demarche="d")
        assert base == [], "aucune écriture, même partielle"

    def test_supprimer_un_champ_cite_par_le_recapitulatif_est_refuse(self, base):
        with pytest.raises(editeur.EditionRefusee) as refus:
            editeur.supprimer("champ", "nom_enfant", type_demarche="d")
        assert "nom_enfant" in str(refus.value)
        assert base == []

    def test_supprimer_un_champ_cite_par_une_condition_est_refuse(self, base):
        with pytest.raises(editeur.EditionRefusee):
            editeur.supprimer("champ", "parents_maries", type_demarche="d")
        assert base == []

    def test_supprimer_le_cas_par_defaut_est_refuse(self, base):
        with pytest.raises(editeur.EditionRefusee):
            editeur.supprimer("cas", "tardif", type_demarche="d")
        assert base == []

    def test_un_champ_supprimable_est_bien_supprime(self, base):
        editeur.supprimer("document", "livret_famille", type_demarche="d")
        assert base[0][1] == "delete"

    def test_les_avertissements_remontent_sans_empecher(self, base):
        restants = editeur.enregistrer("champ", "age_enfant", {"relances": []}, type_demarche="d")
        assert any(p.gravite == editeur.AVERTISSEMENT for p in restants)
        assert base, "l'écriture a quand même eu lieu"


class TestFrancaisEtPulaar:
    def test_changer_le_francais_retire_la_relecture_pulaar(self, base):
        # Le relecteur avait approuvé une traduction de l'ANCIEN texte ; elle
        # ne traduit plus rien.
        editeur.enregistrer("champ", "nom_enfant", {"question": "Quel est son nom complet ?"},
                            type_demarche="d")
        _table, _op, donnees, _filtres = base[0]
        assert donnees["pulaar_valide"] is False

    def test_modifier_autre_chose_ne_touche_pas_a_la_relecture(self, base):
        editeur.enregistrer("champ", "nom_enfant", {"obligatoire": False}, type_demarche="d")
        _t, _o, donnees, _f = base[0]
        assert "pulaar_valide" not in donnees

    def test_reecrire_le_meme_francais_ne_retire_rien(self, base):
        editeur.enregistrer("champ", "nom_enfant", {"question": "Quel est le nom ?"},
                            type_demarche="d")
        _t, _o, donnees, _f = base[0]
        assert "pulaar_valide" not in donnees


class TestSequence:
    def test_la_sequence_mele_champs_et_pieces_dans_l_ordre_reel(self, base):
        # Le citoyen ne rencontre pas deux tables : il rencontre une suite.
        etapes = editeur.sequence("d")
        assert [e["cle"] for e in etapes] == [
            "nom_enfant", "age_enfant", "parents_maries", "commune_naissance", "livret_famille"]
        assert etapes[-1]["genre"] == "document"

    def test_reordonner_espace_les_rangs_de_dix(self, base):
        editeur.reordonner("champ",
                           ["age_enfant", "nom_enfant", "parents_maries", "commune_naissance"],
                           type_demarche="d")
        rangs = [(f[1][1], d["ordre"]) for _t, _o, d, f in base]
        assert rangs == [("age_enfant", 10), ("nom_enfant", 20),
                         ("parents_maries", 30), ("commune_naissance", 40)]

    def test_reordonner_une_liste_partielle_est_refuse(self, base):
        # Les absents resteraient à leur ancien rang, donc à une place
        # arbitraire dans la nouvelle séquence.
        with pytest.raises(ValueError, match="absent"):
            editeur.reordonner("champ", ["age_enfant"], type_demarche="d")
        assert base == []

    def test_reordonner_avec_un_element_inconnu_est_refuse(self, base):
        with pytest.raises(ValueError, match="inconnu"):
            editeur.reordonner(
                "champ",
                ["age_enfant", "nom_enfant", "parents_maries", "commune_naissance", "fantome"],
                type_demarche="d")
        assert base == []


class TestRenommage:
    """
    Renommer était accepté, annoncé comme enregistré, et n'arrivait jamais en
    base : la clé d'identification écrasait le nouveau nom. Le pire des trois
    résultats possibles — pas une erreur, pas un refus, une illusion.
    """

    def test_un_renommage_sans_dependance_arrive_bien_en_base(self, base):
        editeur.enregistrer("champ", "commune_naissance", {"nom_champ": "commune"},
                            type_demarche="d")
        _table, _op, donnees, _filtres = base[0]
        assert donnees["nom_champ"] == "commune"

    def test_le_renommage_est_cherche_sous_l_ancien_nom(self, base):
        editeur.enregistrer("champ", "commune_naissance", {"nom_champ": "commune"},
                            type_demarche="d")
        _t, _o, _d, filtres = base[0]
        assert ("nom_champ", "commune_naissance") in filtres

    def test_un_renommage_qui_casse_le_recapitulatif_est_refuse(self, base):
        # `{nom_enfant}` du récapitulatif ne correspondrait plus à rien.
        with pytest.raises(editeur.EditionRefusee) as refus:
            editeur.enregistrer("champ", "nom_enfant", {"nom_champ": "bebe"}, type_demarche="d")
        assert "nom_enfant" in str(refus.value)
        assert base == []
