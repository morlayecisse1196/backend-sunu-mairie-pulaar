"""
Le formulaire de l'acte, par démarche (étape 5.5).

Le document généré a des champs que personne ne peut deviner : le numéro et
l'année du registre, les mentions « en toutes lettres », le nom de l'officier
qui signe. Ils viennent du registre PAPIER, et c'est le consultant qui les
recopie.

Avant, ce formulaire était celui de l'extrait de naissance, pour TOUS les
dossiers. Un dossier de mariage héritait donc de cases qui ne le concernaient
pas (le bloc du jugement supplétif) et n'en avait aucune pour les siennes :
sa génération échouait sur des champs obligatoires que personne ne pouvait
remplir. Un cul-de-sac silencieux.

Le test central est `test_chaque_champ_manuel_a_une_case_pour_le_saisir` : il
relie le template du document au formulaire du consultant. C'est le lien qui
manquait, et le seul qui casse quand on ajoute un champ au document en
oubliant d'ouvrir la case correspondante.
"""
from __future__ import annotations

import re

import pytest

import document_generator as gen
import dossiers_repo
from dialogue_engine import CHAMPS_FORMULAIRE_PAR_TYPE_DOCUMENT

TOUTES_LES_CASES = {
    nom for champs in CHAMPS_FORMULAIRE_PAR_TYPE_DOCUMENT.values() for nom in champs
}


def _champs_manuels(type_demarche: str) -> set:
    """Les `source="formulaire.X"` du template d'une démarche."""
    modele = gen.MODELES[type_demarche]
    sources = [e.get("source") for e in modele.arbre().iter() if e.get("source")]
    manuels = set()
    for source in sources:
        for alternative in source.split("|"):
            alternative = alternative.strip()
            if alternative.startswith("formulaire."):
                manuels.add(alternative[len("formulaire."):])
    return manuels


@pytest.mark.parametrize("type_demarche", sorted(gen.DEMARCHES_AVEC_MODELE))
def test_chaque_champ_manuel_a_une_case_pour_le_saisir(type_demarche):
    manquants = sorted(_champs_manuels(type_demarche) - TOUTES_LES_CASES)
    assert not manquants, (
        f"{type_demarche} : aucune case de formulaire pour {manquants} — "
        "le consultant ne pourra jamais générer ce document"
    )


def test_le_mariage_a_son_propre_formulaire():
    assert dossiers_repo.type_document_acte("constatation_mariage") == "constatation_mariage"


def test_l_extrait_de_naissance_garde_son_nom_historique():
    # Les lignes déjà en base portent ce type_document : le changer les
    # rendrait invisibles, et le consultant retrouverait un formulaire vide
    # sur des dossiers déjà remplis.
    assert dossiers_repo.type_document_acte("extrait_naissance") == "extrait_naissance"
    assert dossiers_repo.type_document_acte(None) == "extrait_naissance"


def test_une_demarche_sans_document_n_a_pas_de_formulaire():
    # Plutôt qu'un formulaire vide, ou pire, celui d'une autre démarche.
    assert dossiers_repo.type_document_acte("changement_de_nom") is None


def test_le_mariage_n_herite_pas_des_cases_de_la_naissance():
    cases = set(CHAMPS_FORMULAIRE_PAR_TYPE_DOCUMENT["constatation_mariage"])
    # Le bloc du jugement supplétif n'existe que pour une naissance tardive.
    assert not cases & {"tribunalOuJuge", "dateJugementLettres", "numeroActe"}


def test_la_case_du_registre_n_est_pas_confondue_avec_la_piece_mariage():
    # "certificat_mariage" désigne une PIÈCE fournie par le citoyen (le mariage
    # des parents, pour une naissance) ; le certificat produit, lui, s'appelle
    # "constatation_mariage". Les confondre mélangerait la pièce reçue et
    # l'acte produit dans le même formulaire.
    piece = set(CHAMPS_FORMULAIRE_PAR_TYPE_DOCUMENT["certificat_mariage"])
    acte = set(CHAMPS_FORMULAIRE_PAR_TYPE_DOCUMENT["constatation_mariage"])
    assert not piece & acte


def test_les_cases_du_mariage_sont_vides_a_la_creation():
    # Rien n'est pré-rempli : aucune de ces valeurs ne vient du dialogue, et
    # une valeur inventée sur un acte d'état civil est pire qu'une case vide.
    from dialogue_engine import construire_champs_formulaire

    champs = construire_champs_formulaire("constatation_mariage", {"prenoms_epoux": "Amadou"})
    assert champs, "le formulaire du mariage ne doit pas être vide de cases"
    assert all(c["valeur"] is None for c in champs)
    assert all(c["source"] == "manuel" for c in champs)


class _Requete:
    """
    Juste assez de client Supabase pour voir ce que le dépôt demande et ce
    qu'il écrit — aucune base réelle n'est jointe.
    """

    def __init__(self, journal, lignes_existantes):
        self.journal = journal
        self.lignes = lignes_existantes

    def select(self, *_a):
        return self

    def eq(self, colonne, valeur):
        self.journal.setdefault("filtres", {})[colonne] = valeur
        return self

    def is_(self, *_a):
        return self

    def limit(self, *_a):
        return self

    def insert(self, payload):
        self.journal["insere"] = payload
        self.lignes = [payload]
        return self

    def execute(self):
        return type("Reponse", (), {"data": self.lignes})()


class _FauxSupabase:
    def __init__(self, journal):
        self.journal = journal

    def table(self, _nom):
        return _Requete(self.journal, [])


@pytest.fixture
def journal(monkeypatch):
    suivi = {}
    monkeypatch.setattr(dossiers_repo, "get_supabase_client", lambda: _FauxSupabase(suivi))
    return suivi


def test_un_dossier_de_mariage_recoit_le_formulaire_du_mariage(journal, monkeypatch):
    monkeypatch.setattr(dossiers_repo, "get_dossier",
                        lambda _id: {"id": "d1", "type_demarche": "constatation_mariage"})
    dossiers_repo.get_or_create_formulaire_acte("d1")

    assert journal["filtres"]["type_document"] == "constatation_mariage"
    cases = {c["nom"] for c in journal["insere"]["champs"]}
    assert "dateCelebrationLettres" in cases
    assert "tribunalOuJuge" not in cases, "le bloc du jugement supplétif n'a rien à faire ici"


def test_un_dossier_de_naissance_ne_change_pas_de_formulaire(journal, monkeypatch):
    monkeypatch.setattr(dossiers_repo, "get_dossier",
                        lambda _id: {"id": "d1", "type_demarche": "extrait_naissance"})
    dossiers_repo.get_or_create_formulaire_acte("d1")

    assert journal["filtres"]["type_document"] == "extrait_naissance"
    assert "numeroActe" in {c["nom"] for c in journal["insere"]["champs"]}


def test_un_dossier_sans_modele_n_ouvre_aucun_formulaire(journal, monkeypatch):
    monkeypatch.setattr(dossiers_repo, "get_dossier",
                        lambda _id: {"id": "d1", "type_demarche": "changement_de_nom"})
    assert dossiers_repo.get_or_create_formulaire_acte("d1") is None
    assert "insere" not in journal, "un formulaire a été créé pour une démarche sans document"


def test_aucune_case_du_mariage_ne_porte_sur_les_epoux():
    # Ces champs-là sont collectés à l'oral : les redemander au consultant
    # ouvrirait la porte à deux vérités différentes pour la même personne.
    cases = CHAMPS_FORMULAIRE_PAR_TYPE_DOCUMENT["constatation_mariage"]
    assert not [c for c in cases if re.match(r"^epou[xs]e?(Prenoms|NomFamille|Profession)", c)]
