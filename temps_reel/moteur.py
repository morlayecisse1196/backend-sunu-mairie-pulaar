"""
Moteur de dialogue — UN tour de conversation, indépendant du transport.

Extrait de la boucle WebSocket historique de main.py (même comportement
métier : mode information → bascule confirmée → collecte champ par champ via
slot_controller → relecture RG7 → envoi / blocage), avec les corrections :

  * RG7 : « oui » détecté de manière déterministe AVEC la négation
    (temps_reel/intentions.py) ; une correction signalée est réellement
    appliquée (champ corrigé et revalidé, ou vidé puis redemandé).
  * Fin de démarche (envoyée ou bloquée) ⇒ `session_a_clore` : la session
    suivante repart en mode information au lieu de répondre indéfiniment
    « votre demande a déjà été envoyée ».
  * Le numéro de suivi est redit chiffre par chiffre (public analphabète).
  * Transitions de statut via services/evenements.py (historique,
    notifications, push temps réel).
  * `slot_controller` fait des appels Supabase SYNCHRONES à l'intérieur de
    coroutines : il est exécuté dans un thread avec sa propre boucle, pour ne
    jamais bloquer les autres citoyens connectés.

Toutes les dépendances externes passent par `Dependances` : le moteur est
testable sans réseau (tests/unit/test_moteur.py).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Optional

import slot_controller
from config import OPENROUTER_API_KEY
from dialogue_engine import construire_recapitulatif
from dossiers_repo import create_dossier, generer_numero_suivi, resoudre_commune_id, update_dossier
from prompts import SCHEMA_REPONSE_INFORMATION, SYSTEM_PROMPT_GENERATOR, build_generator_prompt
from services import demarche, evenements, llm, phrases, rag
from services.corrections import SEUIL_ITERATIONS_CORRECTION_BLOQUE as SEUIL_CORRECTIONS
from services.journal import obtenir_logger
from temps_reel.etat import ajouter_historique
from temps_reel.intentions import classer_confirmation, est_confirmation_seule
from temps_reel.prompts_dialogue import (
    SCHEMA_CORRECTION_RELECTURE,
    SYSTEM_PROMPT_CORRECTION_RELECTURE,
    construire_prompt_correction,
)

log = obtenir_logger("moteur")

TYPE_DEMARCHE_ADMINISTRATIVE = demarche.TYPE_DEMARCHE_PAR_DEFAUT
# Même seuil que les corrections demandées après génération (services/corrections.py) :
# une seule valeur de référence pour les deux boucles (avant et après envoi).
SEUIL_ITERATIONS_CORRECTION_BLOQUE = SEUIL_CORRECTIONS
SEUIL_RELANCES_RELECTURE = 3
HISTORIQUE_POUR_PROMPT = 7

MESSAGE_BLOCAGE = (
    "Je rencontre des difficultés à finaliser votre demande après plusieurs tentatives. "
    "Un agent de votre mairie va reprendre votre dossier directement — vous n'avez rien d'autre à faire pour l'instant."
)
MESSAGE_REPETER = "Excusez-moi, je n'ai pas bien compris. Pouvez-vous répéter, s'il vous plaît ?"


async def _tour_administratif_isole(etat: dict, message: str, sans_interpreter: bool = False,
                                    echec_silencieux: bool = False) -> dict:
    entetes = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    return await asyncio.to_thread(
        lambda: asyncio.run(
            slot_controller.traiter_tour_administratif(
                etat, message, entetes, sans_interpreter, echec_silencieux)))


@dataclass
class Dependances:
    """Points d'accès externes du moteur (remplaçables dans les tests)."""

    rechercher: Callable[..., Any] = rag.rechercher_demarches  # async
    completer_structure: Callable[..., Any] = llm.completer_structure  # async
    tour_administratif: Callable[..., Any] = _tour_administratif_isole  # async
    transition: Callable[..., Any] = evenements.transition_statut  # async
    evenement: Callable[..., Any] = evenements.ajouter_evenement  # async
    document_recu: Callable[..., Any] = slot_controller.verifier_document_recu_et_avancer  # sync
    definition_champs: Callable[..., Any] = slot_controller.charger_definition_demarche  # sync
    creer_dossier: Callable[..., Any] = create_dossier  # sync
    resoudre_commune: Callable[..., Any] = resoudre_commune_id  # sync
    maj_dossier: Callable[..., Any] = update_dossier  # sync
    numero_suivi: Callable[..., Any] = generer_numero_suivi  # sync
    valider_valeur: Callable[..., Any] = slot_controller.valider_valeur  # sync, pur


@dataclass
class ResultatTour:
    reponse_fr: str
    document_attendu: Optional[str] = None
    session_a_clore: bool = False
    dossier_mis_a_jour: Optional[dict] = None  # {"dossier_id", "statut", "numero_suivi"} — poussé au client
    #: Où en est la démarche : `{"faites", "total"}`, poussé au client pour la
    #: barre d'avancement. `None` = rien de nouveau à dire (mode information,
    #: relecture, démarche bloquée) : le client garde alors ce qu'il affichait.
    progression: Optional[dict] = None
    #: Les morceaux de la réponse, avec leur pulaar validé quand il existe
    #: (étape 3). `None` = rien de validé, le traducteur fait tout, comme avant.
    reponse: Optional[phrases.Reponse] = None


async def traiter_message(etat: dict, message: str, deps: Optional[Dependances] = None) -> ResultatTour:
    """Traite un message (déjà transcrit) du citoyen et fait avancer l'état en place."""
    deps = deps or Dependances()
    ajouter_historique(etat, "user", message)

    if etat.get("phase") in ("termine", "bloque"):
        # Garde-fou : une session terminée devrait déjà être close par l'appelant.
        resultat = ResultatTour(_message_fin(etat), session_a_clore=True)
    elif etat.get("mode") != "administratif":
        resultat_information = await _tour_information(etat, message, deps)
        if resultat_information is not None:
            return _conclure(etat, resultat_information)
        # Bascule confirmée : on rejoue le MÊME message, parce qu'il contient
        # souvent déjà la première réponse (« je veux un extrait pour mon fils
        # de sept jours »). Mais s'il n'est qu'un accord, il n'y a rien à y
        # lire, et l'interpréter faisait répondre « Je n'ai pas bien compris »
        # à la toute première question de la démarche.
        #
        # Deux choses, donc, et il faut les deux :
        #   `sans_interpreter`  — raccourci sur un accord reconnu : on
        #     n'appelle pas le modèle pour rien. Sa liste de mots est
        #     française, il ne reconnaît le pulaar qu'en particule nue.
        #   `echec_silencieux`  — filet pour tout le reste : si l'extracteur
        #     ne trouve rien dans le message rejoué, on pose simplement la
        #     question. Le citoyen n'avait pas encore de question devant lui :
        #     il ne peut pas y avoir « mal répondu ».
        #
        # Le second rend le premier inoffensif. Sans lui, « Eyyi mbiɗo yiɗi
        # ɗe » — un oui pulaar ordinaire — valait au citoyen « Je n'ai pas
        # bien compris » et un pas de plus vers l'abandon du champ.
        resultat = await _tour_collecte(
            etat, message, deps,
            sans_interpreter=est_confirmation_seule(message),
            echec_silencieux=True)
    elif etat.get("phase") == "relecture_en_cours":
        resultat = await _tour_relecture(etat, message, deps)
    else:
        resultat = await _tour_collecte(etat, message, deps)
    return _conclure(etat, resultat)


async def apres_document_recu(etat: dict, deps: Optional[Dependances] = None) -> Optional[ResultatTour]:
    """
    Relance poussée après l'upload réel d'une pièce (canal REST) : confirme la
    réception et enchaîne sur l'étape suivante, sans attendre que le citoyen
    reparle. None si rien de nouveau à annoncer.
    """
    deps = deps or Dependances()
    if etat.get("mode") != "administratif" or etat.get("phase") != "collecte" or not etat.get("dossier_id"):
        return None

    resultat = await asyncio.to_thread(deps.document_recu, etat)
    if resultat is None:
        return None

    morceaux = resultat.get("reponse")
    reponse = resultat.get("reponse_fr") or ""
    document = _noter_document_attendu(etat, resultat.get("document_attendu"))
    if resultat.get("phase_suivante") == "complet" and not (resultat.get("manquants") or []):
        recapitulatif = _recapitulatif(etat)
        reponse, morceaux = recapitulatif.francais, phrases.reponse(recapitulatif)
        etat["phase"] = "relecture_en_cours"
        document = _noter_document_attendu(etat, None)
    if not reponse:
        return None
    await _persister_dossier(etat, deps)
    return _conclure(etat, ResultatTour(reponse, document_attendu=document, reponse=morceaux))


# ---------------------------------------------------------------------------
# Étapes
# ---------------------------------------------------------------------------

def _phrase_a_trous(cle: str, **remplacements: str) -> phrases.Phrase:
    """
    Une phrase système dont le code remplit les trous ({demarche}…).

    Si le pulaar relu a PERDU le trou — un relecteur peut l'avoir traduit ou
    supprimé — on renonce à ce pulaar : mieux vaut repasser par le traducteur
    que dire une phrase à laquelle il manque le nom de la démarche.
    """
    phrase = demarche.phrase_systeme(cle)
    francais, pulaar = phrase.francais, (phrase.pulaar if phrase.pulaar_valide else None)
    for nom, valeur in remplacements.items():
        trou = "{" + nom + "}"
        francais = francais.replace(trou, valeur)
        if pulaar is not None:
            pulaar = pulaar.replace(trou, valeur) if trou in pulaar else None
    return phrases.Phrase(francais=francais, pulaar=pulaar, pulaar_valide=bool(pulaar),
                          origine=f"systeme:{cle}")


def _reponse_information(texte: str, *fixes: phrases.Phrase) -> ResultatTour:
    """La réponse du modèle, suivie s'il y a lieu d'une phrase fixe de l'agent."""
    morceaux = phrases.reponse(texte or None, *fixes)
    return ResultatTour(morceaux.francais or MESSAGE_REPETER,
                        reponse=morceaux if morceaux.morceaux else None)


async def _tour_information(etat: dict, message: str, deps: Dependances) -> Optional[ResultatTour]:
    """Réponse du mode information, ou None si la bascule vers le mode administratif est confirmée."""
    resultats = await deps.rechercher(message, etat.get("commune_profil"))
    traitables = await asyncio.to_thread(demarche.demarches_traitables)
    prompt = build_generator_prompt(
        message, rag.resume_rag(resultats),
        history=etat["historique"][-HISTORIQUE_POUR_PROMPT:],
        demarches_en_ligne=[d.libelle for d in traitables],
    )
    analyse = await deps.completer_structure(
        [{"role": "system", "content": SYSTEM_PROMPT_GENERATOR}, {"role": "user", "content": prompt}],
        SCHEMA_REPONSE_INFORMATION,
        nom_schema="reponse_information",
        temperature=0.3,
    )

    texte = analyse.get("reponse") or ""
    attendue = etat.get("demarche_proposee") if etat.get("dernier_tour_propose_demarche") else None

    # --- Le tour précédent a proposé une démarche : on attend un oui ou un non.
    if attendue:
        entendu = classer_confirmation(message)
        if entendu == "oui" and bool(analyse.get("confirme_demarrage_demarche")):
            type_demarche = attendue
        else:
            if entendu == "non":
                # Refus clair : on repart en information, sans démarche en attente.
                etat["dernier_tour_propose_demarche"] = False
                etat["demarche_proposee"] = None
                return _reponse_information(texte)
            # Ni oui ni non, ou le modèle n'y lit pas une confirmation : on
            # REDEMANDE en nommant la démarche, au lieu d'ouvrir un dossier
            # sur un « oui » supposé. Un dossier créé par erreur, lui, reste.
            libelle = _libelle_demarche(attendue)
            return _reponse_information(texte, _phrase_a_trous("bascule_confirmation", demarche=libelle))

    # --- Sinon : le modèle propose-t-il de commencer, et laquelle ?
    else:
        propose = (demarche.reconnaitre_demarche(analyse.get("demarche_proposee"))
                   if analyse.get("propose_demarrer_demarche") else None)
        # Retenue MAINTENANT : au tour suivant, le citoyen dit seulement
        # « oui », et plus rien ne dira de quelle démarche il parlait.
        etat["dernier_tour_propose_demarche"] = propose is not None
        etat["demarche_proposee"] = propose.type_demarche if propose else None
        if analyse.get("propose_demarrer_demarche") and propose is None:
            # Aucune démarche reconnue : on ne bascule PAS. Auparavant, on
            # démarrait l'extrait de naissance par défaut, et un citoyen venu
            # déclarer un décès s'entendait demander l'âge de son enfant.
            libelles = ", ".join(d.libelle for d in traitables)
            return _reponse_information(
                texte, _phrase_a_trous("bascule_demarche_inconnue", demarches=libelles))
        if propose is not None:
            # L'agent NOMME la démarche avant de la commencer : c'est le seul
            # moment où le citoyen peut encore dire non.
            return _reponse_information(
                texte, _phrase_a_trous("bascule_confirmation", demarche=propose.libelle))
        return _reponse_information(texte)
    etat["mode"] = "administratif"
    etat["phase"] = "collecte"
    etat["type_demarche"] = type_demarche
    # Étape 2.4 : la démarche est figée ICI, au moment où le citoyen s'engage.
    # Elle ne bougera plus jusqu'à la fin de ce dialogue, même si un agent la
    # modifie et la republie entre-temps.
    etat["demarche_version"] = demarche.definition(type_demarche).version
    # Les cases à remplir sont celles de CETTE démarche, pas celles de la
    # démarche par défaut préparées à l'ouverture de la session.
    etat["slots"] = demarche.slots_vides(type_demarche, etat["demarche_version"])
    commune_id = await asyncio.to_thread(deps.resoudre_commune, etat.get("commune_profil"))
    dossier = await asyncio.to_thread(
        deps.creer_dossier, etat["citoyen_id"], type_demarche, etat["slots"], etat.get("cas_legal"), commune_id
    )
    if dossier:
        etat["dossier_id"] = dossier["id"]
        await deps.evenement(
            dossier["id"],
            "cree",
            "Démarche commencée avec l'agent vocal",
            acteur_type="citoyen",
            acteur_id=etat["citoyen_id"],
            statut_apres=dossier.get("statut", "en_cours"),
        )
    else:
        log.warning("Bascule administratif sans dossier persisté (session=%s)", etat["id"])
    return None


async def _tour_collecte(etat: dict, message: str, deps: Dependances,
                         sans_interpreter: bool = False,
                         echec_silencieux: bool = False) -> ResultatTour:
    resultat = await deps.tour_administratif(etat, message, sans_interpreter, echec_silencieux)
    morceaux = resultat.get("reponse")
    reponse = resultat.get("reponse_fr") or ""
    document = _noter_document_attendu(etat, resultat.get("document_attendu"))
    _recalculer_cas_legal(etat)

    if resultat.get("phase_suivante") == "bloque":
        # Délai légal dépassé (plan étape 2.1, forme 2) : la démarche ne peut
        # pas aboutir. Le message vient de la règle, pas du moteur — c'est lui
        # qui oriente le citoyen vers la bonne procédure.
        await _persister_dossier(etat, deps)
        return await _bloquer(
            etat, deps,
            message=reponse or _phrase(MESSAGE_BLOCAGE, "blocage_relecture").francais,
            motif=f"regle:{resultat.get('regle_declenchee') or 'inconnue'}",
            libelle="Bloqué : une règle de la démarche interdit de poursuivre",
        )

    if resultat.get("phase_suivante") == "complet":
        # RG7 : nœud obligatoire, décidé par le code (jamais par le modèle).
        manquants = resultat.get("manquants") or []
        if not manquants:
            recapitulatif = _recapitulatif(etat)
            reponse, morceaux = recapitulatif.francais, phrases.reponse(recapitulatif)
            etat["phase"] = "relecture_en_cours"
            etat["relances_relecture"] = 0
            document = _noter_document_attendu(etat, None)
        else:
            reponse, morceaux = _redemander(etat, manquants, deps)

    await _persister_dossier(etat, deps)
    avancement = resultat.get("progression")
    if not reponse:
        return ResultatTour(_phrase(MESSAGE_REPETER, "repeter").francais, document_attendu=document,
                            reponse=phrases.reponse(_phrase(MESSAGE_REPETER, "repeter")),
                            progression=avancement)
    return ResultatTour(reponse, document_attendu=document, reponse=morceaux, progression=avancement)


def _redemander(etat: dict, manquants: list, deps: Dependances) -> tuple:
    """
    Le dialogue se croit fini, mais un champ obligatoire est vide.

    Ne devrait pas arriver — c'est pourquoi c'est journalisé. Ce qui compte
    est de ne pas laisser le citoyen devant un agent qui répète « je n'ai pas
    bien compris » sans fin : on repose la question qui manque, et la collecte
    reprend son cours.
    """
    log.error(
        "Dialogue annoncé complet alors que %s manque(nt) (session=%s, démarche=%s)",
        ", ".join(manquants), etat.get("id"), etat.get("type_demarche"),
    )
    etat["phase"] = "collecte"
    definitions = deps.definition_champs(
        etat.get("type_demarche", TYPE_DEMARCHE_ADMINISTRATIVE), etat.get("demarche_version")
    )
    par_nom = {d["nom_champ"]: d for d in definitions or []}
    champ = par_nom.get(manquants[0])
    question = demarche.question_champ(champ) if champ else _phrase(MESSAGE_REPETER, "repeter")
    return question.francais, phrases.reponse(question)


async def _tour_relecture(etat: dict, message: str, deps: Dependances) -> ResultatTour:
    if classer_confirmation(message) == "oui":
        return await _confirmer_envoi(etat, deps)

    definitions = await asyncio.to_thread(
        deps.definition_champs,
        etat.get("type_demarche", TYPE_DEMARCHE_ADMINISTRATIVE),
        etat.get("demarche_version"),
    )
    par_nom = {d["nom_champ"]: d for d in definitions or []}
    try:
        analyse = await deps.completer_structure(
            [
                {"role": "system", "content": SYSTEM_PROMPT_CORRECTION_RELECTURE},
                {"role": "user", "content": construire_prompt_correction(message, definitions or [], etat["slots"])},
            ],
            SCHEMA_CORRECTION_RELECTURE,
            nom_schema="correction_relecture",
            temperature=0.1,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Extraction de correction indisponible (%s)", type(exc).__name__)
        analyse = {"intention": "refuse_sans_precision", "champ": None, "nouvelle_valeur": None}

    intention = analyse.get("intention")
    champ = analyse.get("champ") if analyse.get("champ") in par_nom else None

    if champ:
        return await _appliquer_correction(etat, par_nom[champ], analyse.get("nouvelle_valeur"), deps)

    if intention == "confirme":
        # Le modèle croit à une confirmation, mais sans « oui » net : RG7 impose de redemander.
        return ResultatTour("Pour envoyer votre demande à la mairie, j'ai besoin d'un « oui » clair. Est-ce que tout est exact ?")

    etat["relances_relecture"] = int(etat.get("relances_relecture") or 0) + 1
    if etat["relances_relecture"] >= SEUIL_RELANCES_RELECTURE:
        etat["relances_relecture"] = 0
        etat["nb_iterations_correction"] = int(etat.get("nb_iterations_correction") or 0) + 1
        if etat["nb_iterations_correction"] >= SEUIL_ITERATIONS_CORRECTION_BLOQUE:
            return await _bloquer(etat, deps)
        await _persister_dossier(etat, deps)

    if intention == "hors_sujet":
        return ResultatTour("Je vous ai relu vos informations. Dites « oui » si tout est exact, ou dites-moi ce qu'il faut corriger.")
    return ResultatTour(
        "D'accord. Quelle information n'est pas correcte ? Dites-moi par exemple : le nom de la maman, ou la date de naissance."
    )


async def _appliquer_correction(etat: dict, definition: dict, nouvelle_valeur: Optional[str], deps: Dependances) -> ResultatTour:
    nom = definition["nom_champ"]
    etat["relances_relecture"] = 0
    etat["nb_iterations_correction"] = int(etat.get("nb_iterations_correction") or 0) + 1
    if etat["nb_iterations_correction"] >= SEUIL_ITERATIONS_CORRECTION_BLOQUE:
        return await _bloquer(etat, deps)
    if nom == "commune_naissance":
        etat["commune_id_resolue"] = False

    prefixe = "D'accord, corrigeons cela. "
    if nouvelle_valeur and definition["type_valeur"] not in ("age",):
        valide, valeur, raison = deps.valider_valeur(
            definition["type_valeur"], nouvelle_valeur, definition.get("regle_validation"), valeurs_connues=etat["slots"]
        )
        if valide:
            etat["slots"][nom] = valeur
            _recalculer_cas_legal(etat)
            await _persister_dossier(etat, deps)
            definitions = await asyncio.to_thread(
                deps.definition_champs,
                etat.get("type_demarche", TYPE_DEMARCHE_ADMINISTRATIVE),
                etat.get("demarche_version"),
            )
            manquants = slot_controller.champs_obligatoires_manquants(
                etat["slots"], definitions or [], etat.get("champs_ignores")
            )
            if not manquants:
                return ResultatTour(f"C'est corrigé. {construire_recapitulatif(etat['slots'])}")
        else:
            prefixe = f"{raison} "

    # Valeur absente ou invalide : le champ est vidé puis redemandé par la collecte normale.
    etat["slots"][nom] = {"valeur": None, "unite": None} if definition["type_valeur"] == "age" else None
    etat["phase"] = "collecte"
    await _persister_dossier(etat, deps)
    return ResultatTour(f"{prefixe}{definition['question']}".strip())


async def _confirmer_envoi(etat: dict, deps: Dependances) -> ResultatTour:
    numero = await asyncio.to_thread(deps.numero_suivi)
    etat["numero_suivi"] = numero
    etat["phase"] = "termine"
    _noter_document_attendu(etat, None)

    dossier_mis_a_jour = None
    if etat.get("dossier_id"):
        await deps.transition(
            etat["dossier_id"],
            "recu",
            acteur_type="citoyen",
            acteur_id=etat["citoyen_id"],
            champs={"numero_suivi": numero, "slots": etat["slots"], "nb_iterations_correction": int(etat.get("nb_iterations_correction") or 0)},
        )
        dossier_mis_a_jour = {"dossier_id": etat["dossier_id"], "statut": "recu", "numero_suivi": numero}
    else:
        log.error("Confirmation RG7 sans dossier persisté (session=%s)", etat["id"])

    commune = etat["slots"].get("commune_naissance")
    lieu = f" à la mairie de {commune}" if commune else ""
    chiffres = ", ".join(c for c in numero.split("-")[-1] if c.isdigit())
    reponse = (
        f"Voilà, votre demande est envoyée{lieu}. Votre numéro de suivi est {numero}. "
        f"Je vous redis les derniers chiffres un par un : {chiffres}. "
        "Je vous préviendrai dès que votre extrait de naissance sera prêt."
    )
    return ResultatTour(reponse, session_a_clore=True, dossier_mis_a_jour=dossier_mis_a_jour)


async def _bloquer(
    etat: dict,
    deps: Dependances,
    *,
    message: str = MESSAGE_BLOCAGE,
    motif: str = "relecture_rg7",
    libelle: str = "Bloqué : la relecture n'a jamais pu être confirmée",
) -> ResultatTour:
    """
    Fin de parcours. Deux causes aujourd'hui, distinguées par `motif` : la
    relecture jamais confirmée (défaut), et une règle de la démarche qui
    interdit de poursuivre (délai légal dépassé).

    `message` est mémorisé : si le citoyen reparle, il doit réentendre la
    raison de l'arrêt, pas un message générique qui ne lui dit rien.
    """
    etat["phase"] = "bloque"
    etat["message_blocage"] = message
    _noter_document_attendu(etat, None)
    dossier_mis_a_jour = None
    if etat.get("dossier_id"):
        iterations = int(etat.get("nb_iterations_correction") or 0)
        await deps.transition(
            etat["dossier_id"],
            "bloque",
            acteur_type="systeme",
            libelle=libelle,
            details={"nb_iterations_correction": iterations, "motif_blocage": motif},
            champs={"nb_iterations_correction": iterations, "motif_blocage": motif, "slots": etat["slots"]},
        )
        dossier_mis_a_jour = {"dossier_id": etat["dossier_id"], "statut": "bloque", "numero_suivi": etat.get("numero_suivi")}
    return ResultatTour(
        message,
        session_a_clore=True,
        dossier_mis_a_jour=dossier_mis_a_jour,
        reponse=phrases.depuis_texte(message, origine=f"blocage:{motif}"),
    )


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

def _recapitulatif(etat: dict) -> phrases.Phrase:
    """
    La relecture obligatoire (RG7), rendue depuis le gabarit de la démarche.

    Le gabarit sépare la phrase des valeurs : relue une fois, elle n'est plus
    retraduite à chaque dossier, et les dates sont énoncées en entier au lieu
    d'être lues comme des suites de chiffres (étape 3.2).

    Repli sur le récapitulatif écrit en dur quand aucun gabarit n'est défini —
    la migration 021 n'est peut-être pas appliquée, et la relecture ne peut
    pas être sautée.
    """
    rendu = demarche.rendre_gabarit(
        "recapitulatif",
        etat["slots"],
        etat.get("type_demarche") or TYPE_DEMARCHE_ADMINISTRATIVE,
        etat.get("demarche_version"),
    )
    if rendu is not None:
        return rendu
    log.info("Aucun gabarit de récapitulatif utilisable — repli sur le texte figé.")
    return phrases.Phrase(
        francais=construire_recapitulatif(etat["slots"]), origine="recapitulatif:repli"
    )


def _libelle_demarche(type_demarche: str) -> str:
    """Le nom lisible de la démarche, pour le dire au citoyen."""
    return demarche.definition(type_demarche).libelle or type_demarche


def _phrase(texte_par_defaut: str, cle: str) -> phrases.Phrase:
    """Une phrase système, en retombant sur le texte figé du module si besoin."""
    phrase = demarche.phrase_systeme(cle)
    return phrase if phrase.francais else phrases.Phrase(francais=texte_par_defaut, origine=f"systeme:{cle}")


def _conclure(etat: dict, resultat: ResultatTour) -> ResultatTour:
    ajouter_historique(etat, "assistant", resultat.reponse_fr)
    return resultat


def _message_fin(etat: dict) -> str:
    if etat.get("phase") == "bloque":
        return etat.get("message_blocage") or MESSAGE_BLOCAGE
    numero = etat.get("numero_suivi")
    return f"Votre demande a déjà été envoyée{f', numéro de suivi {numero}' if numero else ''}."


def _noter_document_attendu(etat: dict, document: Optional[str]) -> Optional[str]:
    etat["document_en_attente"] = document
    if document:
        etat.setdefault("documents_demandes", set()).add(document)
    return document


def _recalculer_cas_legal(etat: dict) -> None:
    """
    Le cas du dossier, recalculé par le CODE à chaque tour — jamais deviné par
    le modèle.

    Les seuils (un mois, un an) ne sont plus écrits ici : ils viennent de
    `demarche_cas` (étape 2.3, migration 018). Le DSF signale lui-même son
    incertitude sur le premier — « jusqu'à 45 jours en zone rurale éloignée
    selon les sources » — et corriger un seuil contesté ne doit pas demander
    un redéploiement.

    `None` en retour veut dire « pas encore déterminable » : le cas précédent
    est alors conservé, et surtout aucun cas par défaut n'est inscrit à tort.
    """
    cas = demarche.determiner_cas(
        etat["slots"],
        etat.get("type_demarche") or TYPE_DEMARCHE_ADMINISTRATIVE,
        etat.get("demarche_version"),
    )
    if cas:
        etat["cas_legal"] = cas


async def _persister_dossier(etat: dict, deps: Dependances) -> None:
    if not etat.get("dossier_id"):
        return
    champs: dict = {"slots": etat["slots"], "nb_iterations_correction": int(etat.get("nb_iterations_correction") or 0)}
    if etat.get("demarche_version"):
        # Tracé sur le dossier : un dossier relu des mois plus tard doit
        # pouvoir l'être avec les règles qui lui ont été appliquées.
        champs["demarche_version"] = etat["demarche_version"]
    if etat.get("cas_legal"):
        champs["cas_legal"] = etat["cas_legal"]
    commune_naissance = etat["slots"].get("commune_naissance")
    if commune_naissance and not etat.get("commune_id_resolue"):
        commune_id = await asyncio.to_thread(deps.resoudre_commune, commune_naissance)
        if commune_id:
            champs["commune_id"] = commune_id
            etat["commune_id_resolue"] = True
    ok = await asyncio.to_thread(lambda: deps.maj_dossier(etat["dossier_id"], **champs))
    if not ok:
        log.error("Persistance du dossier échouée (dossier=%s)", etat["dossier_id"])
