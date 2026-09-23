import pytest

from services import corrections


@pytest.fixture
def espion(monkeypatch):
    etat = {"remarques": [], "transitions": [], "documents": [{"id": "doc-1"}], "remarque_ok": True}

    monkeypatch.setattr(corrections, "list_documents_generes", lambda dossier_id: etat["documents"])

    def creer(dossier_id, texte, source, document_genere_id, champ_concerne):
        if not etat["remarque_ok"]:
            return None
        ligne = {"id": "r-1", "dossier_id": dossier_id, "texte": texte, "source": source,
                 "document_genere_id": document_genere_id, "champ_concerne": champ_concerne}
        etat["remarques"].append(ligne)
        return ligne

    monkeypatch.setattr(corrections, "create_remarque", creer)

    async def transition(dossier_id, statut, **kwargs):
        etat["transitions"].append((dossier_id, statut, kwargs))
        return {"id": dossier_id, "statut": statut}

    monkeypatch.setattr(corrections.evenements, "transition_statut", transition)
    return etat


def _dossier(iterations=0, statut="en_attente_validation_citoyen"):
    return {"id": "d-1", "statut": statut, "nb_iterations_correction": iterations}


async def test_premiere_correction(espion):
    issue = await corrections.enregistrer_demande(_dossier(), "Le nom du père est faux", citoyen_id="c-1", champ_concerne="prenomPere")
    assert issue["bloque"] is False and issue["iterations"] == 1
    assert espion["remarques"][0]["champ_concerne"] == "prenomPere"
    assert espion["remarques"][0]["document_genere_id"] == "doc-1"
    dossier_id, statut, kwargs = espion["transitions"][0]
    assert statut == "corrections_demandees" and kwargs["champs"]["nb_iterations_correction"] == 1
    assert "Le nom du père est faux" not in str(kwargs["details"])  # pas de texte personnel dans l'historique


async def test_troisieme_correction_bloque_avec_motif(espion):
    issue = await corrections.enregistrer_demande(_dossier(iterations=2), "Toujours faux", citoyen_id="c-1")
    assert issue["bloque"] is True
    _, statut, kwargs = espion["transitions"][0]
    assert statut == "bloque" and kwargs["champs"]["motif_blocage"] == "corrections_post_generation"


async def test_correction_par_la_voix_tracee(espion):
    await corrections.enregistrer_demande(_dossier(), "la date est fausse", citoyen_id="c-1", source_audio=True)
    assert espion["transitions"][0][2]["details"]["par_la_voix"] is True


@pytest.mark.parametrize("texte", ["", "   "])
async def test_remarque_vide_refusee(espion, texte):
    with pytest.raises(corrections.CorrectionImpossible) as exc:
        await corrections.enregistrer_demande(_dossier(), texte, citoyen_id="c-1")
    assert exc.value.code == "remarque_vide"


async def test_statut_inattendu_refuse(espion):
    with pytest.raises(corrections.CorrectionImpossible) as exc:
        await corrections.enregistrer_demande(_dossier(statut="en_traitement"), "faux", citoyen_id="c-1")
    assert exc.value.code == "statut_inattendu"
    assert espion["transitions"] == []


async def test_echec_d_enregistrement_de_la_remarque(espion):
    espion["remarque_ok"] = False
    with pytest.raises(corrections.CorrectionImpossible) as exc:
        await corrections.enregistrer_demande(_dossier(), "faux", citoyen_id="c-1")
    assert exc.value.code == "enregistrement_echoue"
    assert espion["transitions"] == []
