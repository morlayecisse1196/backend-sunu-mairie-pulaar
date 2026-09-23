"""
Une base injoignable ne doit jamais être annoncée comme une migration manquante.

Les deux situations se ressemblent d'ici : dans les deux cas, la table de
configuration renvoie une liste vide. Mais l'une se répare en rallumant le
wifi et l'autre en appliquant un fichier SQL. Énoncer la mauvaise cause envoie
chercher dans la mauvaise direction, et une panne de trente secondes coûte
une soirée — c'est arrivé.
"""
from __future__ import annotations

import pytest

from services import demarche

#: Capturée à l'import, donc AVANT que le conftest ne coupe les tables : ces
#: tests-ci portent justement sur le vrai `_table` et sa gestion des pannes.
_TABLE_REELLE = demarche._table


@pytest.fixture(autouse=True)
def _vrai_table(monkeypatch):
    monkeypatch.setattr(demarche, "_table", _TABLE_REELLE)
    monkeypatch.setattr(demarche, "_derniere_erreur", None)
    yield
    monkeypatch.setattr(demarche, "_derniere_erreur", None)


class TestDerniereErreurLecture:
    def test_une_lecture_ratee_retient_sa_cause(self, monkeypatch):
        monkeypatch.setattr(demarche, "get_supabase_client", lambda: (_ for _ in ()).throw(
            OSError("[Errno 11001] getaddrinfo failed")))
        assert demarche._table("phrases_systeme") == []
        cause = demarche.derniere_erreur_lecture()
        assert cause is not None
        assert "phrases_systeme" in cause and "getaddrinfo" in cause

    def test_une_table_vide_mais_joignable_ne_signale_aucune_erreur(self, monkeypatch):
        # La distinction qui compte : lue avec succès, simplement vide —
        # là, et seulement là, la question des migrations se pose.
        class _Requete:
            def select(self, *_a): return self
            def eq(self, *_a): return self
            def execute(self): return type("R", (), {"data": []})()

        class _Client:
            def table(self, _nom): return _Requete()

        monkeypatch.setattr(demarche, "get_supabase_client", _Client)
        assert demarche._table("phrases_systeme") == []
        assert demarche.derniere_erreur_lecture() is None

    def test_une_lecture_reussie_efface_une_erreur_precedente(self, monkeypatch):
        # Sinon le script accuserait le réseau longtemps après son retour.
        monkeypatch.setattr(demarche, "get_supabase_client", lambda: (_ for _ in ()).throw(
            OSError("coupure")))
        demarche._table("demarche_champs")
        assert demarche.derniere_erreur_lecture() is not None

        class _Requete:
            def select(self, *_a): return self
            def eq(self, *_a): return self
            def execute(self): return type("R", (), {"data": [{"cle": "x"}]})()

        monkeypatch.setattr(demarche, "get_supabase_client",
                            lambda: type("C", (), {"table": lambda _s, _n: _Requete()})())
        assert demarche._table("demarche_champs") == [{"cle": "x"}]
        assert demarche.derniere_erreur_lecture() is None
