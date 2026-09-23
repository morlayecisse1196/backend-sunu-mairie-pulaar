from datetime import datetime, timedelta, timezone

import admin_repo


def _iso(jours_avant: int, heure: int = 9) -> str:
    base = datetime.now(timezone.utc) - timedelta(days=jours_avant)
    return base.replace(hour=heure, minute=0, second=0, microsecond=0).isoformat()


def test_evolution_couvre_30_jours_meme_sans_dossier():
    points = admin_repo._evolution_30_jours([])
    assert len(points) == 30
    assert all(point["recus"] == 0 and point["finalises"] == 0 for point in points)
    assert points[-1]["date"] == datetime.now(timezone.utc).date().isoformat()
    assert [p["date"] for p in points] == sorted(p["date"] for p in points)


def test_evolution_compte_recus_et_finalises():
    dossiers = [
        {"statut": "recu", "created_at": _iso(2), "updated_at": _iso(2)},
        {"statut": "finalise", "created_at": _iso(5), "updated_at": _iso(1)},
        {"statut": "en_cours", "created_at": _iso(2), "updated_at": _iso(2)},  # dialogue non déposé
        {"statut": "recu", "created_at": _iso(90), "updated_at": _iso(90)},  # hors fenêtre
    ]
    par_date = {point["date"]: point for point in admin_repo._evolution_30_jours(dossiers)}
    hier = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    avant_hier = (datetime.now(timezone.utc).date() - timedelta(days=2)).isoformat()
    assert par_date[avant_hier]["recus"] == 1  # le dialogue en_cours n'est pas compté
    assert par_date[hier]["finalises"] == 1
    assert sum(point["recus"] for point in par_date.values()) == 2  # le dossier vieux de 90 j est ignoré


def test_par_commune_agrege_et_trie(monkeypatch):
    monkeypatch.setattr(
        admin_repo, "list_consultants",
        lambda: [{"commune": "Ross-Béthio", "actif": True}, {"commune": "Ross-Béthio", "actif": False}],
    )
    monkeypatch.setattr(admin_repo, "resoudre_commune_id", lambda nom: {"Ross-Béthio": "c1"}.get(nom))
    dossiers = [
        {"statut": "recu", "commune_id": "c1"},
        {"statut": "genere", "commune_id": "c1"},
        {"statut": "bloque", "commune_id": "c1"},
        {"statut": "finalise", "commune_id": "c1", "created_at": _iso(3), "updated_at": _iso(1)},
        {"statut": "recu", "commune_id": "c2"},
    ]
    lignes = admin_repo._supervision_par_commune(dossiers, {"c1": "Ross-Béthio", "c2": "Podor"})
    assert [ligne["commune_id"] for ligne in lignes] == ["c1", "c2"]  # tri par volume décroissant
    premiere = lignes[0]
    assert premiere["total"] == 4 and premiere["a_traiter"] == 2  # recu + genere
    assert premiere["finalises"] == 1 and premiere["bloques"] == 1
    assert premiere["nb_consultants_actifs"] == 1  # le consultant désactivé ne compte pas
    assert premiere["delai_moyen_heures"] == 48.0
    assert lignes[1]["delai_moyen_heures"] is None
    assert "_delais" not in premiere


def test_par_commune_survit_a_une_erreur_de_consultants(monkeypatch):
    def _explose():
        raise RuntimeError("Auth indisponible")

    monkeypatch.setattr(admin_repo, "list_consultants", _explose)
    lignes = admin_repo._supervision_par_commune([{"statut": "recu", "commune_id": "c1"}], {})
    assert lignes[0]["total"] == 1 and lignes[0]["nb_consultants_actifs"] == 0


def test_duree_traitement_ignore_les_dossiers_non_finalises():
    assert admin_repo._duree_traitement_heures({"statut": "recu", "created_at": _iso(2), "updated_at": _iso(1)}) is None
    assert admin_repo._duree_traitement_heures({"statut": "finalise", "created_at": None, "updated_at": _iso(1)}) is None
    assert admin_repo._duree_traitement_heures({"statut": "finalise", "created_at": "pas une date", "updated_at": _iso(1)}) is None
