import json

import httpx
import pytest

from services import llm


def _reponse_contenu(contenu: str) -> dict:
    return {"choices": [{"message": {"content": contenu}}]}


@pytest.fixture
def transport(monkeypatch):
    """Installe un client httpx simulé ; `reponses` est une file consommée dans l'ordre."""
    etat = {"reponses": [], "appels": 0}

    def gerer(requete: httpx.Request) -> httpx.Response:
        etat["appels"] += 1
        statut, corps = etat["reponses"].pop(0)
        return httpx.Response(statut, json=corps)

    monkeypatch.setattr(llm.asyncio, "sleep", _sans_attente)
    llm.definir_client(httpx.AsyncClient(transport=httpx.MockTransport(gerer)))
    yield etat
    llm.definir_client(None)


async def _sans_attente(_secondes):
    return None


async def test_structure_rejoue_si_json_invalide(transport):
    transport["reponses"] = [(200, _reponse_contenu("{tronqué")), (200, _reponse_contenu(json.dumps({"ok": True})))]
    resultat = await llm.completer_structure([{"role": "user", "content": "x"}], {"type": "object"})
    assert resultat == {"ok": True}
    assert transport["appels"] == 2


async def test_rejeu_sur_erreur_transitoire_puis_succes(transport):
    transport["reponses"] = [(503, {}), (200, _reponse_contenu("bonjour"))]
    assert await llm.completer_texte([{"role": "user", "content": "x"}]) == "bonjour"
    assert transport["appels"] == 2


async def test_erreur_4xx_non_rejouee(transport):
    transport["reponses"] = [(401, {"error": "clé invalide"})]
    with pytest.raises(llm.ErreurLLM):
        await llm.completer_texte([{"role": "user", "content": "x"}])
    assert transport["appels"] == 1


async def test_structure_echec_definitif(transport):
    transport["reponses"] = [(200, _reponse_contenu("pas du json"))] * 3
    with pytest.raises(llm.ErreurLLM):
        await llm.completer_structure([{"role": "user", "content": "x"}], {"type": "object"}, rejeux_json=2)
