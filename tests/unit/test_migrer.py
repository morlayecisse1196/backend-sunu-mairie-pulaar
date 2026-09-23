"""
Registre des migrations (`scripts/migrer.py`).

« Est-ce que la migration 019 est passée ? » n'avait aucune réponse fiable :
il fallait aller regarder si telle colonne existait. Ce qui est verrouillé
ici :

  * le mot de passe n'apparaît JAMAIS dans ce que le script affiche ;
  * une migration modifiée après avoir été appliquée est détectée — c'est
    ainsi que la base et le dépôt divergent sans que personne ne le voie ;
  * les migrations sont jouées dans l'ordre des numéros.
"""
from __future__ import annotations

import sys

import pytest

sys.path.insert(0, "scripts")

import migrer  # noqa: E402

URL = "postgresql://postgres:MOT_DE_PASSE_SECRET@db.exemple.supabase.co:5432/postgres"


class TestAdresse:
    def test_le_mot_de_passe_n_est_jamais_affiche(self):
        # Le script imprime l'adresse de la base pour que l'on sache où l'on
        # tape. Il ne doit pas imprimer de quoi s'y connecter.
        affichee = migrer._sans_secret(URL)
        assert "MOT_DE_PASSE_SECRET" not in affichee
        assert "postgres:" not in affichee
        assert "db.exemple.supabase.co" in affichee

    def test_le_chiffrement_est_exige(self, monkeypatch):
        # Supabase refuse une connexion en clair ; l'oubli se traduirait par
        # une erreur incompréhensible côté utilisateur.
        monkeypatch.setenv("DATABASE_URL", URL)
        assert "sslmode=require" in migrer._url()

    def test_un_sslmode_deja_choisi_est_respecte(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", URL + "?sslmode=verify-full")
        assert migrer._url().count("sslmode=") == 1

    def test_sans_adresse_le_script_s_arrete(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
        with pytest.raises(SystemExit):
            migrer._url()


class TestRegistre:
    def test_les_migrations_sont_lues_dans_l_ordre_des_numeros(self):
        noms = [nom for nom, _contenu, _empreinte in migrer._fichiers()]
        assert noms == sorted(noms)
        assert noms[0].startswith("001_")

    def test_chaque_migration_a_une_empreinte_distincte(self):
        empreintes = [e for _n, _c, e in migrer._fichiers()]
        assert len(set(empreintes)) == len(empreintes)

    def test_une_migration_modifiee_apres_coup_est_detectee(self):
        # Le fichier dit une chose, la base en contient une autre : c'est
        # exactement ce qu'un registre doit rendre visible.
        fichiers = migrer._fichiers()
        nom, _contenu, empreinte = fichiers[0]
        assert migrer._verifier_non_modifiees(fichiers, {nom: empreinte}) == []
        assert migrer._verifier_non_modifiees(fichiers, {nom: "empreinte d'avant"}) == [nom]

    def test_une_migration_jamais_appliquee_n_est_pas_signalee_comme_modifiee(self):
        # Manquante et modifiée sont deux situations différentes : l'une
        # s'applique, l'autre demande une décision.
        assert migrer._verifier_non_modifiees(migrer._fichiers(), {}) == []
