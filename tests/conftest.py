"""
Garde-fous communs aux tests unitaires.

`pytest.ini` promet des tests SANS réseau. Depuis l'étape 2.3, la définition
d'une démarche est lue en base : sans ce fichier, un test qui crée une session
irait interroger Supabase — lent, dépendant du réseau, et surtout dépendant du
contenu réel de la base du jour.

Les tables de configuration sont donc coupées par défaut : `services/demarche`
retombe sur ses constantes, comportement identique à celui d'avant l'étape 2.3.
Un test qui veut de vraies définitions les fournit lui-même (cf.
`tests/unit/test_demarche_conditions.py`, qui remplace les chargeurs).
"""
from __future__ import annotations

import pytest

from services import catalogue_audio, demarche


@pytest.fixture(autouse=True)
def _configuration_hors_ligne(monkeypatch):
    # Le cache est vidé avant ET après : une définition posée par un test ne
    # doit jamais fuir vers le suivant, dans un sens comme dans l'autre.
    demarche.vider_cache()
    monkeypatch.setattr(demarche, "_table", lambda _nom, **_filtres: [])
    yield
    demarche.vider_cache()


@pytest.fixture(autouse=True)
def _cache_audio_isole(monkeypatch, tmp_path):
    """
    Chaque test a son propre dossier d'audio pré-généré (étape 3.4).

    Sans cela, un test qui synthétise une phrase laisserait un fichier dans
    `audio_cache/phrases/` du dépôt, et le test suivant — ou la même phrase
    dans un autre test — trouverait un audio qu'il n'a pas produit. Le résultat
    dépendrait alors de l'ordre d'exécution.
    """
    monkeypatch.setattr(catalogue_audio, "DOSSIER_PHRASES", str(tmp_path / "phrases"))
