"""
Brouillon d'une démarche (plan maître, étape 4.4).

Ce qui est verrouillé ici :

  * l'écart entre le brouillon et la version publiée est exact — ni
    changement fantôme (colonne ajoutée par une migration postérieure, fichier
    audio régénéré), ni changement oublié (pulaar corrigé, ordre modifié) ;
  * abandonner remet VRAIMENT la démarche dans l'état publié, ajouts retirés
    compris ;
  * une lecture ratée n'est jamais prise pour « table vide » : sinon
    l'abandon supprimerait tout, et l'écart annoncerait tout comme retiré ;
  * on ne restaure pas une version qui viderait la démarche.
"""
from __future__ import annotations

import copy

import pytest

from services import brouillon, demarche

T = "extrait_naissance"

NOM = {"type_demarche": T, "nom_champ": "nom_enfant", "ordre": 10, "type_valeur": "texte",
       "question": "Le nom de l'enfant ?", "pulaar": "Innde ?", "pulaar_valide": True,
       "question_audio": "a.mp3", "id": "u1"}
AGE = {"type_demarche": T, "nom_champ": "age_enfant", "ordre": 20, "type_valeur": "age",
       "question": "Quel âge ?", "pulaar": None, "pulaar_valide": False, "id": "u2"}
CNI = {"type_demarche": T, "type_document": "cni_mere", "ordre": 30,
       "message_demande": "La CNI de la mère.", "id": "u3"}
RECAP = {"type_demarche": T, "cle": "recapitulatif", "francais": "Enfant : {nom_enfant}.",
         "pulaar": None, "pulaar_valide": False}
TARDIF = {"type_demarche": T, "code": "tardif", "ordre": 10, "condition": None, "libelle": "Tardif"}


def _version(numero, *, gabarits=True, champs=(NOM, AGE)):
    contenu = {"definition": {"libelle": "Extrait", "traitable": True, "champ_age": "age_enfant"},
               "champs": [copy.deepcopy(c) for c in champs], "documents": [copy.deepcopy(CNI)],
               "regles": [], "cas": [copy.deepcopy(TARDIF)]}
    if gabarits:
        contenu["gabarits"] = [copy.deepcopy(RECAP)]
    return {"type_demarche": T, "version": numero, "publiee_par": "test", "contenu": contenu}


class _Base:
    """Assez de PostgREST pour que les écritures de l'abandon s'appliquent vraiment."""

    def __init__(self, tables):
        self.tables = tables
        self.ecritures = []

    def table(self, nom):
        base = self

        class _Requete:
            def __init__(self):
                self.filtres, self.action = [], None

            def insert(self, ligne):
                self.action = ("insert", ligne)
                return self

            def update(self, valeurs):
                self.action = ("update", valeurs)
                return self

            def delete(self):
                self.action = ("delete", None)
                return self

            def eq(self, colonne, valeur):
                self.filtres.append((colonne, valeur))
                return self

            def execute(self):
                genre, donnees = self.action
                base.ecritures.append((genre, nom, dict(self.filtres)))
                lignes = base.tables.setdefault(nom, [])
                visees = [l for l in lignes if all(l.get(c) == v for c, v in self.filtres)]
                if genre == "insert":
                    lignes.append(dict(donnees))
                elif genre == "update":
                    for l in visees:
                        l.update(donnees)
                else:
                    base.tables[nom] = [l for l in lignes if l not in visees]

        return _Requete()


@pytest.fixture
def base(monkeypatch):
    tables = {
        "demarche_definitions": [{"type_demarche": T, "version": 4}],
        "demarche_versions": [_version(4)],
        "demarche_champs": [copy.deepcopy(NOM), copy.deepcopy(AGE)],
        "demarche_documents": [copy.deepcopy(CNI)],
        "demarche_regles": [],
        "demarche_cas": [copy.deepcopy(TARDIF)],
        "demarche_gabarits": [copy.deepcopy(RECAP)],
    }
    fausse = _Base(tables)

    def lire(nom, **filtres):
        return [copy.deepcopy(l) for l in tables.get(nom, [])
                if all(l.get(c) == v for c, v in filtres.items())]

    monkeypatch.setattr(demarche, "lire_strictement", lire)
    monkeypatch.setattr(brouillon, "get_supabase_client", lambda: fausse)
    demarche.vider_cache()
    return fausse


def _champ(base, nom):
    return next(l for l in base.tables["demarche_champs"] if l["nom_champ"] == nom)


class TestEcarts:
    def test_rien_n_a_change(self, base):
        etat = brouillon.etat(T)
        assert etat.version_publiee == 4
        assert etat.ecarts == []
        assert etat.a_publier is False

    def test_une_question_modifiee(self, base):
        _champ(base, "age_enfant")["question"] = "Quel âge a l'enfant ?"
        assert brouillon.etat(T).ecarts == [
            brouillon.Ecart("champ", "age_enfant", brouillon.MODIFIE, ("question",))]

    def test_un_pulaar_corrige_dans_l_atelier_est_un_ecart(self, base):
        # C'est ce que l'agent de l'atelier doit savoir : sa correction
        # n'est pas encore entendue au téléphone.
        _champ(base, "nom_enfant")["pulaar"] = "Innde cukalel ngel ?"
        assert brouillon.etat(T).ecarts[0].colonnes == ("pulaar",)

    def test_un_ordre_change_est_un_ecart(self, base):
        _champ(base, "age_enfant")["ordre"] = 5
        assert brouillon.etat(T).ecarts[0].colonnes == ("ordre",)

    def test_ajout_et_retrait(self, base):
        base.tables["demarche_champs"].append({**AGE, "nom_champ": "profession_pere", "id": "u9"})
        base.tables["demarche_documents"] = []
        natures = {(e.famille, e.cle, e.nature) for e in brouillon.etat(T).ecarts}
        assert natures == {("champ", "profession_pere", brouillon.AJOUTE),
                           ("document", "cni_mere", brouillon.RETIRE)}

    def test_un_gabarit_modifie_est_un_ecart(self, base):
        base.tables["demarche_gabarits"][0]["francais"] = "Enfant : {nom_enfant}, né le ?"
        assert brouillon.etat(T).ecarts[0].famille == "gabarit"

    def test_un_audio_regenere_n_est_pas_un_ecart(self, base):
        # Le fichier suit le texte ; le citoyen n'entend aucune différence.
        _champ(base, "nom_enfant")["question_audio"] = "b.mp3"
        _champ(base, "nom_enfant")["updated_at"] = "2026-09-21"
        assert brouillon.etat(T).ecarts == []

    def test_une_colonne_nee_apres_la_publication_n_est_pas_un_ecart(self, base):
        # La migration 024 a ajouté des drapeaux après la publication : les
        # comparer à « absent » signalerait un changement que personne n'a fait.
        _champ(base, "age_enfant")["relances_pulaar_valide"] = []
        assert brouillon.etat(T).ecarts == []

    def test_une_version_d_avant_le_gel_des_gabarits_est_a_republier(self, base):
        base.tables["demarche_versions"] = [_version(4, gabarits=False)]
        etat = brouillon.etat(T)
        assert etat.gabarits_non_figes is True
        assert etat.ecarts == []
        assert etat.a_publier is True

    def test_une_lecture_ratee_leve_au_lieu_de_tout_declarer_retire(self, base, monkeypatch):
        def en_panne(nom, **_f):
            raise demarche.LectureImpossible(nom)
        monkeypatch.setattr(demarche, "lire_strictement", en_panne)
        with pytest.raises(demarche.LectureImpossible):
            brouillon.etat(T)

    def test_le_cache_du_dialogue_n_est_pas_la_reference(self, base, monkeypatch):
        # Le cache de `demarche.instantane` peut contenir un repli sur le
        # vivant : comparer le brouillon à lui-même ne montrerait rien.
        _champ(base, "age_enfant")["question"] = "Modifiée"
        monkeypatch.setattr(demarche, "instantane",
                            lambda *_a, **_k: pytest.fail("cache du dialogue consulté"))
        assert len(brouillon.etat(T).ecarts) == 1


class TestAbandon:
    def test_remet_la_version_publiee(self, base):
        _champ(base, "age_enfant")["question"] = "Modifiée"
        base.tables["demarche_champs"].append({**AGE, "nom_champ": "profession_pere", "id": "u9"})
        base.tables["demarche_documents"] = []
        base.tables["demarche_gabarits"][0]["francais"] = "Autre"

        assert brouillon.abandonner(T, par="moussa@mairie.sn") == 4
        assert brouillon.etat(T).ecarts == []
        assert _champ(base, "age_enfant")["question"] == "Quel âge ?"
        assert [l["nom_champ"] for l in base.tables["demarche_champs"]] == ["nom_enfant", "age_enfant"]

    def test_n_ecrit_rien_quand_rien_n_a_change(self, base):
        assert brouillon.abandonner(T) == 0
        assert base.ecritures == []

    def test_les_suppressions_viennent_en_dernier(self, base):
        # Si la base tombe au milieu, on a perdu le moins possible.
        _champ(base, "age_enfant")["question"] = "Modifiée"
        base.tables["demarche_champs"].append({**AGE, "nom_champ": "profession_pere", "id": "u9"})
        base.tables["demarche_documents"] = []
        brouillon.abandonner(T)
        genres = [g for g, _t, _f in base.ecritures]
        premiere = genres.index("delete")
        assert premiere > 0 and set(genres[premiere:]) == {"delete"}

    def test_ne_reecrit_ni_l_identifiant_ni_l_audio(self, base):
        _champ(base, "nom_enfant")["question"] = "Modifiée"
        _champ(base, "nom_enfant")["question_audio"] = "b.mp3"
        brouillon.abandonner(T)
        assert _champ(base, "nom_enfant")["id"] == "u1"
        # Le déclencheur 022 efface l'audio si le pulaar change ; le
        # réécrire ici remettrait un fichier qui ne correspond peut-être plus.
        assert _champ(base, "nom_enfant")["question_audio"] == "b.mp3"

    def test_n_ecrit_pas_une_colonne_disparue_du_schema(self, base):
        base.tables["demarche_versions"][0]["contenu"]["champs"][1]["colonne_supprimee"] = "x"
        _champ(base, "age_enfant")["question"] = "Modifiée"
        brouillon.abandonner(T)
        assert "colonne_supprimee" not in _champ(base, "age_enfant")

    def test_laisse_les_gabarits_d_une_version_qui_ne_les_contenait_pas(self, base):
        base.tables["demarche_versions"] = [_version(4, gabarits=False)]
        base.tables["demarche_gabarits"][0]["francais"] = "Corrigé depuis"
        brouillon.abandonner(T)
        assert base.tables["demarche_gabarits"][0]["francais"] == "Corrigé depuis"

    def test_refuse_une_version_sans_champ(self, base):
        base.tables["demarche_versions"] = [_version(4, champs=())]
        with pytest.raises(brouillon.AbandonImpossible):
            brouillon.abandonner(T)
        assert base.ecritures == []

    def test_refuse_sans_version_publiee(self, base):
        base.tables["demarche_versions"] = []
        with pytest.raises(brouillon.AbandonImpossible):
            brouillon.abandonner(T)

    def test_une_lecture_ratee_ne_supprime_rien(self, base, monkeypatch):
        # La panne survient APRÈS la lecture des champs : l'ajout à retirer
        # est connu, mais rien ne doit être supprimé sur un tableau incomplet.
        base.tables["demarche_champs"].append({**AGE, "nom_champ": "profession_pere", "id": "u9"})
        vraie = demarche.lire_strictement

        def en_panne(nom, **f):
            if nom == "demarche_gabarits":
                raise demarche.LectureImpossible(nom)
            return vraie(nom, **f)

        monkeypatch.setattr(demarche, "lire_strictement", en_panne)
        with pytest.raises(demarche.LectureImpossible):
            brouillon.abandonner(T)
        assert [g for g, _t, _f in base.ecritures if g == "delete"] == []
        assert "profession_pere" in [l["nom_champ"] for l in base.tables["demarche_champs"]]
