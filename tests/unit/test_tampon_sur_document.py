"""
Le tampon numérique de la commune sur le document généré (§5.4, étape 5.5).

L'administrateur pouvait enregistrer le tampon d'une commune, et sa
confirmation était journalisée — mais ce tampon n'arrivait JAMAIS sur un
document. La génération l'ignorait complètement : le consultant produisait un
acte nu, et le tampon restait une image dans un bucket.

Ce fichier vérifie les deux sens : le tampon arrive quand la commune en a un,
et il n'arrive pas quand elle n'en a pas — ni par défaut, ni par erreur, ni
depuis une autre commune.
"""
from __future__ import annotations

import base64

import pytest

import document_generator as gen

IMAGE = b"\x89PNG\r\n\x1a\n" + b"faux-tampon-de-test" * 3
COMMUNE_AVEC = {"nom": "Touba", "region": "Diourbel", "departement": "Mbacké",
                "tampon_numerique_url": "commune-1/20260101120000.png"}
COMMUNE_SANS = {"nom": "Touba", "region": "Diourbel", "departement": "Mbacké",
                "tampon_numerique_url": None}


@pytest.fixture
def stockage(monkeypatch):
    """Le bucket des tampons, sans réseau. Compte les téléchargements."""
    appels = []

    def telecharger(chemin):
        appels.append(chemin)
        return IMAGE

    monkeypatch.setattr(gen, "telecharger_tampon", telecharger)
    return appels


class TestQuandLeTamponArrive:
    def test_une_commune_qui_a_un_tampon_le_voit_sur_le_document(self, stockage):
        tampon = gen.tampon_de_la_commune(COMMUNE_AVEC)
        assert tampon.startswith("data:image/png;base64,")
        assert base64.b64decode(tampon.split(",", 1)[1]) == IMAGE

    def test_l_image_voyage_DANS_le_document(self, stockage):
        # Et non par un lien : une URL signée expire au bout d'une heure, et un
        # acte qui perd son tampon le lendemain a l'air trafiqué.
        tampon = gen.tampon_de_la_commune(COMMUNE_AVEC)
        assert "http" not in tampon
        assert stockage == [COMMUNE_AVEC["tampon_numerique_url"]]

    @pytest.mark.parametrize("extension,type_attendu", [
        ("png", "image/png"), ("jpg", "image/jpeg"),
        ("jpeg", "image/jpeg"), ("webp", "image/webp"),
    ])
    def test_les_formats_d_image_courants_sont_reconnus(self, stockage, extension, type_attendu):
        commune = dict(COMMUNE_AVEC, tampon_numerique_url=f"c1/2026.{extension}")
        assert gen.tampon_de_la_commune(commune).startswith(f"data:{type_attendu};base64,")


class TestQuandLeTamponN_arrivePas:
    def test_une_commune_sans_tampon_n_en_recoit_aucun(self, stockage):
        assert gen.tampon_de_la_commune(COMMUNE_SANS) is None
        assert stockage == [], "le stockage a été interrogé pour rien"

    def test_aucun_tampon_n_est_invente_quand_la_commune_est_inconnue(self, stockage):
        assert gen.tampon_de_la_commune(None) is None
        assert gen.tampon_de_la_commune({}) is None

    def test_un_fichier_de_type_inconnu_n_est_pas_devine(self, stockage):
        # Un PDF ou un .doc déposé par erreur ne doit pas être collé dans une
        # balise image en espérant que ça marche.
        commune = dict(COMMUNE_AVEC, tampon_numerique_url="c1/tampon.pdf")
        assert gen.tampon_de_la_commune(commune) is None
        assert stockage == []

    def test_un_stockage_injoignable_ne_bloque_pas_la_delivrance(self, monkeypatch):
        # Le consultant a un citoyen au guichet : mieux vaut un acte sans
        # tampon qu'aucun acte.
        monkeypatch.setattr(gen, "telecharger_tampon", lambda _c: None)
        assert gen.tampon_de_la_commune(COMMUNE_AVEC) is None


class TestSurLeDocumentImprime:
    """Les trois documents portent le tampon au même endroit : sous la signature."""

    CAS = {
        "extrait_naissance": {},
        "constatation_mariage": {},
        "declaration_deces": {},
    }

    def _html(self, type_demarche, tampon):
        return gen._rendre_html({}, False, "S-1", gen.MODELES[type_demarche], tampon=tampon)

    @pytest.mark.parametrize("type_demarche", sorted(CAS))
    def test_le_tampon_apparait_sur_chaque_document(self, type_demarche):
        html = self._html(type_demarche, "data:image/png;base64,AAAA")
        assert "data:image/png;base64,AAAA" in html
        assert "Tampon numérique de la mairie" in html

    @pytest.mark.parametrize("type_demarche", sorted(CAS))
    def test_sans_tampon_aucune_image_vide_n_est_laissee(self, type_demarche):
        # Une balise <img src=""> afficherait une icône d'image cassée sur un
        # acte d'état civil.
        html = self._html(type_demarche, None)
        assert "<img" not in html

    @pytest.mark.parametrize("type_demarche", sorted(CAS))
    def test_un_document_tamponne_n_est_plus_un_brouillon(self, type_demarche):
        # Décision du porteur du projet (2026-09-26) : la confirmation de
        # l'administrateur suffit à faire sauter le bandeau. Elle est
        # journalisée — on sait qui a autorisé ce tampon, et quand.
        html = self._html(type_demarche, "data:image/png;base64,AAAA")
        assert "BROUILLON OFFICIEL" not in html
        assert "DOCUMENT DÉLIVRÉ PAR LA MAIRIE" in html

    @pytest.mark.parametrize("type_demarche", sorted(CAS))
    def test_sans_tampon_le_bandeau_brouillon_reste(self, type_demarche):
        # C'est l'autre moitié de la règle, et la plus importante : un
        # document non tamponné ne doit JAMAIS avoir l'air officiel.
        html = self._html(type_demarche, None)
        assert "BROUILLON OFFICIEL" in html
        assert "DOCUMENT DÉLIVRÉ PAR LA MAIRIE" not in html

    @pytest.mark.parametrize("type_demarche", sorted(CAS))
    def test_le_numero_de_suivi_accompagne_le_document_dans_les_deux_cas(self, type_demarche):
        # C'est par lui que le citoyen et le guichet retrouvent le dossier :
        # il ne doit pas disparaître avec le bandeau.
        for tampon in (None, "data:image/png;base64,AAAA"):
            assert "S-1" in self._html(type_demarche, tampon)
