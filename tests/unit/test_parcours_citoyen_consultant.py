"""
Le va-et-vient citoyen <-> consultant, bout en bout, par les endpoints réels.

CE QUI MANQUAIT

`test_parcours_naissance_complet.py` suit la FABRICATION du document : slots ->
résolution -> XSD -> PDF tamponné. `test_regles_statut.py` vérifie la machine à
états. Mais personne ne jouait la PARTIE À DEUX : le citoyen dépose, le
consultant ouvre, saisit le registre, génère, envoie ; le citoyen refuse ; le
consultant corrige, régénère, renvoie ; le citoyen valide. Chaque pièce passait
ses tests, et c'est l'enchaînement qui était cassé (cf. le test du formulaire de
l'acte plus bas).

COMMENT

Une mairie en mémoire (`Mairie`) remplace Supabase et son stockage, et
`document_generator` tourne POUR DE VRAI dessus : weasyprint produit un PDF,
le tampon y est posé, la validation XSD s'applique. Les requêtes passent par
`TestClient`, donc par les dépendances d'authentification, les contrôles de
commune et `services/regles_statut.py` — rien n'est court-circuité entre le
clic et la base.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import dialogue_engine
import document_generator as gen
import main
from services import acces, corrections, evenements, notes

CITOYEN = {"id": "citoyen-1", "email": "awa@exemple.sn"}
AUTRE_CITOYEN = {"id": "citoyen-2", "email": "ndiaye@exemple.sn"}
CONSULTANT = {"id": "agent-1", "email": "agent@mairie.sn", "commune": "Ross-Béthio"}
CONSULTANT_AILLEURS = {"id": "agent-2", "email": "autre@mairie.sn", "commune": "Tambacounda"}

TAMPON = b"\x89PNG\r\n\x1a\n" + b"tampon-de-la-commune" * 4

# Ce que le dialogue laisse derrière lui (même jeu que le parcours naissance).
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

# Ce que le consultant saisit à la main, et nulle part ailleurs. Deux
# formulaires distincts le portent, et c'est exprès : les noms et prénoms se
# lisent sur le CERTIFICAT photographié (le dialogue ne connaît que
# « Ibrahima Diallo » d'un bloc), le reste sur le REGISTRE papier.
SAISIE_CONSULTANT = {
    # Formulaire de la pièce (type_document = "certificat_naissance").
    "prenomEnfant": "Ibrahima",
    "nomFamilleEnfant": "Diallo",
    "prenomMere": "Aissatou",
    "nomFamilleMere": "Ba",
    # Formulaire de l'acte (document_id NULL).
    "numeroActe": "412",
    "anneeRegistreLettres": "deux mille vingt-six",
    "anneeRegistreChiffres": "2026",
    "numeroRegistreLettres": "quatre cent douze",
    "numeroRegistreChiffres": "412",
    "officierEtatCivil": "Mamadou Sow",
}


class Mairie:
    """Base + stockage en mémoire, aux signatures de `dossiers_repo`."""

    def __init__(self):
        self.commune = {
            "id": "commune-1", "nom": "Ross-Béthio", "region": "Saint-Louis",
            "departement": "Dagana", "arrondissement": "Rosso-Sénégal",
            "tampon_numerique_url": "commune-1/tampon.png",
        }
        self.dossier = {
            "id": "dossier-1", "citoyen_id": CITOYEN["id"], "commune_id": "commune-1",
            "type_demarche": "extrait_naissance", "cas_legal": "dans_les_delais",
            "statut": "recu", "numero_suivi": "SM-2026-000452", "slots": dict(SLOTS),
            "nb_iterations_correction": 0,
        }
        self.pieces = [{
            "id": "piece-1", "dossier_id": "dossier-1", "type": "certificat_naissance",
            "fichier_url": "dossier-1/certificat.jpg",
        }]
        self.formulaires: dict[str, dict] = {}
        self.documents_generes: list[dict] = []
        self.remarques: list[dict] = []
        self.evenements: list[dict] = []
        self.pdfs: dict[str, bytes] = {}

    # --- dossier ---
    def get_dossier(self, dossier_id):
        return dict(self.dossier) if dossier_id == self.dossier["id"] else None

    def update_dossier(self, dossier_id, **champs):
        if dossier_id != self.dossier["id"]:
            return False
        self.dossier.update(champs)
        return True

    def resoudre_commune_id(self, nom):
        return self.commune["id"] if nom == self.commune["nom"] else None

    def list_dossiers_par_commune(self, commune_id):
        return [dict(self.dossier)] if commune_id == self.commune["id"] else []

    def list_dossiers_par_citoyen(self, citoyen_id):
        return [dict(self.dossier)] if citoyen_id == self.dossier["citoyen_id"] else []

    def get_commune(self, commune_id):
        return dict(self.commune) if commune_id == self.commune["id"] else None

    # --- pièces et formulaires ---
    def list_documents(self, dossier_id):
        return [dict(p) for p in self.pieces if p["dossier_id"] == dossier_id]

    def list_document_formulaires(self, dossier_id):
        return [dict(f) for f in self.formulaires.values() if f["dossier_id"] == dossier_id]

    def _creer_formulaire(self, dossier_id, document_id, type_document, champs):
        identifiant = f"form-{len(self.formulaires) + 1}"
        formulaire = {
            "id": identifiant, "dossier_id": dossier_id, "document_id": document_id,
            "type_document": type_document, "champs": champs,
            "statut": "rempli" if champs and all(c["valeur"] is not None for c in champs) else "a_remplir",
        }
        self.formulaires[identifiant] = formulaire
        return dict(formulaire)

    def get_or_create_document_formulaire(self, dossier_id, document, slots):
        for formulaire in self.formulaires.values():
            if formulaire["document_id"] == document["id"]:
                return dict(formulaire)
        return self._creer_formulaire(
            dossier_id, document["id"], document["type"],
            dialogue_engine.construire_champs_formulaire(document["type"], slots),
        )

    def get_or_create_formulaire_acte(self, dossier_id):
        from dossiers_repo import type_document_acte

        type_document = type_document_acte(self.dossier.get("type_demarche"))
        if type_document is None:
            return None
        for formulaire in self.formulaires.values():
            if formulaire["dossier_id"] == dossier_id and formulaire["document_id"] is None:
                return dict(formulaire)
        return self._creer_formulaire(
            dossier_id, None, type_document,
            dialogue_engine.construire_champs_formulaire(type_document, {}),
        )

    def get_document_formulaire(self, form_id):
        formulaire = self.formulaires.get(form_id)
        return dict(formulaire) if formulaire else None

    def update_champ_formulaire(self, formulaire, nom_champ, valeur=None, verifie=None):
        reel = self.formulaires[formulaire["id"]]
        champ = next((c for c in reel["champs"] if c["nom"] == nom_champ), None)
        if champ is None:
            return None
        if valeur is not None:
            champ["valeur"] = valeur
            champ["source"] = "manuel"
        if verifie is not None:
            champ["verifie_par_consultant"] = verifie
        remplis = all(c.get("valeur") is not None for c in reel["champs"])
        verifies = all(c.get("verifie_par_consultant") for c in reel["champs"])
        reel["statut"] = "verifie" if (remplis and verifies) else ("rempli" if remplis else "a_remplir")
        return dict(reel)

    # --- documents générés ---
    def get_next_version(self, dossier_id):
        return len([d for d in self.documents_generes if d["dossier_id"] == dossier_id]) + 1

    def upload_document_genere(self, dossier_id, version, pdf_bytes):
        chemin = f"{dossier_id}/v{version}.pdf"
        self.pdfs[chemin] = pdf_bytes
        return chemin

    def create_document_genere(self, dossier_id, template_utilise, version, contenu_url):
        ligne = {
            "id": f"dg-{version}", "dossier_id": dossier_id, "template_utilise": template_utilise,
            "version": version, "contenu_url": contenu_url, "statut": "genere",
        }
        self.documents_generes.append(ligne)
        return dict(ligne)

    def list_documents_generes(self, dossier_id):
        lignes = [d for d in self.documents_generes if d["dossier_id"] == dossier_id]
        return [dict(d) for d in sorted(lignes, key=lambda d: d["version"], reverse=True)]

    def update_document_genere_statut(self, document_genere_id, statut):
        for ligne in self.documents_generes:
            if ligne["id"] == document_genere_id:
                ligne["statut"] = statut
                return dict(ligne)
        return None

    def create_remarque(self, dossier_id, texte, source, document_genere_id=None, champ_concerne=None):
        remarque = {
            "id": f"r-{len(self.remarques) + 1}", "dossier_id": dossier_id, "texte": texte,
            "source": source, "document_genere_id": document_genere_id, "champ_concerne": champ_concerne,
        }
        self.remarques.append(remarque)
        return dict(remarque)

    @property
    def statut(self):
        return self.dossier["statut"]

    @property
    def statuts_traverses(self):
        return [e["statut_apres"] for e in self.evenements]


@pytest.fixture
def mairie(monkeypatch):
    m = Mairie()

    # `main` importe les fonctions de dépôt par leur nom : c'est là qu'il faut
    # les remplacer, pas dans `dossiers_repo`.
    for module in (main, gen, acces, corrections, evenements):
        for nom, remplacement in (
            ("get_dossier", m.get_dossier),
            ("update_dossier", m.update_dossier),
            ("resoudre_commune_id", m.resoudre_commune_id),
            ("get_commune", m.get_commune),
            ("list_dossiers_par_commune", m.list_dossiers_par_commune),
            ("list_dossiers_par_citoyen", m.list_dossiers_par_citoyen),
            ("list_documents", m.list_documents),
            ("list_document_formulaires", m.list_document_formulaires),
            ("get_or_create_document_formulaire", m.get_or_create_document_formulaire),
            ("get_or_create_formulaire_acte", m.get_or_create_formulaire_acte),
            ("get_document_formulaire", m.get_document_formulaire),
            ("update_champ_formulaire", m.update_champ_formulaire),
            ("get_next_version_documents_generes", m.get_next_version),
            ("upload_document_genere", m.upload_document_genere),
            ("create_document_genere", m.create_document_genere),
            ("list_documents_generes", m.list_documents_generes),
            ("update_document_genere_statut", m.update_document_genere_statut),
            ("create_remarque", m.create_remarque),
        ):
            if hasattr(module, nom):
                monkeypatch.setattr(module, nom, remplacement)

    monkeypatch.setattr(main, "get_document_signed_url", lambda chemin, **_: f"https://signe/{chemin}")
    monkeypatch.setattr(main, "get_document_genere_signed_url", lambda chemin, **_: f"https://signe/{chemin}")
    monkeypatch.setattr(gen, "telecharger_tampon", lambda _c: TAMPON)
    monkeypatch.setattr(gen, "create_cas_particulier", lambda *a, **k: None)
    monkeypatch.setattr(main, "list_cas_particuliers", lambda _id: [])

    # Historique : enregistré en mémoire au lieu d'être inséré en base.
    async def noter(dossier_id, type_evenement, libelle, **kw):
        ligne = {"dossier_id": dossier_id, "type": type_evenement, "libelle": libelle, **kw}
        m.evenements.append(ligne)
        return ligne

    monkeypatch.setattr(evenements, "ajouter_evenement", noter)

    async def sans_effet(*a, **k):
        return None

    monkeypatch.setattr(main.audit, "journaliser", sans_effet)

    async def remarques_du_dossier(dossier_id):
        return [dict(r) for r in reversed(m.remarques) if r["dossier_id"] == dossier_id]

    monkeypatch.setattr(notes, "lister_remarques", remarques_du_dossier)

    async def evenements_du_dossier(dossier_id):
        return [dict(e) for e in m.evenements if e["dossier_id"] == dossier_id]

    monkeypatch.setattr(notes, "lister_evenements", evenements_du_dossier)

    return m


@pytest.fixture
def citoyen(mairie):
    main.app.dependency_overrides[main.get_current_user] = lambda: CITOYEN
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


@pytest.fixture
def agent(mairie):
    main.app.dependency_overrides[main.get_current_consultant] = lambda: CONSULTANT
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def _saisir(agent, champs=SAISIE_CONSULTANT):
    """
    Le consultant remplit ce qu'il a sous les yeux, chaque champ dans le
    formulaire qui le porte. Si un champ n'appartient à AUCUN formulaire
    renvoyé, c'est qu'il n'y a nulle part où le saisir : le test le dit, au
    lieu de laisser la génération échouer plus loin sans expliquer pourquoi.
    """
    formulaires = agent.get("/consultant/dossiers/dossier-1/formulaires").json()["formulaires"]
    for nom, valeur in champs.items():
        porteur = next((f for f in formulaires if any(c["nom"] == nom for c in f["champs"])), None)
        assert porteur is not None, f"« {nom} » n'a de place dans aucun formulaire du dossier"
        reponse = agent.patch(
            f"/consultant/dossiers/dossier-1/formulaires/{porteur['id']}",
            json={"nom": nom, "valeur": valeur},
        )
        assert reponse.status_code == 200, f"{nom} : {reponse.text}"
    return formulaires


def _formulaire_acte(agent):
    formulaires = agent.get("/consultant/dossiers/dossier-1/formulaires").json()["formulaires"]
    acte = next((f for f in formulaires if f["document_id"] is None), None)
    assert acte is not None, (
        "aucun formulaire d'acte renvoyé : le consultant n'a nulle part où saisir le registre"
    )
    return acte


class TestLeConsultantPeutSaisirLeRegistre:
    """
    LE TROU TROUVÉ EN JOUANT LE PARCOURS À DEUX (novembre 2026).

    Le formulaire de l'acte — numéro et année du registre, mentions en toutes
    lettres, officier signataire — est créé avec `document_id = NULL` : il ne
    correspond à aucune PIÈCE photographiée, puisqu'il porte ce que le
    consultant lit sur le registre papier.

    Or `GET /consultant/dossiers/{id}/formulaires` ne construisait sa liste
    qu'en parcourant les pièces uploadées. Le formulaire de l'acte n'était donc
    JAMAIS renvoyé, et l'écran consultant — qui sélectionne un formulaire par
    `document_id` — ne pouvait pas l'afficher. Résultat : les champs
    obligatoires du document restaient vides, la génération échouait en 422 sur
    `numeroActe` et `officierEtatCivil`, et aucun écran ne permettait de les
    remplir. Le parcours s'arrêtait là, sur tous les dossiers.
    """

    def test_le_formulaire_de_l_acte_est_renvoye(self, agent):
        formulaires = agent.get("/consultant/dossiers/dossier-1/formulaires").json()["formulaires"]
        actes = [f for f in formulaires if f["document_id"] is None]
        assert len(actes) == 1, "le formulaire de l'acte doit être renvoyé, une seule fois"
        noms = {c["nom"] for c in actes[0]["champs"]}
        assert {"numeroActe", "officierEtatCivil"} <= noms

    def test_les_formulaires_des_pieces_restent_la(self, agent):
        formulaires = agent.get("/consultant/dossiers/dossier-1/formulaires").json()["formulaires"]
        assert any(f["document_id"] == "piece-1" for f in formulaires)

    def test_il_n_est_pas_dupplique_a_chaque_appel(self, agent, mairie):
        agent.get("/consultant/dossiers/dossier-1/formulaires")
        agent.get("/consultant/dossiers/dossier-1/formulaires")
        actes = [f for f in mairie.formulaires.values() if f["document_id"] is None]
        assert len(actes) == 1

    def test_un_dossier_sans_piece_a_quand_meme_son_formulaire(self, agent, mairie):
        # Le cas le plus fréquent d'une naissance déclarée dans les délais :
        # aucune pièce à photographier, tout vient du dialogue et du registre.
        mairie.pieces.clear()
        formulaires = agent.get("/consultant/dossiers/dossier-1/formulaires").json()["formulaires"]
        assert len(formulaires) == 1 and formulaires[0]["document_id"] is None

    def test_les_champs_saisis_arrivent_bien_a_la_generation(self, agent, mairie):
        _saisir(agent)
        reponse = agent.post("/consultant/dossiers/dossier-1/generer")
        assert reponse.status_code == 200, reponse.text


class TestLeParcoursEntier:
    def test_du_depot_a_la_finalisation(self, agent, citoyen, mairie):
        # 1. Le dossier déposé apparaît dans la liste de SA commune.
        liste = agent.get("/consultant/dossiers").json()["dossiers"]
        assert [d["id"] for d in liste] == ["dossier-1"]

        # 2. L'ouvrir vaut prise en charge.
        detail = agent.get("/consultant/dossiers/dossier-1")
        assert detail.status_code == 200
        assert detail.json()["dossier"]["statut"] == "en_traitement"
        assert detail.json()["documents"][0]["url_signee"].startswith("https://signe/")

        # 3. Le certificat et le registre papier, saisis à la main.
        _saisir(agent)

        # 4. Génération : un vrai PDF, tamponné.
        generation = agent.post("/consultant/dossiers/dossier-1/generer").json()
        assert generation["version"] == 1
        assert generation["tampon"] == {"appose": True, "enregistre": True, "commune": "Ross-Béthio"}
        assert mairie.pdfs["dossier-1/v1.pdf"].startswith(b"%PDF-")
        assert mairie.statut == "genere"

        # 5. Tant que le consultant n'a pas envoyé, le citoyen ne voit rien.
        avant_envoi = citoyen.get("/mes-dossiers/dossier-1").json()
        assert avant_envoi["document_genere"] is None

        # 6. Envoi au citoyen.
        assert agent.post("/consultant/dossiers/dossier-1/valider").status_code == 200
        assert mairie.statut == "en_attente_validation_citoyen"

        # 7. Le citoyen reçoit le document, avec son lien signé.
        chez_le_citoyen = citoyen.get("/mes-dossiers/dossier-1").json()
        assert chez_le_citoyen["document_genere"]["version"] == 1
        assert chez_le_citoyen["document_genere"]["url_signee"] == "https://signe/dossier-1/v1.pdf"

        # 8. Il signale une erreur, sur un champ précis.
        refus = citoyen.post(
            "/mes-dossiers/dossier-1/demander-corrections",
            json={"texte": "Le prénom de ma mère est mal écrit.", "champ_concerne": "prenomMere"},
        )
        assert refus.status_code == 200
        assert refus.json()["bloque"] is False
        assert mairie.statut == "corrections_demandees"
        # La version refusée le dit : sans cela, l'historique du consultant la
        # montrait encore « Envoyée au citoyen ».
        assert mairie.documents_generes[0]["statut"] == "corrections_demandees"

        # 9. Le consultant voit CE QU'il a signalé.
        remarques = agent.get("/consultant/dossiers/dossier-1/remarques").json()["remarques"]
        assert remarques[0]["champ_concerne"] == "prenomMere"
        assert remarques[0]["source"] == "citoyen"

        # 10. Il reprend le dossier, corrige, régénère.
        assert agent.get("/consultant/dossiers/dossier-1").json()["dossier"]["statut"] == "en_traitement"
        _saisir(agent, {"prenomMere": "Aïssatou"})

        regeneration = agent.post("/consultant/dossiers/dossier-1/generer").json()
        assert regeneration["version"] == 2, "la correction doit produire une NOUVELLE version"
        assert agent.post("/consultant/dossiers/dossier-1/valider").status_code == 200

        # 11. Le citoyen reçoit la version 2, pas la 1.
        assert citoyen.get("/mes-dossiers/dossier-1").json()["document_genere"]["version"] == 2

        # 12. Il valide : dossier finalisé, document validé.
        final = citoyen.post("/mes-dossiers/dossier-1/valider")
        assert final.status_code == 200
        assert final.json()["dossier"]["statut"] == "finalise"
        assert final.json()["document_genere"]["statut"] == "valide"

        # 13. Le chemin suivi est bien celui du cycle de vie §3.1.
        assert mairie.statuts_traverses == [
            "en_traitement", "genere", "en_attente_validation_citoyen",
            "corrections_demandees", "en_traitement", "genere",
            "en_attente_validation_citoyen", "finalise",
        ]

    def test_le_dossier_finalise_est_verrouille(self, agent, citoyen, mairie):
        mairie.dossier["statut"] = "finalise"
        refus = agent.post("/consultant/dossiers/dossier-1/generer")
        assert refus.status_code == 409
        assert refus.json()["detail"]["code"] == "dossier_finalise"
        assert agent.patch(
            "/consultant/dossiers/dossier-1/formulaires/form-1", json={"nom": "x", "valeur": "y"}
        ).status_code == 409

    def test_le_consultant_n_agit_pas_pendant_que_le_citoyen_relit(self, agent, mairie):
        mairie.dossier["statut"] = "en_attente_validation_citoyen"
        refus = agent.post("/consultant/dossiers/dossier-1/generer")
        assert refus.status_code == 409
        assert refus.json()["detail"]["code"] == "document_chez_citoyen"

    def test_ouvrir_un_dossier_chez_le_citoyen_ne_le_reprend_pas(self, agent, mairie):
        # Sans quoi une simple consultation annulerait l'envoi au citoyen.
        mairie.dossier["statut"] = "en_attente_validation_citoyen"
        assert agent.get("/consultant/dossiers/dossier-1").json()["dossier"]["statut"] == (
            "en_attente_validation_citoyen"
        )


class TestLesTroisRefusBloquentLeDossier:
    def test_au_troisieme_refus_un_humain_reprend_la_main(self, agent, citoyen, mairie):
        _saisir(agent)
        for essai in (1, 2, 3):
            agent.post("/consultant/dossiers/dossier-1/generer")
            agent.post("/consultant/dossiers/dossier-1/valider")
            reponse = citoyen.post(
                "/mes-dossiers/dossier-1/demander-corrections",
                json={"texte": f"Toujours faux ({essai})."},
            )
            assert reponse.status_code == 200, reponse.text
            assert reponse.json()["bloque"] is (essai == 3)
            if essai < 3:
                agent.get("/consultant/dossiers/dossier-1")  # reprise

        assert mairie.statut == "bloque"
        assert mairie.dossier["motif_blocage"] == corrections.MOTIF_BLOCAGE
        # Et plus rien ne passe côté consultant.
        assert agent.post("/consultant/dossiers/dossier-1/generer").json()["detail"]["code"] == "dossier_bloque"


class TestChacunChezSoi:
    def test_un_autre_citoyen_ne_voit_pas_le_dossier(self, mairie):
        main.app.dependency_overrides[main.get_current_user] = lambda: AUTRE_CITOYEN
        try:
            assert TestClient(main.app).get("/mes-dossiers/dossier-1").status_code == 403
        finally:
            main.app.dependency_overrides.clear()

    def test_un_consultant_d_une_autre_commune_est_refuse(self, mairie):
        main.app.dependency_overrides[main.get_current_consultant] = lambda: CONSULTANT_AILLEURS
        try:
            client = TestClient(main.app)
            assert client.get("/consultant/dossiers").json()["dossiers"] == []
            assert client.get("/consultant/dossiers/dossier-1").status_code == 403
            assert client.get("/consultant/dossiers/dossier-1/formulaires").status_code == 403
        finally:
            main.app.dependency_overrides.clear()

    def test_le_citoyen_ne_valide_pas_avant_d_avoir_recu(self, citoyen, mairie):
        mairie.dossier["statut"] = "genere"
        refus = citoyen.post("/mes-dossiers/dossier-1/valider")
        assert refus.status_code == 400
        assert "pas en attente de validation" in refus.json()["detail"]

    def test_le_citoyen_ne_demande_pas_de_correction_hors_delai(self, citoyen, mairie):
        mairie.dossier["statut"] = "en_traitement"
        refus = citoyen.post(
            "/mes-dossiers/dossier-1/demander-corrections", json={"texte": "C'est faux."}
        )
        assert refus.status_code == 400
        assert refus.json()["detail"]["code"] == "statut_inattendu"

    def test_une_remarque_vide_est_refusee(self, citoyen, mairie):
        mairie.dossier["statut"] = "en_attente_validation_citoyen"
        refus = citoyen.post("/mes-dossiers/dossier-1/demander-corrections", json={"texte": "   "})
        assert refus.status_code == 400
        assert refus.json()["detail"]["code"] == "remarque_vide"


class TestLAssistantDuConsultant:
    """
    « Analyser le dossier » : ce que l'assistant reçoit vraiment.

    Le modèle est distant, donc remplacé ici — ce qui est vérifié est ce qui
    lui est SOUMIS. C'est là que les erreurs se nichent : l'assistant avait
    déjà signalé des champs bien remplis comme manquants parce qu'il comparait
    deux nomenclatures (slots du dialogue / clés du XSD) sans le mapping.
    """

    @pytest.fixture
    def assistant(self, monkeypatch):
        envoye = {}

        async def faux_appel(_client, _headers, payload, **_kw):
            envoye["prompt"] = payload["messages"][-1]["content"]
            return {
                "resume": "Dossier conforme.", "incoherences": [], "champs_a_verifier": [],
                "completude": {"elements_manquants": []}, "suggestions_generales": [],
            }

        monkeypatch.setattr(main, "call_openrouter_structured", faux_appel)
        return envoye

    def test_le_formulaire_de_l_acte_fait_partie_du_contexte(self, agent, assistant):
        assert agent.post("/consultant/dossiers/dossier-1/analyser").status_code == 200
        assert "numeroActe" in assistant["prompt"]
        assert "officierEtatCivil" in assistant["prompt"]

    def test_les_champs_obligatoires_vides_sont_nommes_au_modele(self, agent, assistant):
        agent.post("/consultant/dossiers/dossier-1/analyser")
        apres = assistant["prompt"].split("actuellement vides dans la vue ci-dessus :")[1]
        assert "numeroActe" in apres, "un champ bloquant vide doit être annoncé comme tel"

    def test_une_fois_le_registre_saisi_plus_rien_n_est_bloquant(self, agent, assistant):
        _saisir(agent)
        agent.post("/consultant/dossiers/dossier-1/analyser")
        apres = assistant["prompt"].split("actuellement vides dans la vue ci-dessus :")[1]
        assert "aucun" in apres.split(".")[0]

    def test_les_valeurs_du_dialogue_arrivent_sous_leur_nom_de_document(self, agent, assistant):
        # Le citoyen a dit « Ross-Béthio » et « 2026-09-07» ; le document les
        # appelle lieuNaissance et dateNaissance. Sans cette vue résolue,
        # l'assistant les déclarait manquants.
        _saisir(agent)
        agent.post("/consultant/dossiers/dossier-1/analyser")
        resolues = assistant["prompt"].split("VALEURS RÉSOLUES")[1]
        assert '"lieuNaissance": "Ross-Béthio"' in resolues
        assert '"enfantPrenom": "Ibrahima"' in resolues or '"prenomEnfant": "Ibrahima"' in resolues

    def test_l_analyse_dit_si_l_ocr_a_tourne(self, agent, assistant):
        analyse = agent.post("/consultant/dossiers/dossier-1/analyser").json()
        assert analyse["ocr_disponible"] is False

    def test_analyser_reste_possible_sur_un_dossier_finalise(self, agent, assistant, mairie):
        # Lecture seule : un agent doit pouvoir relire l'analyse d'un dossier
        # clos sans pouvoir y toucher.
        mairie.dossier["statut"] = "finalise"
        assert agent.post("/consultant/dossiers/dossier-1/analyser").status_code == 200
