import pytest

from temps_reel import sessions as module_sessions
from temps_reel.sessions import ErreurPersistance, MagasinSessions, SessionEtrangere


class FaussePersistance:
    def __init__(self):
        self.lignes: dict[str, dict] = {}
        self.panne = None

    def _verifier(self):
        if self.panne:
            raise self.panne

    def lignes_par_cle(self, cle):
        self._verifier()
        return [dict(l) for l in self.lignes.values() if l["cle_client"] == cle]

    def active_du_citoyen(self, citoyen_id):
        self._verifier()
        return next((dict(l) for l in self.lignes.values() if l["citoyen_id"] == citoyen_id and l["statut"] == "active"), None)

    def active_par_dossier(self, dossier_id):
        self._verifier()
        return next((dict(l) for l in self.lignes.values() if l.get("dossier_id") == dossier_id and l["statut"] == "active"), None)

    def inserer(self, ligne):
        self._verifier()
        self.lignes[ligne["id"]] = dict(ligne)

    def mettre_a_jour(self, session_id, ligne):
        self._verifier()
        self.lignes[session_id] = {**self.lignes.get(session_id, {}), **ligne, "id": session_id}


@pytest.fixture
def persistance():
    return FaussePersistance()


@pytest.fixture
def magasin(persistance):
    return MagasinSessions(persistance)


async def test_nouvelle_session_puis_reprise_par_cle(magasin, persistance):
    etat, reprise = await magasin.ouvrir(citoyen_id="c1", commune_profil="Dakar", cle_client="cle-app")
    assert reprise is False and etat["cle_client"] == "cle-app"
    etat["mode"] = "administratif"
    await magasin.enregistrer(etat)

    # Redémarrage serveur : nouveau magasin, même base.
    autre = MagasinSessions(persistance)
    repris, reprise = await autre.ouvrir(citoyen_id="c1", commune_profil="Dakar", cle_client="cle-app")
    assert reprise is True and repris["id"] == etat["id"] and repris["mode"] == "administratif"


async def test_cle_d_un_autre_citoyen_refusee(magasin):
    await magasin.ouvrir(citoyen_id="victime", commune_profil="Dakar", cle_client="cle-partagee")
    with pytest.raises(SessionEtrangere):
        await magasin.ouvrir(citoyen_id="attaquant", commune_profil="Dakar", cle_client="cle-partagee")


async def test_cle_d_un_autre_citoyen_refusee_meme_apres_redemarrage(persistance):
    premier = MagasinSessions(persistance)
    await premier.ouvrir(citoyen_id="victime", commune_profil="Dakar", cle_client="cle-partagee")
    second = MagasinSessions(persistance)
    with pytest.raises(SessionEtrangere):
        await second.ouvrir(citoyen_id="attaquant", commune_profil="Dakar", cle_client="cle-partagee")


async def test_session_close_puis_nouvelle_avec_la_meme_cle(magasin):
    etat, _ = await magasin.ouvrir(citoyen_id="c1", commune_profil="Dakar", cle_client="cle-app")
    etat["phase"] = "termine"
    await magasin.clore(etat, "demarche_envoyee")
    suivante, reprise = await magasin.ouvrir(citoyen_id="c1", commune_profil="Dakar", cle_client="cle-app")
    assert reprise is False and suivante["id"] != etat["id"]
    assert suivante["mode"] == "information" and suivante["phase"] == "collecte"


async def test_nouvelle_conversation_clot_l_active(magasin, persistance):
    etat, _ = await magasin.ouvrir(citoyen_id="c1", commune_profil="Dakar")
    nouvelle, reprise = await magasin.ouvrir(citoyen_id="c1", commune_profil="Dakar", nouvelle=True)
    assert reprise is False and nouvelle["id"] != etat["id"]
    assert persistance.lignes[etat["id"]]["statut"] == "close"


async def test_sans_cle_reprend_la_session_active_du_citoyen(magasin):
    etat, _ = await magasin.ouvrir(citoyen_id="c1", commune_profil="Dakar")
    repris, reprise = await magasin.ouvrir(citoyen_id="c1", commune_profil="Dakar")
    assert reprise is True and repris["id"] == etat["id"]


async def test_panne_base_refuse_plutot_que_d_autoriser(magasin, persistance):
    persistance.panne = TimeoutError("base injoignable")
    with pytest.raises(ErreurPersistance):
        await magasin.ouvrir(citoyen_id="c1", commune_profil="Dakar", cle_client="cle")


async def test_migration_absente_mode_memoire(magasin, persistance):
    persistance.panne = Exception("Could not find the table 'public.dialogue_sessions' (PGRST205)")
    etat, reprise = await magasin.ouvrir(citoyen_id="c1", commune_profil="Dakar", cle_client="cle")
    assert reprise is False and magasin.persistance_disponible is False
    with pytest.raises(SessionEtrangere):
        await magasin.ouvrir(citoyen_id="c2", commune_profil="Dakar", cle_client="cle")


async def test_pour_dossier(magasin, persistance):
    etat, _ = await magasin.ouvrir(citoyen_id="c1", commune_profil="Dakar")
    etat["dossier_id"] = "d-1"
    await magasin.enregistrer(etat)
    assert (await magasin.pour_dossier("d-1"))["id"] == etat["id"]
    assert await MagasinSessions(persistance).pour_dossier("d-1") is not None
    assert await magasin.pour_dossier("inconnu") is None


def test_instance_globale_disponible():
    assert isinstance(module_sessions.magasin, MagasinSessions)
