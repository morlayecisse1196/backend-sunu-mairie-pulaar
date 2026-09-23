import pytest
from fastapi import HTTPException

from services import audit, db


class _Requete:
    def __init__(self, magasin, erreur=None):
        self.magasin = magasin
        self.erreur = erreur
        self.filtres = {}

    def select(self, *args, **kwargs):
        return self

    def insert(self, ligne):
        self.ligne = ligne
        return self

    def eq(self, champ, valeur):
        self.filtres[champ] = valeur
        return self

    def in_(self, champ, valeurs):
        self.filtres[champ] = valeurs
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, n):
        self.limite = n
        return self

    def execute(self):
        if self.erreur:
            raise self.erreur
        if getattr(self, "ligne", None) is not None:
            self.magasin["ecrites"].append(self.ligne)
            return type("R", (), {"data": [self.ligne], "count": 1})
        lignes = [
            l for l in self.magasin["lues"]
            if all(l.get(champ) in valeur if isinstance(valeur, list) else l.get(champ) == valeur
                   for champ, valeur in self.filtres.items())
        ]
        return type("R", (), {"data": lignes, "count": len(lignes)})


class _Client:
    def __init__(self, magasin, erreur=None):
        self.magasin = magasin
        self.erreur = erreur

    def table(self, nom):
        assert nom == audit.TABLE
        return _Requete(self.magasin, self.erreur)


@pytest.fixture
def magasin(monkeypatch):
    magasin = {"ecrites": [], "lues": []}
    monkeypatch.setattr(db, "client", lambda: _Client(magasin))
    return magasin


async def test_journalisation_enregistre_l_acteur(magasin):
    await audit.journaliser(
        "dossier_debloque",
        acteur={"id": "a-1", "email": "admin@mairie.sn", "role": "admin"},
        cible_type="dossier", cible_id="d-1", cible_libelle="SM-2026-1",
    )
    ligne = magasin["ecrites"][0]
    assert ligne["acteur_id"] == "a-1" and ligne["acteur_email"] == "admin@mairie.sn"
    assert ligne["action"] == "dossier_debloque" and ligne["cible_libelle"] == "SM-2026-1"


async def test_journalisation_ne_fait_jamais_echouer_l_action(monkeypatch):
    """Une table d'audit absente ne doit pas casser le déblocage d'un dossier."""
    monkeypatch.setattr(db, "client", lambda: _Client({}, erreur=Exception("PGRST205 relation does not exist")))
    await audit.journaliser("dossier_debloque", acteur={"id": "a-1"})  # aucune exception


async def test_lecture_ajoute_un_libelle_francais(magasin):
    magasin["lues"] = [{"id": "1", "action": "consultant_mdp_reinitialise", "acteur_id": "a-1"}]
    resultat = await audit.lister(limite=10)
    assert resultat["entrees"][0]["libelle"] == "Mot de passe réinitialisé par l'administration"
    assert resultat["total"] == 1


async def test_lecture_du_journal_signale_la_migration_manquante(monkeypatch):
    monkeypatch.setattr(db, "client", lambda: _Client({}, erreur=Exception("PGRST205 relation does not exist")))
    with pytest.raises(HTTPException) as erreur:
        await audit.lister()
    assert erreur.value.status_code == 503 and erreur.value.detail["migration"] == audit.MIGRATION


async def test_activite_du_compte_filtre_sur_moi_et_reste_silencieuse(magasin, monkeypatch):
    magasin["lues"] = [
        {"id": "1", "action": "connexion", "acteur_id": "moi"},
        {"id": "2", "action": "connexion", "acteur_id": "un-autre"},
        {"id": "3", "action": "dossier_debloque", "acteur_id": "moi"},
    ]
    evenements = await audit.activite_du_compte("moi", limite=10)
    assert [e["id"] for e in evenements] == ["1"]

    monkeypatch.setattr(db, "client", lambda: _Client({}, erreur=Exception("PGRST205 relation does not exist")))
    assert await audit.activite_du_compte("moi") == []  # écran de profil lisible sans la migration 016


def test_toutes_les_actions_ont_un_libelle():
    assert set(audit.ACTIONS) <= set(audit.LIBELLES)
    assert set(audit.ACTIONS_COMPTE) <= set(audit.ACTIONS)
