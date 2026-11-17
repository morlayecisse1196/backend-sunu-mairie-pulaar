import pytest

from temps_reel import moteur
from temps_reel.etat import nouvel_etat

DEFINITIONS = [
    {"nom_champ": "age_enfant", "type_valeur": "age", "question": "Quel âge a votre enfant ?", "ordre": 5, "regle_validation": None},
    {"nom_champ": "commune_naissance", "type_valeur": "texte", "question": "Dans quelle commune est-il né ?", "ordre": 10, "regle_validation": None},
    {"nom_champ": "nom_enfant", "type_valeur": "texte", "question": "Quel est le nom complet de votre enfant ?", "ordre": 30, "regle_validation": None},
    {"nom_champ": "nom_mere", "type_valeur": "texte", "question": "Quel est le nom complet de la maman ?", "ordre": 70, "regle_validation": None},
    {"nom_champ": "date_naissance_mere", "type_valeur": "date", "question": "Quelle est sa date de naissance ?", "ordre": 80, "regle_validation": "passee"},
]


def _slots_complets():
    return {
        "age_enfant": {"valeur": 7, "unite": "jours"},
        "commune_naissance": "Ross-Béthio",
        "nom_enfant": "Ibrahima Diallo",
        "date_naissance_enfant": "2026-09-07",
        "nom_declarant": "Modou Diallo",
        "nom_mere": "Aissatou Ba",
        "date_naissance_mere": "1998-03-12",
        "parents_maries": True,
    }


class Espion:
    def __init__(self):
        self.transitions = []
        self.evenements = []
        self.maj = []
        self.dossiers_crees = []
        self.analyse_information = {"reponse": "Il faut un certificat.", "propose_demarrer_demarche": True,
                                    "confirme_demarrage_demarche": False,
                                    "demarche_proposee": "Extrait de naissance"}
        self.analyse_correction = {"intention": "refuse_sans_precision", "champ": None, "nouvelle_valeur": None}
        self.resultat_collecte = {"reponse_fr": "Quel âge a votre enfant ?", "document_attendu": None, "phase_suivante": "collecte"}
        self.resultat_document = None
        self.demarches_demarrees = []
        self.prompts = []
        #: Ce que le moteur a dit au collecteur : « ce message porte-t-il
        #: quelque chose à lire ? » Un « oui » qui lance la démarche n'en
        #: porte rien, et l'interpréter faisait répondre « Je n'ai pas bien
        #: compris » à la première question.
        self.sans_interpreter = []
        #: Et : « si tu ne trouves rien, tais-toi ». Posé à la bascule et là
        #: seulement, parce que le citoyen n'avait pas encore de question
        #: devant lui — il ne peut donc pas y avoir mal répondu.
        self.echec_silencieux = []

    def deps(self):
        espion = self

        async def rechercher(question, commune):
            return [{"nom_demarche": "Extrait de naissance", "documents_requis": ["certificat"]}]

        async def completer_structure(messages, schema, **kwargs):
            espion.prompts.append(messages[-1]["content"])
            if kwargs.get("nom_schema") == "correction_relecture":
                return espion.analyse_correction
            return espion.analyse_information

        # `sans_interpreter` dit au collecteur qu'il n'y a rien à lire dans ce
        # message — un simple « oui » qui lance la démarche. L'espion le note
        # pour que les tests puissent le vérifier.
        async def tour_administratif(etat, message, sans_interpreter=False,
                                     echec_silencieux=False):
            espion.sans_interpreter.append(sans_interpreter)
            espion.echec_silencieux.append(echec_silencieux)
            return espion.resultat_collecte

        async def transition(dossier_id, statut, **kwargs):
            espion.transitions.append((dossier_id, statut, kwargs))
            return {"id": dossier_id, "statut": statut}

        async def evenement(*args, **kwargs):
            espion.evenements.append((args, kwargs))

        def creer_dossier(citoyen_id, type_demarche, slots, cas_legal, commune_id):
            espion.dossiers_crees.append((citoyen_id, commune_id))
            espion.demarches_demarrees.append(type_demarche)
            return {"id": "dossier-1", "statut": "en_cours"}

        return moteur.Dependances(
            rechercher=rechercher,
            completer_structure=completer_structure,
            tour_administratif=tour_administratif,
            transition=transition,
            evenement=evenement,
            document_recu=lambda etat: espion.resultat_document,
            definition_champs=lambda type_demarche, version=None: DEFINITIONS,
            creer_dossier=creer_dossier,
            resoudre_commune=lambda nom: "commune-1" if nom else None,
            maj_dossier=lambda dossier_id, **champs: espion.maj.append((dossier_id, champs)) or True,
            numero_suivi=lambda: "SM-2026-000452",
        )


@pytest.fixture
def espion():
    return Espion()


def _etat(**extra):
    etat = nouvel_etat(session_id="s-1", cle_client="k", citoyen_id="citoyen-1", commune_profil="Ross-Béthio")
    etat.update(extra)
    return etat


async def test_information_sans_bascule(espion, deux_demarches):
    etat = _etat()
    resultat = await moteur.traiter_message(etat, "Comment avoir un extrait ?", espion.deps())
    # La réponse du modèle, SUIVIE de la phrase fixe qui nomme la démarche.
    assert resultat.reponse_fr.startswith("Il faut un certificat.")
    assert etat["mode"] == "information"
    assert etat["dernier_tour_propose_demarche"] is True
    assert etat["demarche_proposee"] == "extrait_naissance"
    assert [h["role"] for h in etat["historique"]] == ["user", "assistant"]


async def test_bascule_confirmee_cree_le_dossier_et_enchaine_la_collecte(espion, deux_demarches):
    etat = _etat(dernier_tour_propose_demarche=True, demarche_proposee="extrait_naissance")
    espion.analyse_information = {"reponse": "", "propose_demarrer_demarche": False,
                                  "confirme_demarrage_demarche": True, "demarche_proposee": None}
    resultat = await moteur.traiter_message(etat, "Oui je veux commencer", espion.deps())
    assert etat["mode"] == "administratif" and etat["dossier_id"] == "dossier-1"
    assert espion.dossiers_crees == [("citoyen-1", "commune-1")]
    assert resultat.reponse_fr == "Quel âge a votre enfant ?"
    # Le message rejoué est le « oui » du citoyen. S'il ne porte rien, le
    # collecteur doit se taire, pas s'excuser : le citoyen n'avait pas encore
    # de question devant lui.
    assert espion.echec_silencieux == [True]
    # Étape 2.4 : la version de la démarche est figée au moment où le citoyen
    # s'engage. Sans elle, une publication en cours de dialogue changerait ses
    # questions — y compris après le récapitulatif qu'il vient de confirmer.
    assert etat["demarche_version"] is not None


async def test_collecte_signale_le_document_attendu(espion):
    etat = _etat(mode="administratif", dossier_id="dossier-1")
    espion.resultat_collecte = {"reponse_fr": "Envoyez la photo du certificat.", "document_attendu": "certificat_naissance", "phase_suivante": "collecte"}
    resultat = await moteur.traiter_message(etat, "7 jours", espion.deps())
    assert resultat.document_attendu == "certificat_naissance"
    assert etat["document_en_attente"] == "certificat_naissance"
    assert "certificat_naissance" in etat["documents_demandes"]


async def test_collecte_complete_impose_la_relecture(espion):
    etat = _etat(mode="administratif", dossier_id="dossier-1", slots=_slots_complets())
    espion.resultat_collecte = {"reponse_fr": None, "document_attendu": None, "phase_suivante": "complet"}
    resultat = await moteur.traiter_message(etat, "Oui nous sommes mariés", espion.deps())
    assert etat["phase"] == "relecture_en_cours"
    assert "Est-ce que tout est exact" in resultat.reponse_fr
    assert etat["cas_legal"] == "dans_les_delais"


async def test_une_demarche_sans_les_champs_de_la_naissance_va_jusqu_a_la_relecture(espion):
    # Régression : la relecture n'était déclenchée que si des champs propres à
    # l'extrait de naissance étaient remplis. La constatation de mariage et la
    # déclaration de décès n'en ont aucun : elles ne pouvaient jamais aboutir.
    etat = _etat(mode="administratif", dossier_id="dossier-1", type_demarche="constatation_mariage",
                 slots={"date_ceremonie": "2026-09-01", "nom_epoux": "Modou Diallo"})
    espion.resultat_collecte = {"reponse_fr": None, "document_attendu": None,
                                "phase_suivante": "complet", "manquants": []}
    resultat = await moteur.traiter_message(etat, "Oui", espion.deps())

    assert etat["phase"] == "relecture_en_cours"
    assert "Est-ce que tout est exact" in resultat.reponse_fr


async def test_un_champ_manquant_repose_la_question_au_lieu_de_tourner_en_rond(espion):
    # Le dialogue se croit fini alors qu'un champ obligatoire est vide. Sans
    # issue, l'agent répétait « je n'ai pas bien compris » indéfiniment.
    etat = _etat(mode="administratif", dossier_id="dossier-1", slots=_slots_complets())
    espion.resultat_collecte = {"reponse_fr": None, "document_attendu": None,
                                "phase_suivante": "complet", "manquants": ["nom_mere"]}
    resultat = await moteur.traiter_message(etat, "Oui", espion.deps())

    assert resultat.reponse_fr == "Quel est le nom complet de la maman ?"
    assert etat["phase"] == "collecte", "la collecte doit reprendre, pas s'arrêter"
    assert "pas bien compris" not in resultat.reponse_fr


async def test_relecture_oui_envoie_et_clot_la_session(espion):
    etat = _etat(mode="administratif", phase="relecture_en_cours", dossier_id="dossier-1", slots=_slots_complets())
    resultat = await moteur.traiter_message(etat, "Oui, c'est bon", espion.deps())
    assert resultat.session_a_clore is True
    assert etat["phase"] == "termine" and etat["numero_suivi"] == "SM-2026-000452"
    assert espion.transitions[0][1] == "recu"
    assert "0, 0, 0, 4, 5, 2" in resultat.reponse_fr
    assert resultat.dossier_mis_a_jour == {"dossier_id": "dossier-1", "statut": "recu", "numero_suivi": "SM-2026-000452"}


async def test_relecture_non_ne_confirme_jamais(espion):
    etat = _etat(mode="administratif", phase="relecture_en_cours", dossier_id="dossier-1", slots=_slots_complets())
    resultat = await moteur.traiter_message(etat, "Non, ce n'est pas correct", espion.deps())
    assert etat["phase"] == "relecture_en_cours"
    assert espion.transitions == []
    assert "Quelle information" in resultat.reponse_fr


async def test_correction_avec_valeur_appliquee_puis_relue(espion):
    etat = _etat(mode="administratif", phase="relecture_en_cours", dossier_id="dossier-1", slots=_slots_complets())
    espion.analyse_correction = {"intention": "corrige", "champ": "nom_mere", "nouvelle_valeur": "Awa Ba"}
    resultat = await moteur.traiter_message(etat, "Non, la maman s'appelle Awa Ba", espion.deps())
    assert etat["slots"]["nom_mere"] == "Awa Ba"
    assert resultat.reponse_fr.startswith("C'est corrigé.")
    assert "Awa Ba" in resultat.reponse_fr
    assert etat["nb_iterations_correction"] == 1 and etat["phase"] == "relecture_en_cours"


async def test_correction_sans_valeur_vide_le_champ_et_le_redemande(espion):
    etat = _etat(mode="administratif", phase="relecture_en_cours", dossier_id="dossier-1", slots=_slots_complets())
    espion.analyse_correction = {"intention": "corrige", "champ": "date_naissance_mere", "nouvelle_valeur": None}
    resultat = await moteur.traiter_message(etat, "La date de la maman est fausse", espion.deps())
    assert etat["slots"]["date_naissance_mere"] is None
    assert etat["phase"] == "collecte"
    assert resultat.reponse_fr.endswith("Quelle est sa date de naissance ?")


async def test_correction_invalide_explique_et_redemande(espion):
    etat = _etat(mode="administratif", phase="relecture_en_cours", dossier_id="dossier-1", slots=_slots_complets())
    espion.analyse_correction = {"intention": "corrige", "champ": "date_naissance_mere", "nouvelle_valeur": "2099-01-01"}
    resultat = await moteur.traiter_message(etat, "Elle est née en 2099", espion.deps())
    assert etat["slots"]["date_naissance_mere"] is None
    assert "futur" in resultat.reponse_fr


async def test_troisieme_correction_bloque_le_dossier(espion):
    etat = _etat(mode="administratif", phase="relecture_en_cours", dossier_id="dossier-1", slots=_slots_complets(), nb_iterations_correction=2)
    espion.analyse_correction = {"intention": "corrige", "champ": "nom_mere", "nouvelle_valeur": "Awa Ba"}
    resultat = await moteur.traiter_message(etat, "Non la maman c'est Awa Ba", espion.deps())
    assert resultat.session_a_clore is True and etat["phase"] == "bloque"
    dossier_id, statut, kwargs = espion.transitions[0]
    assert statut == "bloque" and kwargs["champs"]["motif_blocage"] == "relecture_rg7"


async def test_relance_apres_document_recu(espion):
    etat = _etat(mode="administratif", dossier_id="dossier-1", document_en_attente="cni_declarant_recto")
    espion.resultat_document = {"reponse_fr": "Merci, photo bien reçue. Retournez la carte.", "document_attendu": "cni_declarant_verso", "phase_suivante": "collecte"}
    resultat = await moteur.apres_document_recu(etat, espion.deps())
    assert resultat.document_attendu == "cni_declarant_verso"
    assert etat["document_en_attente"] == "cni_declarant_verso"


async def test_relance_apres_document_sans_nouveaute(espion):
    etat = _etat(mode="administratif", dossier_id="dossier-1")
    assert await moteur.apres_document_recu(etat, espion.deps()) is None


# ============================================================================
# Étape 5.2 — le dialogue mène plusieurs démarches
# ============================================================================

DEMARCHES = {
    "demarche_definitions": [
        {"type_demarche": "extrait_naissance", "libelle": "Extrait de naissance", "version": 3,
         "traitable": True, "mots_cles": ["extrait de naissance"], "champ_age": "age_enfant"},
        {"type_demarche": "constatation_mariage", "libelle": "Constatation de mariage", "version": 1,
         "traitable": True, "mots_cles": ["constatation de mariage", "mariage"], "champ_age": None},
    ],
    "demarche_champs": [
        {"type_demarche": "extrait_naissance", "nom_champ": "nom_enfant", "ordre": 10,
         "type_valeur": "texte", "question": "Le nom ?", "obligatoire": True},
        {"type_demarche": "constatation_mariage", "nom_champ": "prenoms_epoux", "ordre": 10,
         "type_valeur": "texte", "question": "Les prénoms du mari ?", "obligatoire": True},
    ],
}


@pytest.fixture
def deux_demarches(monkeypatch):
    from services import demarche as service_demarche

    def lire(nom, **filtres):
        return [l for l in DEMARCHES.get(nom, []) if all(l.get(c) == v for c, v in filtres.items())]

    monkeypatch.setattr(service_demarche, "_table", lire)
    service_demarche.vider_cache()


async def test_les_demarches_menables_sont_proposees_au_modele(espion, deux_demarches):
    # Sans cette liste, le modèle proposait de commencer n'importe quelle
    # démarche trouvée par la recherche documentaire.
    await moteur.traiter_message(_etat(), "Je veux constater mon mariage", espion.deps())
    assert "Constatation de mariage" in espion.prompts[0]
    assert "Extrait de naissance" in espion.prompts[0]


async def test_la_demarche_proposee_est_retenue_pour_le_tour_suivant(espion, deux_demarches):
    # Au tour suivant le citoyen dit « oui » : plus rien ne dirait de quelle
    # démarche il parlait.
    etat = _etat()
    espion.analyse_information = {"reponse": "On commence ?", "propose_demarrer_demarche": True,
                                  "confirme_demarrage_demarche": False,
                                  "demarche_proposee": "Constatation de mariage"}
    await moteur.traiter_message(etat, "Je veux constater mon mariage", espion.deps())
    assert etat["demarche_proposee"] == "constatation_mariage"


async def test_la_bascule_demarre_la_demarche_demandee(espion, deux_demarches):
    etat = _etat(dernier_tour_propose_demarche=True, demarche_proposee="constatation_mariage")
    espion.analyse_information = {"reponse": "", "propose_demarrer_demarche": False,
                                  "confirme_demarrage_demarche": True, "demarche_proposee": None}
    await moteur.traiter_message(etat, "Oui", espion.deps())
    assert etat["type_demarche"] == "constatation_mariage"
    assert espion.demarches_demarrees == ["constatation_mariage"]
    assert etat["demarche_version"] == 1


async def test_les_cases_a_remplir_sont_celles_de_cette_demarche(espion, deux_demarches):
    # Sinon le dossier de mariage porterait les champs de l'extrait de
    # naissance, préparés à l'ouverture de la session.
    etat = _etat(dernier_tour_propose_demarche=True, demarche_proposee="constatation_mariage")
    espion.analyse_information = {"reponse": "", "propose_demarrer_demarche": False,
                                  "confirme_demarrage_demarche": True, "demarche_proposee": None}
    await moteur.traiter_message(etat, "Oui", espion.deps())
    assert "prenoms_epoux" in etat["slots"] and "nom_enfant" not in etat["slots"]


async def test_sans_demarche_reconnue_on_ne_bascule_pas(espion, deux_demarches):
    # Avant, on démarrait l'extrait de naissance par défaut : un citoyen venu
    # déclarer un décès s'entendait demander l'âge de son enfant.
    etat = _etat(dernier_tour_propose_demarche=True, demarche_proposee=None)
    espion.analyse_information = {"reponse": "", "propose_demarrer_demarche": False,
                                  "confirme_demarrage_demarche": True, "demarche_proposee": None}
    await moteur.traiter_message(etat, "Oui", espion.deps())
    assert etat["mode"] == "information"
    assert espion.dossiers_crees == []


async def test_une_demarche_inventee_par_le_modele_n_est_pas_retenue(espion, deux_demarches):
    etat = _etat()
    espion.analyse_information = {"reponse": "On commence ?", "propose_demarrer_demarche": True,
                                  "confirme_demarrage_demarche": False,
                                  "demarche_proposee": "Passeport biométrique"}
    await moteur.traiter_message(etat, "Je veux un passeport", espion.deps())
    assert etat["demarche_proposee"] is None


# ============================================================================
# Les trois verrous de la bascule (correctifs demandés avant l'étape 5.6)
# ============================================================================

PHRASES = {
    "bascule_confirmation": {
        "cle": "bascule_confirmation",
        "francais": "Je vais vous aider pour : {demarche}. Voulez-vous que nous commencions maintenant ?",
        "pulaar": "Mi wallay ma e : {demarche}. Aɗa yiɗi en fuɗɗoo jooni?",
        "pulaar_valide": True,
    },
    "bascule_demarche_inconnue": {
        "cle": "bascule_demarche_inconnue",
        "francais": "Je n'ai pas compris quelle démarche. Je peux vous aider pour : {demarches}.",
        "pulaar": "Mi faamaani. Mi waawi wallude ma e : {demarches}.",
        "pulaar_valide": True,
    },
}


@pytest.fixture
def phrases_fixes(monkeypatch, deux_demarches):
    from services import demarche as service_demarche

    monkeypatch.setattr(service_demarche, "_phrases_systeme", lambda: PHRASES)
    service_demarche.vider_cache()


async def test_l_agent_nomme_la_demarche_avant_de_commencer(espion, phrases_fixes):
    # C'est le seul moment où le citoyen peut encore dire non — et il ne peut
    # pas le faire si personne ne lui dit de quoi il s'agit.
    etat = _etat()
    espion.analyse_information = {"reponse": "Voici les pièces.", "propose_demarrer_demarche": True,
                                  "confirme_demarrage_demarche": False,
                                  "demarche_proposee": "Constatation de mariage"}
    resultat = await moteur.traiter_message(etat, "Je veux constater mon mariage", espion.deps())
    assert "Constatation de mariage" in resultat.reponse_fr
    assert etat["demarche_proposee"] == "constatation_mariage"


async def test_la_phrase_qui_nomme_la_demarche_garde_son_pulaar_relu(espion, phrases_fixes):
    # Sinon elle repart au traducteur à chaque conversation, alors que c'est
    # la phrase la plus importante du mode information.
    etat = _etat()
    await moteur.traiter_message(etat, "Un extrait de naissance", espion.deps())
    resultat = await moteur.traiter_message(etat, "Un extrait de naissance", espion.deps())
    dite = [m for m in resultat.reponse.morceaux if m.origine == "systeme:bascule_confirmation"]
    assert dite and dite[0].pulaar_pret() == "Mi wallay ma e : Extrait de naissance. Aɗa yiɗi en fuɗɗoo jooni?"


async def test_un_pulaar_qui_a_perdu_le_trou_n_est_pas_dit(espion, phrases_fixes, monkeypatch):
    # Un relecteur peut avoir traduit ou supprimé {demarche} : la phrase
    # dirait alors « je vais vous aider pour : » sans rien nommer.
    from services import demarche as service_demarche
    sans_trou = {**PHRASES, "bascule_confirmation": {**PHRASES["bascule_confirmation"],
                                                     "pulaar": "Mi wallay ma. Aɗa yiɗi?"}}
    monkeypatch.setattr(service_demarche, "_phrases_systeme", lambda: sans_trou)
    service_demarche.vider_cache()
    etat = _etat()
    await moteur.traiter_message(etat, "Un extrait de naissance", espion.deps())
    resultat = await moteur.traiter_message(etat, "Un extrait de naissance", espion.deps())
    dite = [m for m in resultat.reponse.morceaux if m.origine == "systeme:bascule_confirmation"]
    assert dite and dite[0].pulaar_pret() is None


async def test_un_oui_flou_ne_cree_pas_de_dossier(espion, phrases_fixes):
    # Le modèle dit « il a confirmé » ; le code, lui, n'entend pas de oui.
    etat = _etat(dernier_tour_propose_demarche=True, demarche_proposee="constatation_mariage")
    espion.analyse_information = {"reponse": "", "propose_demarrer_demarche": False,
                                  "confirme_demarrage_demarche": True, "demarche_proposee": None}
    resultat = await moteur.traiter_message(etat, "euh, le mariage de ma sœur…", espion.deps())
    assert etat["mode"] == "information"
    assert espion.dossiers_crees == []
    # Et on redemande en nommant la démarche, au lieu de rester muet.
    assert "Constatation de mariage" in resultat.reponse_fr
    assert etat["demarche_proposee"] == "constatation_mariage"


async def test_un_non_clair_annule_la_proposition(espion, phrases_fixes):
    etat = _etat(dernier_tour_propose_demarche=True, demarche_proposee="constatation_mariage")
    espion.analyse_information = {"reponse": "D'accord.", "propose_demarrer_demarche": False,
                                  "confirme_demarrage_demarche": True, "demarche_proposee": None}
    await moteur.traiter_message(etat, "Non, ce n'est pas ça", espion.deps())
    assert etat["mode"] == "information"
    assert etat["dernier_tour_propose_demarche"] is False
    assert etat["demarche_proposee"] is None
    assert espion.dossiers_crees == []


async def test_un_oui_franc_bascule_bien(espion, phrases_fixes):
    # Le verrou ne doit pas empêcher la démarche de commencer quand elle doit.
    etat = _etat(dernier_tour_propose_demarche=True, demarche_proposee="constatation_mariage")
    espion.analyse_information = {"reponse": "", "propose_demarrer_demarche": False,
                                  "confirme_demarrage_demarche": True, "demarche_proposee": None}
    await moteur.traiter_message(etat, "Oui, allons-y", espion.deps())
    assert etat["mode"] == "administratif" and etat["type_demarche"] == "constatation_mariage"


async def test_une_demarche_inconnue_fait_lister_celles_qui_existent(espion, phrases_fixes):
    etat = _etat()
    espion.analyse_information = {"reponse": "Pour un passeport, allez à la police.",
                                  "propose_demarrer_demarche": True, "confirme_demarrage_demarche": False,
                                  "demarche_proposee": "Passeport biométrique"}
    resultat = await moteur.traiter_message(etat, "Je veux un passeport", espion.deps())
    assert "Extrait de naissance" in resultat.reponse_fr and "Constatation de mariage" in resultat.reponse_fr
    assert etat["dernier_tour_propose_demarche"] is False
    assert etat["demarche_proposee"] is None


async def test_un_oui_apres_une_demarche_inconnue_ne_bascule_pas(espion, phrases_fixes):
    etat = _etat()
    espion.analyse_information = {"reponse": "", "propose_demarrer_demarche": True,
                                  "confirme_demarrage_demarche": False,
                                  "demarche_proposee": "Passeport biométrique"}
    await moteur.traiter_message(etat, "Je veux un passeport", espion.deps())
    espion.analyse_information = {"reponse": "", "propose_demarrer_demarche": False,
                                  "confirme_demarrage_demarche": True, "demarche_proposee": None}
    await moteur.traiter_message(etat, "Oui", espion.deps())
    assert etat["mode"] == "information" and espion.dossiers_crees == []


async def test_un_oui_que_le_modele_ne_lit_pas_comme_un_accord_ne_bascule_pas(espion, phrases_fixes):
    # « Oui » peut répondre à autre chose que la proposition — « oui, c'est
    # bien mon quartier ». Les deux avis doivent concorder : le mot entendu
    # ET le sens compris. Dans le doute, on redemande ; on n'ouvre pas de
    # dossier au nom de quelqu'un.
    etat = _etat(dernier_tour_propose_demarche=True, demarche_proposee="constatation_mariage")
    espion.analyse_information = {"reponse": "", "propose_demarrer_demarche": False,
                                  "confirme_demarrage_demarche": False, "demarche_proposee": None}
    resultat = await moteur.traiter_message(etat, "Oui", espion.deps())
    assert etat["mode"] == "information" and espion.dossiers_crees == []
    assert "Constatation de mariage" in resultat.reponse_fr
