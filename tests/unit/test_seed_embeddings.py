"""
Vecteurs de recherche des fiches d'information.

Une fiche ajoutée sans vecteur est INVISIBLE pour le mode information : la
recherche ne la trouve pas, et rien ne le signale — ni erreur, ni journal. Le
script est donc le seul endroit où ce défaut peut se voir.

Ce qui est verrouillé ici :

  * lancé avec le mauvais Python, il dit lequel utiliser au lieu d'un
    traceback ;
  * sans URL de base, il le dit aussi, sans jamais réclamer l'URL en argument ;
  * `--verifier` n'écrit rien ;
  * une fiche renommée est revectorisée, une fiche inchangée est laissée.
"""
from __future__ import annotations

import numpy
import pytest

import seed_embeddings


class TestTexteVectorise:
    def test_le_nom_et_la_categorie(self):
        assert seed_embeddings.texte_a_vectoriser("Extrait de naissance", "État Civil") == \
            "Extrait de naissance État Civil"

    def test_une_categorie_absente_ne_laisse_pas_d_espace_en_trop(self):
        # Un espace parasite change le vecteur, donc les résultats de recherche.
        assert seed_embeddings.texte_a_vectoriser("Extrait de naissance", None) == "Extrait de naissance"
        assert seed_embeddings.texte_a_vectoriser(None, None) == ""


class TestGardeFous:
    def test_sans_url_de_base_il_explique(self, monkeypatch, capsys):
        monkeypatch.setattr(seed_embeddings, "load_dotenv", lambda: None)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
        monkeypatch.setattr(seed_embeddings, "_dependances",
                            lambda: pytest.fail("connexion tentée sans URL"))
        with pytest.raises(SystemExit):
            seed_embeddings.main()
        assert "DATABASE_URL" in capsys.readouterr().out

    def test_l_url_n_est_jamais_attendue_en_argument(self, monkeypatch, capsys):
        # Une URL passée en ligne de commande resterait dans l'historique du
        # terminal, avec le mot de passe de la base.
        monkeypatch.setattr(seed_embeddings, "load_dotenv", lambda: None)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
        with pytest.raises(SystemExit):
            seed_embeddings.main()
        assert "historique" in capsys.readouterr().out

    def test_un_module_manquant_donne_la_commande_du_venv(self, monkeypatch, capsys):
        # C'est l'erreur réelle rencontrée : `python seed_embeddings.py` au
        # lieu du Python du venv, et un ModuleNotFoundError brut.
        import builtins
        vrai_import = builtins.__import__

        def sans_pgvector(nom, *args, **kwargs):
            if nom.startswith("pgvector"):
                raise ModuleNotFoundError("No module named 'pgvector'", name="pgvector")
            return vrai_import(nom, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", sans_pgvector)
        with pytest.raises(SystemExit):
            seed_embeddings._dependances()
        sortie = capsys.readouterr().out
        # La COMMANDE exacte, pas seulement le mot « venv » : c'est elle qui
        # sort l'utilisateur de l'erreur.
        assert "pgvector" in sortie and seed_embeddings.COMMANDE_VENV in sortie


class _Curseur:
    """Assez de psycopg pour dérouler le script sans base."""

    def __init__(self, fiches, contrainte):
        self.fiches, self.contrainte = fiches, contrainte
        self.ecritures: list[tuple] = []
        self._derniere = ""

    def execute(self, sql, params=None):
        self._derniere = sql
        if "INSERT INTO demarches_embeddings" in sql:
            self.ecritures.append(params)

    def fetchall(self):
        return self.fiches

    def fetchone(self):
        return (1,) if self.contrainte else None

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class _Connexion:
    def __init__(self, curseur):
        self._curseur = curseur
        self.commits = 0

    def cursor(self):
        return self._curseur

    def commit(self):
        self.commits += 1

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def _preparer(monkeypatch, fiches, contrainte=True):
    import types

    curseur = _Curseur(fiches, contrainte)
    connexion = _Connexion(curseur)
    encodages: list[str] = []

    class _Modele:
        def __init__(self, _nom):
            pass

        def encode(self, texte):
            # Le vrai modèle rend un tableau numpy, d'où le `.tolist()` côté
            # script : un double qui rendrait une liste masquerait l'erreur.
            encodages.append(texte)
            return numpy.array([0.1, 0.2])

    faux_psycopg = types.SimpleNamespace(
        connect=lambda _url: connexion, OperationalError=ConnectionError)
    monkeypatch.setattr(seed_embeddings, "load_dotenv", lambda: None)
    monkeypatch.setenv("DATABASE_URL", "postgresql://exemple")
    monkeypatch.setattr(seed_embeddings, "_dependances",
                        lambda: (faux_psycopg, lambda _c: None, _Modele))
    return curseur, connexion, encodages


class TestDeroule:
    FICHES = [("id-1", "Extrait de naissance", "État Civil", "Extrait de naissance État Civil"),
              ("id-2", "Constatation de mariage", "État Civil", None)]

    def test_seules_les_fiches_a_jour_sont_laissees_tranquilles(self, monkeypatch):
        curseur, connexion, encodages = _preparer(monkeypatch, self.FICHES)
        assert seed_embeddings.main() == 0
        assert encodages == ["Constatation de mariage État Civil"]
        assert len(curseur.ecritures) == 1 and connexion.commits == 1

    def test_rien_a_faire_ne_charge_pas_le_modele(self, monkeypatch, capsys):
        # Le modèle pèse plusieurs centaines de Mo : le charger pour rien fait
        # croire à une panne pendant une minute.
        a_jour = [self.FICHES[0]]
        _, _, encodages = _preparer(monkeypatch, a_jour)
        assert seed_embeddings.main() == 0
        assert encodages == []
        assert "deja a jour" in capsys.readouterr().out

    def test_verifier_n_ecrit_rien(self, monkeypatch, capsys):
        curseur, connexion, encodages = _preparer(monkeypatch, self.FICHES)
        assert seed_embeddings.main(verifier=True) == 0
        assert curseur.ecritures == [] and connexion.commits == 0 and encodages == []
        assert "Rien n'a ete ecrit" in capsys.readouterr().out

    def test_sans_contrainte_d_unicite_on_s_arrete_et_on_explique(self, monkeypatch, capsys):
        # Sinon l'écriture échoue sur un message Postgres incompréhensible et
        # AUCUN vecteur n'est écrit : la recherche ne trouve plus rien.
        curseur, _, encodages = _preparer(monkeypatch, self.FICHES, contrainte=False)
        with pytest.raises(SystemExit):
            seed_embeddings.main()
        sortie = capsys.readouterr().out
        assert "032" in sortie and "migrer" in sortie
        assert curseur.ecritures == [] and encodages == []
