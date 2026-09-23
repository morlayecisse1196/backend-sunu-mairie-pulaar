from services.db import est_erreur_schema, migration_manquante


class FausseErreurPostgrest(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.message = message
        self.code = code


def test_table_absente_reconnue():
    assert est_erreur_schema(FausseErreurPostgrest("Could not find the table 'public.notifications'", "PGRST205"))
    assert est_erreur_schema(Exception('relation "public.dialogue_sessions" does not exist (42P01)'))


def test_colonne_absente_reconnue():
    assert est_erreur_schema(FausseErreurPostgrest("Could not find the 'nom_complet' column of 'profiles'", "PGRST204"))


def test_erreur_ordinaire_non_confondue():
    assert not est_erreur_schema(Exception("duplicate key value violates unique constraint"))
    assert not est_erreur_schema(TimeoutError("timeout"))


def test_migration_manquante_503_explicite():
    exc = migration_manquante("014", "Les notifications")
    assert exc.status_code == 503
    assert exc.detail["code"] == "migration_manquante"
    assert "014" in exc.detail["message"]
