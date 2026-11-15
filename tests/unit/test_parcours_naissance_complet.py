"""
Le parcours complet d'un extrait de naissance : du dialogue au PDF tamponné.

Chaque morceau de la chaîne était testé séparément — le dialogue, la
résolution, le XSD, le rendu — mais JAMAIS bout à bout. Ce fichier suit un
dossier du premier mot du citoyen jusqu'au PDF que le consultant envoie, avec
le tampon de la commune dessus.

Ce qu'il ne peut pas faire ici : l'extraction des réponses du citoyen passe
par un modèle de langue distant, et les tests tournent sans réseau (pytest.ini).
Le parcours démarre donc aux slots tels que le dialogue les laisse, et la
partie moteur (relecture obligatoire avant tout document) est vérifiée avec ses
dépendances simulées, comme dans test_moteur.py.

Le PDF, lui, est RÉELLEMENT produit : weasyprint tourne pour de bon dans ce
test. C'est la seule façon de savoir que le document sort, et pas seulement
que le HTML se rend.
"""
from __future__ import annotations

import base64

import pytest

import document_generator as gen
from temps_reel import moteur
from temps_reel.etat import nouvel_etat
from test_moteur import Espion  # harnais du moteur, déjà éprouvé

TAMPON = b"\x89PNG\r\n\x1a\n" + b"tampon-de-la-commune" * 4

COMMUNE = {
    "id": "commune-1", "nom": "Ross-Béthio", "region": "Saint-Louis",
    "departement": "Dagana", "arrondissement": "Rosso-Sénégal",
    "tampon_numerique_url": "commune-1/20260101120000.png",
}

# Ce que le dialogue laisse dans le dossier après la relecture confirmée.
SLOTS = {
    "age_enfant": {"valeur": 7, "unite": "jours"},
    "commune_naissance": "Ross-Béthio",
    "nom_enfant": "Ibrahima Diallo",
    "date_naissance_enfant": "2026-09-07",
    "sexe_enfant": "masculin",
    "nom_declarant": "Modou Diallo",
    "nom_mere": "Aissatou Ba",
    "date_naissance_mere": "1998-03-12",
    "parents_maries": True,
}

DOSSIER = {
    "id": "dossier-1", "type_demarche": "extrait_naissance",
    "cas_legal": "dans_les_delais", "statut": "en_traitement",
    "commune_id": "commune-1", "numero_suivi": "SM-2026-000452",
    "slots": SLOTS,
}

# Ce que le consultant recopie du registre papier. Les dates en toutes lettres
# n'y sont plus : elles s'écrivent seules depuis la date du dialogue.
SAISIE_CONSULTANT = {
    # 19 chiffres : la suite de cases « ERVE » en bas du formulaire. Le nombre
    # exact reste une hypothèse du XSD, à confirmer par le service d'état civil.
    "numeroActe": "2026041200000000412",
    "anneeRegistreLettres": "deux mille vingt-six",
    "anneeRegistreChiffres": "2026",
    "numeroRegistreLettres": "quatre cent douze",
    "numeroRegistreChiffres": "412",
    "prenomEnfant": "Ibrahima",
    "nomFamilleEnfant": "Diallo",
    "prenomMere": "Aissatou",
    "nomFamilleMere": "Ba",
    "officierEtatCivil": "Mamadou Sow",
}


def _formulaire(champs: dict) -> dict:
    return {"id": "f-acte", "type_document": "extrait_naissance",
            "champs": [{"nom": nom, "valeur": valeur, "source": "manuel"}
                       for nom, valeur in champs.items()]}


@pytest.fixture
def mairie(monkeypatch):
    """La base et le stockage de la commune, sans réseau."""
    journal = {"cas_particuliers": []}

    monkeypatch.setattr(gen, "get_dossier", lambda _id: DOSSIER)
    monkeypatch.setattr(gen, "get_commune", lambda _id: COMMUNE)
    monkeypatch.setattr(gen, "list_document_formulaires", lambda _id: [])
    monkeypatch.setattr(gen, "telecharger_tampon", lambda _c: TAMPON)
    monkeypatch.setattr(
        gen, "create_cas_particulier",
        lambda dossier_id, type_incident, description, **kw:
            journal["cas_particuliers"].append((type_incident, description)))
    return journal


def _avec_saisie(monkeypatch, champs):
    monkeypatch.setattr(gen, "get_or_create_formulaire_acte", lambda _id: _formulaire(champs))


class TestLeDialogueAvantLeDocument:
    """
    Le document n'existe que si le citoyen a relu et confirmé. C'est le nœud
    RG7 : sans lui, un acte partirait sur une réponse mal comprise.
    """

    async def test_la_collecte_complete_impose_la_relecture(self):
        espion = Espion()
        etat = nouvel_etat(session_id="s-1", cle_client="k", citoyen_id="citoyen-1",
                           commune_profil="Ross-Béthio")
        etat.update(mode="administratif", dossier_id="dossier-1", slots=dict(SLOTS))
        espion.resultat_collecte = {"reponse_fr": None, "document_attendu": None,
                                    "phase_suivante": "complet"}

        resultat = await moteur.traiter_message(etat, "C'est tout", espion.deps())

        assert etat["phase"] == "relecture_en_cours"
        assert "Est-ce que tout est exact" in resultat.reponse_fr
        assert etat["cas_legal"] == "dans_les_delais"


class TestLeConsultantGenereLeDocument:
    def test_sans_la_saisie_du_registre_la_generation_refuse_et_s_explique(
            self, mairie, monkeypatch):
        # Le numéro d'acte et le signataire ne peuvent venir que du registre
        # papier : le consultant doit les saisir avant de pouvoir générer.
        _avec_saisie(monkeypatch, {})

        with pytest.raises(gen.ErreurGenerationDocument) as echec:
            gen.generer_document("dossier-1")

        manquants = " ".join(echec.value.erreurs)
        assert "numeroActe" in manquants and "officierEtatCivil" in manquants
        assert mairie["cas_particuliers"], "aucun cas particulier n'a été ouvert"
        assert mairie["cas_particuliers"][0][0] == "champ_manquant"

    def test_les_dates_en_lettres_ne_sont_plus_a_saisir(self, mairie, monkeypatch):
        _avec_saisie(monkeypatch, {})
        with pytest.raises(gen.ErreurGenerationDocument) as echec:
            gen.generer_document("dossier-1")
        assert not [e for e in echec.value.erreurs if e.startswith("dateNaissanceLettres")]

    def test_le_dossier_complet_produit_un_vrai_PDF(self, mairie, monkeypatch):
        _avec_saisie(monkeypatch, SAISIE_CONSULTANT)

        pdf = gen.generer_document("dossier-1")

        assert pdf.startswith(b"%PDF-"), "ce n'est pas un PDF"
        # Un PDF d'une page avec un tampon : quelques dizaines de Ko. En
        # dessous de 5 Ko, c'est une page blanche.
        assert len(pdf) > 5000
        assert mairie["cas_particuliers"] == []

    def test_le_document_porte_bien_ce_que_le_citoyen_a_dit(self, mairie, monkeypatch):
        _avec_saisie(monkeypatch, SAISIE_CONSULTANT)
        valeurs, erreurs = gen.resoudre_template(DOSSIER, COMMUNE, SAISIE_CONSULTANT, False)
        assert erreurs == []

        html = gen._rendre_html(valeurs, False, DOSSIER["numero_suivi"],
                                gen.MODELES["extrait_naissance"],
                                tampon=gen.tampon_de_la_commune(COMMUNE))

        assert "Ibrahima" in html and "Diallo" in html
        assert "Aissatou" in html                      # la mère, dite au dialogue
        assert "Ross-Béthio" in html                   # la commune de naissance
        assert "MASCULIN" in html                      # le sexe, écrit en toutes lettres
        assert "sept septembre deux mille vingt-six" in html  # date écrite seule
        assert "SM-2026-000452" in html                # le numéro de suivi du citoyen

    def test_la_generation_va_vraiment_chercher_le_tampon(self, mairie, monkeypatch):
        # Le test suivant vérifie le rendu ; celui-ci vérifie que la
        # GÉNÉRATION le demande. Sans lui, un tampon parfaitement fabriqué
        # pourrait n'être jamais posé sur le document que reçoit le citoyen.
        _avec_saisie(monkeypatch, SAISIE_CONSULTANT)
        rendus = []
        monkeypatch.setattr(gen, "_convertir_pdf",
                            lambda html: rendus.append(html) or b"%PDF-faux")

        gen.generer_document("dossier-1")

        assert base64.b64encode(TAMPON).decode() in rendus[0]

    def test_le_tampon_de_la_commune_est_sur_le_document(self, mairie, monkeypatch):
        _avec_saisie(monkeypatch, SAISIE_CONSULTANT)
        valeurs, _ = gen.resoudre_template(DOSSIER, COMMUNE, SAISIE_CONSULTANT, False)

        html = gen._rendre_html(valeurs, False, "S-1", gen.MODELES["extrait_naissance"],
                                tampon=gen.tampon_de_la_commune(COMMUNE))

        assert base64.b64encode(TAMPON).decode() in html
        assert "Tampon numérique de la mairie" in html

    def test_une_commune_sans_tampon_delivre_quand_meme(self, mairie, monkeypatch):
        # La plupart des communes n'ont pas encore déposé leur tampon : le
        # parcours ne doit pas s'arrêter pour autant.
        _avec_saisie(monkeypatch, SAISIE_CONSULTANT)
        monkeypatch.setattr(gen, "get_commune",
                            lambda _id: dict(COMMUNE, tampon_numerique_url=None))

        pdf = gen.generer_document("dossier-1")
        assert pdf.startswith(b"%PDF-")

    def test_le_document_tamponne_sort_sans_mention_de_brouillon(self, mairie, monkeypatch):
        # Décision du 2026-09-26 : la confirmation de l'administrateur, qui est
        # journalisée, suffit. Un acte tamponné est un acte délivré.
        _avec_saisie(monkeypatch, SAISIE_CONSULTANT)
        valeurs, _ = gen.resoudre_template(DOSSIER, COMMUNE, SAISIE_CONSULTANT, False)
        html = gen._rendre_html(valeurs, False, "S-1", gen.MODELES["extrait_naissance"],
                                tampon=gen.tampon_de_la_commune(COMMUNE))
        assert "BROUILLON OFFICIEL" not in html

    def test_une_commune_sans_tampon_sort_un_brouillon_assume(self, mairie, monkeypatch):
        # Le cas le plus fréquent aujourd'hui : aucune commune n'a encore
        # déposé son tampon. Ces actes-là doivent rester reconnaissables comme
        # des brouillons, sinon on met en circulation des documents qui ont
        # l'air officiels sans que personne ne les ait autorisés.
        _avec_saisie(monkeypatch, SAISIE_CONSULTANT)
        commune = dict(COMMUNE, tampon_numerique_url=None)
        valeurs, _ = gen.resoudre_template(DOSSIER, commune, SAISIE_CONSULTANT, False)
        html = gen._rendre_html(valeurs, False, "S-1", gen.MODELES["extrait_naissance"],
                                tampon=gen.tampon_de_la_commune(commune))
        assert "BROUILLON OFFICIEL" in html

    def test_un_numero_d_acte_court_du_registre_est_accepte(self, mairie, monkeypatch):
        # Corrigé le 2026-09-26 : la règle exigeait 19 chiffres exactement, un
        # chiffre estimé au comptage des cases du formulaire. Un registre qui
        # inscrit « 412 » voyait sa génération refusée.
        _avec_saisie(monkeypatch, dict(SAISIE_CONSULTANT, numeroActe="412"))
        assert gen.generer_document("dossier-1").startswith(b"%PDF-")

    def test_un_numero_d_acte_qui_n_en_est_pas_un_reste_refuse(self, mairie, monkeypatch):
        # La correction ne doit pas tout ouvrir : ce champ reste un numéro.
        _avec_saisie(monkeypatch, dict(SAISIE_CONSULTANT, numeroActe="quatre cent douze"))
        with pytest.raises(gen.ErreurGenerationDocument):
            gen.generer_document("dossier-1")

    def test_un_numero_interminable_est_refuse(self, mairie, monkeypatch):
        # La borne haute (19 cases comptées sur le formulaire) est ce qui
        # rattrape un collage malheureux — un NIN, un numéro de téléphone, une
        # ligne entière recopiée dans la case du numéro d'acte.
        _avec_saisie(monkeypatch, dict(SAISIE_CONSULTANT, numeroActe="1" * 25))
        with pytest.raises(gen.ErreurGenerationDocument):
            gen.generer_document("dossier-1")
