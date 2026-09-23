"""
Lecture du fichier de relecture (`scripts/atelier_pulaar.py`).

Une tabulation perdue décale tout : le contexte glisse dans la colonne du
pulaar, et `csv.DictReader` l'accepte sans broncher. C'est arrivé — trois
lignes mal formées ont mis « Question du champ « commune_naissance » » en base
comme traduction pulaar de deux questions du dialogue, marquées relues, prêtes
à être lues à voix haute par la synthèse.

Rien ne le signalait : ni à l'import, ni au listing, ni au dialogue.
"""
from __future__ import annotations

import pytest

import scripts.atelier_pulaar as script

ENTETE = "identifiant\tfrancais\tpulaar\tcontexte"


def _fichier(tmp_path, *lignes: str) -> str:
    chemin = tmp_path / "phrases.tsv"
    chemin.write_text("\n".join((ENTETE, *lignes)) + "\n", encoding="utf-8")
    return str(chemin)


def test_un_fichier_bien_forme_est_lu(tmp_path):
    chemin = _fichier(tmp_path, "champ:a:question\tLe français ?\tPulaar.\tContexte.")
    traductions, malformees = script._lire_tsv(chemin)
    assert traductions == {"champ:a:question": "Pulaar."}
    assert malformees == []


def test_une_tabulation_perdue_est_signalee_avec_son_numero_de_ligne(tmp_path):
    # Le français et le pulaar collés dans la même cellule : trois colonnes
    # au lieu de quatre, et le contexte prend la place du pulaar.
    chemin = _fichier(tmp_path, "champ:a:question\tLe français ? Pulaar collé.\tContexte.")
    traductions, malformees = script._lire_tsv(chemin)
    assert traductions == {}, "rien n'est importé d'une ligne décalée"
    assert "ligne 2" in malformees[0]
    assert "champ:a:question" in malformees[0]


def test_une_colonne_en_trop_est_aussi_refusee(tmp_path):
    # Une tabulation DANS une traduction découpe la phrase en deux.
    chemin = _fichier(tmp_path, "champ:a:question\tFr\tPul\tCtx\tEn trop")
    _traductions, malformees = script._lire_tsv(chemin)
    assert malformees, "5 colonnes au lieu de 4"


def test_une_ligne_decalee_empeche_tout_l_import(tmp_path, monkeypatch):
    # Les bonnes lignes du fichier ne sont pas importées non plus : mieux vaut
    # un import refusé qu'un import à moitié fait, dont on ne saura plus dire
    # quelle moitié est passée.
    ecritures: list = []
    monkeypatch.setattr(
        script.atelier, "enregistrer",
        lambda *a, **k: ecritures.append((a, k)) or {"phrases": 0, "lignes": 0},
    )
    chemin = _fichier(
        tmp_path,
        "champ:a:question\tFr A ?\tPulaar A.\tContexte A.",
        "champ:b:question\tFr B ? Pulaar collé.\tContexte B.",
    )
    assert script._importer(chemin, valider=False, par=None, type_demarche="d") == 2
    assert ecritures == [], "la ligne A, pourtant correcte, n'est pas importée non plus"


def test_une_traduction_laissee_vide_n_est_pas_une_erreur(tmp_path):
    # Le cas normal d'une relecture partielle : on remplit ce qu'on sait.
    chemin = _fichier(tmp_path, "champ:a:question\tLe français ?\t\tContexte.")
    traductions, malformees = script._lire_tsv(chemin)
    assert traductions == {}
    assert malformees == []


def test_le_vrai_fichier_du_depot_est_bien_forme():
    """
    `phrases.tsv` est le fichier que l'on réimporte après chaque relecture.
    Le garder bien formé évite de redécouvrir le problème en dialogue.
    """
    import os

    chemin = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "phrases.tsv")
    if not os.path.exists(chemin):
        pytest.skip("phrases.tsv absent de ce dépôt")
    _traductions, malformees = script._lire_tsv(chemin)
    assert malformees == [], f"lignes décalées : {malformees}"
