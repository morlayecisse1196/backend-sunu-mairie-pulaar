"""
L'envoi de photo refuse la partie confidentielle (étape 5.4).

Le module `services/partie_confidentielle` sait la reconnaître ; encore
faut-il qu'elle soit examinée AVANT l'enregistrement, et que rien ne permette
de passer outre. `forcer=true` existe pour assumer une photo floue, pas pour
verser une donnée de santé au dossier d'une mairie.
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

import main
from services import partie_confidentielle as pc

CITOYEN = {"id": "citoyen-1", "email": "a@b.sn"}


@pytest.fixture
def client(monkeypatch):
    enregistres: list[tuple] = []
    examens: list[bytes] = []

    def upload_document(dossier_id, type_document, contenu, mime, extension):
        enregistres.append((dossier_id, type_document, contenu))
        return {"id": "doc-1", "type": type_document, "statut": "recu"}

    def examiner(octets, **_k):
        examens.append(octets)
        if b"CAUSES" in octets:
            return pc.CONFIDENTIELLE, pc.MESSAGE
        return None, None

    monkeypatch.setattr(main, "get_dossier", lambda _id: {"id": "dossier-1", "citoyen_id": CITOYEN["id"]})
    monkeypatch.setattr(main, "upload_document", upload_document)
    monkeypatch.setattr(main.partie_confidentielle, "examiner", examiner)
    monkeypatch.setattr(main.qualite_photo, "evaluer",
                        lambda _octets: main.qualite_photo.Verdict(True))
    monkeypatch.setattr(main.relances, "planifier", lambda _coroutine: None)
    monkeypatch.setattr(main.relances, "pousser_message", lambda *a, **k: None)
    monkeypatch.setattr(main.relances, "relancer_apres_document", lambda *a, **k: None)
    monkeypatch.setattr(main.evenements, "ajouter_evenement", lambda *a, **k: None)
    monkeypatch.setattr(main.demarche_config, "types_documents_acceptes",
                        lambda: ("certificat_deces", "cni_declarant_recto"))

    main.app.dependency_overrides[main.get_current_user] = lambda: CITOYEN
    yield TestClient(main.app), enregistres, examens
    main.app.dependency_overrides.clear()


def _envoyer(http, contenu: bytes, type_document="certificat_deces", forcer=None):
    donnees = {"type": type_document}
    if forcer is not None:
        donnees["forcer"] = str(forcer).lower()
    return http.post(
        "/dossiers/dossier-1/documents",
        files={"fichier": ("photo.jpg", io.BytesIO(contenu), "image/jpeg")},
        data=donnees,
        headers={"Authorization": "Bearer jeton"},
    )


class TestRefus:
    def test_la_partie_confidentielle_n_est_jamais_enregistree(self, client):
        http, enregistres, _ = client
        reponse = _envoyer(http, b"CERTIFICAT DE CAUSES DE DECES")
        assert reponse.status_code == 422
        assert reponse.json()["detail"]["code"] == pc.CONFIDENTIELLE
        assert enregistres == []

    def test_forcer_ne_permet_pas_de_passer_outre(self, client):
        # `forcer` sert à assumer une photo floue. Une donnée de santé
        # enregistrée, elle, ne se rattrape pas.
        http, enregistres, _ = client
        assert _envoyer(http, b"CERTIFICAT DE CAUSES DE DECES", forcer=True).status_code == 422
        assert enregistres == []

    def test_le_citoyen_est_reoriente_vers_la_bonne_partie(self, client):
        http, _, _ = client
        message = _envoyer(http, b"CERTIFICAT DE CAUSES DE DECES").json()["detail"]["message"]
        assert "partie du haut" in message


class TestAcceptation:
    def test_la_partie_haute_est_enregistree(self, client):
        http, enregistres, _ = client
        assert _envoyer(http, b"CERTIFICAT DE DECES partie a detacher").status_code == 200
        assert enregistres[0][1] == "certificat_deces"

    def test_les_autres_pieces_ne_sont_pas_examinees(self, client):
        # L'examen lance une reconnaissance de texte : la faire sur chaque
        # carte d'identité coûterait des secondes pour rien.
        http, enregistres, examens = client
        assert _envoyer(http, b"CNI", type_document="cni_declarant_recto").status_code == 200
        assert examens == [] and enregistres[0][1] == "cni_declarant_recto"
