"""
Définition d'une démarche, lue en base (plan maître, étapes 2.2 et 2.3).

Point d'accès unique à tout ce qui décrit une démarche : ses champs, ses
pièces, ses règles, ses cas, et la démarche elle-même. Avant, ces
informations étaient dispersées entre cinq constantes Python, si bien
qu'ajouter une démarche demandait de modifier du code à cinq endroits — et
d'y penser à chaque fois.

REPLI
Chaque lecture a un repli sur les anciennes constantes, utilisé quand la base
est injoignable ou quand les migrations 017/018 ne sont pas encore appliquées.
Ce n'est pas une deuxième source de vérité : c'est un filet, pour qu'une
coupure réseau ne rende pas le dialogue impossible à un citoyen déjà en
ligne. Chaque repli laisse une trace dans le journal.

CACHE
Une démarche est relue à chaque tour de dialogue, par plusieurs citoyens à la
fois, alors qu'elle change quelques fois par mois. Elle est donc gardée en
mémoire quelques secondes. `vider_cache()` rend la main tout de suite après
une modification côté admin.
"""
from __future__ import annotations

import time
from datetime import date
from dataclasses import dataclass
from typing import Any

from services import conditions, gabarits
from services.journal import obtenir_logger
from services.phrases import Phrase
from supabase_client import get_supabase_client

log = obtenir_logger("demarche")

#: Quelques secondes suffisent : assez pour absorber les tours d'un même
#: dialogue, assez court pour qu'une correction côté admin se voie vite.
DUREE_CACHE_SECONDES = 30

_cache: dict[str, tuple[float, Any]] = {}


def vider_cache() -> None:
    _cache.clear()


def _lire(cle: str, charger) -> Any:
    entree = _cache.get(cle)
    if entree and time.monotonic() - entree[0] < DUREE_CACHE_SECONDES:
        return entree[1]
    valeur = charger()
    _cache[cle] = (time.monotonic(), valeur)
    return valeur


#: Dernière lecture qui a ÉCHOUÉ, et pourquoi — ou `None` si tout va bien.
#:
#: Une table vide et une table injoignable produisent toutes deux une liste
#: vide, et un appelant qui ne les distingue pas énonce une cause fausse :
#: « les migrations sont-elles appliquées ? » alors que c'est le réseau qui
#: est tombé. Cherchée dans la mauvaise direction, une panne de trente
#: secondes coûte une soirée.
_derniere_erreur: str | None = None


def derniere_erreur_lecture() -> str | None:
    """La cause du dernier échec de lecture, pour qui doit l'expliquer."""
    return _derniere_erreur


def _table(nom: str, **filtres) -> list[dict]:
    """Lecture d'une table de configuration. Liste vide si elle est hors d'atteinte."""
    global _derniere_erreur
    try:
        requete = get_supabase_client().table(nom).select("*")
        for colonne, valeur in filtres.items():
            requete = requete.eq(colonne, valeur)
        donnees = (requete.execute().data) or []
        _derniere_erreur = None
        return donnees
    except Exception as exc:  # noqa: BLE001 — migration pas encore appliquée, ou base injoignable
        log.warning("Table de configuration %r illisible (%s).", nom, exc)
        _derniere_erreur = f"{nom} : {exc}"
        return []


class LectureImpossible(RuntimeError):
    """Une table n'a pas pu être lue — à ne JAMAIS confondre avec « vide »."""


def lire_strictement(nom: str, **filtres) -> list[dict]:
    """
    Comme `_table`, mais une panne LÈVE au lieu de rendre une liste vide.

    `_table` convient au dialogue : mieux vaut un repli qu'un citoyen coupé.
    Il ne convient pas à ce qui ÉCRIT d'après ce qu'il a lu. Publier sur une
    lecture ratée figerait une démarche sans aucune question ; abandonner un
    brouillon sur une lecture ratée prendrait chaque ligne pour « à retirer ».
    """
    try:
        requete = get_supabase_client().table(nom).select("*")
        for colonne, valeur in filtres.items():
            requete = requete.eq(colonne, valeur)
        return (requete.execute().data) or []
    except Exception as exc:  # noqa: BLE001
        raise LectureImpossible(f"{nom} : {exc}") from exc


# ============================================================================
# Repli — les anciennes constantes, conservées comme filet de sécurité
# ============================================================================

TYPE_DEMARCHE_PAR_DEFAUT = "extrait_naissance"

_REPLI_TYPES_DOCUMENT = (
    "certificat_naissance", "cni_declarant", "cni_conjoint",
    "livret_famille", "certificat_mariage",
    "cni_declarant_recto", "cni_declarant_verso",
)

_REPLI_SLOTS_VIDES: dict = {
    "age_enfant": {"valeur": None, "unite": None},
    "commune_naissance": None,
    "nom_enfant": None,
    "date_naissance_enfant": None,
    "nom_declarant": None,
    "nom_mere": None,
    "date_naissance_mere": None,
    "parents_maries": None,
}

#: Seuils de `dialogue_engine.determiner_cas_legal`, en jours.
_REPLI_CAS = (
    ("dans_les_delais", "age_jours(age_enfant) <= 30"),
    ("tardif", "age_jours(age_enfant) <= 365"),
    ("jugement_requis", None),
)

_REPLI_MOTS_CLES = ("extrait de naissance", "acte de naissance", "naissance")


# ============================================================================
# Définition de la démarche
# ============================================================================


@dataclass(frozen=True)
class Definition:
    type_demarche: str
    libelle: str
    mots_cles: tuple[str, ...] = ()
    traitable: bool = False
    champ_age: str | None = None
    version: int = 1
    #: Vrai quand la ligne vient de la base, faux quand c'est le repli.
    en_base: bool = True


def definition(type_demarche: str = TYPE_DEMARCHE_PAR_DEFAUT) -> Definition:
    def charger() -> Definition:
        lignes = _table("demarche_definitions", type_demarche=type_demarche)
        if not lignes:
            log.warning("Démarche %r absente de demarche_definitions — repli sur les constantes.", type_demarche)
            return Definition(
                type_demarche=type_demarche,
                libelle=type_demarche.replace("_", " ").capitalize(),
                mots_cles=_REPLI_MOTS_CLES if type_demarche == TYPE_DEMARCHE_PAR_DEFAUT else (),
                traitable=type_demarche == TYPE_DEMARCHE_PAR_DEFAUT,
                champ_age="age_enfant" if type_demarche == TYPE_DEMARCHE_PAR_DEFAUT else None,
                en_base=False,
            )
        ligne = lignes[0]
        return Definition(
            type_demarche=ligne["type_demarche"],
            libelle=ligne.get("libelle") or type_demarche,
            mots_cles=tuple(ligne.get("mots_cles") or ()),
            traitable=bool(ligne.get("traitable")),
            champ_age=ligne.get("champ_age"),
            version=int(ligne.get("version") or 1),
        )

    return _lire(f"definition:{type_demarche}", charger)


def demarches_traitables() -> list[Definition]:
    """Les démarches que le dialogue guidé sait mener de bout en bout."""
    def charger() -> list[Definition]:
        lignes = [
            l for l in _table("demarche_definitions")
            if l.get("traitable") and l.get("actif", True)
        ]
        if not lignes:
            return [definition(TYPE_DEMARCHE_PAR_DEFAUT)]
        return [definition(l["type_demarche"]) for l in lignes]

    return _lire("traitables", charger)


def reconnaitre_demarche(nom_demarche: str | None) -> Definition | None:
    """
    La démarche traitable correspondant à un nom trouvé par la recherche.

    Remplace `est_demarche_extrait_naissance`, qui cherchait le mot
    « naissance » n'importe où dans le nom : « certificat de naissance » et
    « déclaration de naissance » — deux démarches différentes — basculaient
    toutes les deux vers l'extrait de naissance. Le rapprochement se fait
    maintenant sur des mots-clés déclarés, le plus long d'abord pour qu'un
    mot-clé précis l'emporte sur un mot-clé générique.
    """
    nom = (nom_demarche or "").strip().casefold()
    if not nom:
        return None
    candidats = [
        (mot, demarche)
        for demarche in demarches_traitables()
        for mot in demarche.mots_cles
    ]
    for mot, demarche in sorted(candidats, key=lambda c: len(c[0]), reverse=True):
        if mot.casefold() in nom:
            return demarche
    return None


# ============================================================================
# Instantané d'une démarche — figé par version (étape 2.4)
# ============================================================================


@dataclass(frozen=True)
class Instantane:
    """
    Une démarche entière à un instant donné.

    `version` est le numéro sous lequel elle a été publiée. `fige` dit d'où
    vient cet instantané : d'une version publiée (`demarche_versions`), ou de
    la définition VIVANTE, celle qu'un agent peut être en train de modifier.
    Un dialogue en cours doit toujours travailler sur un instantané figé —
    sinon une question ajoutée en pleine journée ressurgit après le
    récapitulatif, et une question retirée laisse une valeur orpheline.
    """

    type_demarche: str
    version: int
    definition: Definition
    champs: list[dict]
    documents: list[dict]
    regles: list[dict]
    cas: list[dict]
    fige: bool
    #: Les gabarits à trous, par clé. `None` pour une version publiée avant
    #: qu'on les fige (v1 et v2 de l'extrait de naissance) : on ne sait pas
    #: ce qu'ils disaient alors, et le prétendre serait inventer.
    gabarits: dict[str, dict] | None = None


def _instantane_vivant(type_demarche: str, lire=None) -> Instantane:
    """
    La démarche telle qu'elle est en base à cet instant — le BROUILLON.

    `lire` vaut `_table` pour le dialogue (repli toléré) et
    `lire_strictement` pour la publication (aucune panne ne passe pour du vide).
    """
    lire = lire or _table

    def ordonner(nom: str) -> list[dict]:
        return sorted(lire(nom, type_demarche=type_demarche), key=lambda l: l.get("ordre", 0))

    lignes_cas = ordonner("demarche_cas")
    if not lignes_cas:
        log.warning("Aucun cas défini pour %r — repli sur les seuils figés.", type_demarche)
        lignes_cas = [
            {"code": code, "condition": condition, "ordre": index, "libelle": code}
            for index, (code, condition) in enumerate(_REPLI_CAS)
        ]
    meta = definition(type_demarche)
    return Instantane(
        type_demarche=type_demarche,
        version=meta.version,
        definition=meta,
        champs=ordonner("demarche_champs"),
        documents=ordonner("demarche_documents"),
        regles=ordonner("demarche_regles"),
        cas=lignes_cas,
        fige=False,
        gabarits={l["cle"]: l for l in lire("demarche_gabarits", type_demarche=type_demarche)},
    )


def instantane_publie(ligne: dict) -> Instantane:
    """Une ligne de `demarche_versions`, relue en instantané figé."""
    type_demarche, version = ligne["type_demarche"], int(ligne["version"])
    contenu = ligne.get("contenu") or {}
    ligne_definition = contenu.get("definition") or {}
    return Instantane(
        type_demarche=type_demarche,
        version=version,
        definition=Definition(
            type_demarche=type_demarche,
            libelle=ligne_definition.get("libelle") or type_demarche,
            mots_cles=tuple(ligne_definition.get("mots_cles") or ()),
            traitable=bool(ligne_definition.get("traitable")),
            champ_age=ligne_definition.get("champ_age"),
            version=version,
        ),
        champs=list(contenu.get("champs") or []),
        documents=list(contenu.get("documents") or []),
        regles=list(contenu.get("regles") or []),
        cas=list(contenu.get("cas") or []),
        fige=True,
        gabarits=(
            {l["cle"]: l for l in contenu["gabarits"]} if "gabarits" in contenu else None
        ),
    )


def instantane(type_demarche: str = TYPE_DEMARCHE_PAR_DEFAUT, version: int | None = None) -> Instantane:
    """
    La démarche dans la version demandée, ou la version vivante si `version`
    vaut `None`.

    Une version introuvable — jamais publiée, ou base injoignable — retombe
    sur la version vivante, en le signalant. C'est un compromis assumé : mieux
    vaut un dialogue qui continue avec des questions légèrement différentes
    qu'un citoyen coupé au milieu de sa démarche.
    """
    if version is None:
        return _lire("vivant:" + type_demarche, lambda: _instantane_vivant(type_demarche))

    def charger() -> Instantane:
        lignes = _table("demarche_versions", type_demarche=type_demarche, version=version)
        if not lignes:
            log.warning(
                "Version %s de %r introuvable — repli sur la définition vivante.", version, type_demarche
            )
            return _instantane_vivant(type_demarche)
        return instantane_publie(lignes[0])

    return _lire("version:%s:%s" % (type_demarche, version), charger)


def publier(type_demarche: str = TYPE_DEMARCHE_PAR_DEFAUT, *, par: str | None = None) -> int:
    """
    Fige la démarche vivante dans une nouvelle version et retourne son numéro.

    Les dialogues déjà commencés ne la voient pas : ils gardent la version
    sous laquelle ils ont démarré. Seuls les suivants en bénéficient.
    """
    # Lectures STRICTES : une panne réseau ici figerait une démarche vide,
    # et tous les dialogues suivants démarreraient dessus.
    lignes_definition = lire_strictement("demarche_definitions", type_demarche=type_demarche)
    if not lignes_definition:
        raise LectureImpossible(f"Démarche {type_demarche!r} absente de demarche_definitions.")
    vivant = _instantane_vivant(type_demarche, lire=lire_strictement)
    if not vivant.champs:
        raise LectureImpossible(f"Démarche {type_demarche!r} sans aucun champ : rien de publiable.")
    nouvelle = int(lignes_definition[0].get("version") or 1) + 1
    contenu = {
        "definition": {
            "libelle": vivant.definition.libelle,
            "mots_cles": list(vivant.definition.mots_cles),
            "traitable": vivant.definition.traitable,
            "champ_age": vivant.definition.champ_age,
        },
        "champs": vivant.champs,
        "documents": vivant.documents,
        "regles": vivant.regles,
        "cas": vivant.cas,
        # Figés depuis l'étape 4.4 : un récapitulatif modifié touchait tout de
        # suite les dialogues en cours, en citant les champs de LEUR version.
        "gabarits": sorted((vivant.gabarits or {}).values(), key=lambda l: l["cle"]),
    }
    client = get_supabase_client()
    client.table("demarche_versions").insert({
        "type_demarche": type_demarche,
        "version": nouvelle,
        "publiee_par": par or "inconnu",
        "contenu": contenu,
    }).execute()
    client.table("demarche_definitions").update({"version": nouvelle}).eq(
        "type_demarche", type_demarche
    ).execute()
    vider_cache()
    log.info("Demarche %r publiee en version %s par %s.", type_demarche, nouvelle, par or "inconnu")
    return nouvelle


# ============================================================================
# Champs, pièces, cas
# ============================================================================


def champs(type_demarche: str = TYPE_DEMARCHE_PAR_DEFAUT, version: int | None = None) -> list[dict]:
    """Champs de la démarche, triés par `ordre`."""
    return instantane(type_demarche, version).champs


def documents(type_demarche: str = TYPE_DEMARCHE_PAR_DEFAUT, version: int | None = None) -> list[dict]:
    """Pièces de la démarche, triées par `ordre`."""
    return instantane(type_demarche, version).documents


def regles(type_demarche: str = TYPE_DEMARCHE_PAR_DEFAUT, version: int | None = None) -> list[dict]:
    """Règles transverses de la démarche (cf. services/regles_demarche.py)."""
    return instantane(type_demarche, version).regles


def types_documents_acceptes() -> tuple[str, ...]:
    """
    Types acceptés à l'upload d'une pièce.

    Comprend les types obsolètes : d'anciens dossiers en portent, et refuser
    leur relecture serait pire que de les accepter. Un type obsolète n'est
    simplement plus demandé par aucune démarche.
    """
    def charger() -> tuple[str, ...]:
        lignes = _table("types_document_acceptes")
        if not lignes:
            log.warning("types_document_acceptes vide ou illisible — repli sur les constantes.")
            return _REPLI_TYPES_DOCUMENT
        return tuple(sorted(l["type_document"] for l in lignes))

    return _lire("types_documents", charger)


def slots_vides(type_demarche: str = TYPE_DEMARCHE_PAR_DEFAUT, version: int | None = None) -> dict:
    """
    L'état initial des réponses, déduit des champs de la démarche.

    Un champ de type `age` vaut `{"valeur": None, "unite": None}` : c'est la
    forme que le reste du code attend (cf. `normaliser_age`).
    """
    definitions = champs(type_demarche, version)
    if not definitions:
        log.warning("Aucun champ pour %r — repli sur les slots figés.", type_demarche)
        return {cle: (dict(v) if isinstance(v, dict) else v) for cle, v in _REPLI_SLOTS_VIDES.items()}
    return {
        c["nom_champ"]: ({"valeur": None, "unite": None} if c.get("type_valeur") == "age" else None)
        for c in definitions
    }


def champs_obligatoires(
    type_demarche: str = TYPE_DEMARCHE_PAR_DEFAUT, version: int | None = None
) -> list[dict]:
    return [c for c in champs(type_demarche, version) if c.get("obligatoire", True)]


def cas(type_demarche: str = TYPE_DEMARCHE_PAR_DEFAUT, version: int | None = None) -> list[dict]:
    return instantane(type_demarche, version).cas


def determiner_cas(
    slots: dict, type_demarche: str = TYPE_DEMARCHE_PAR_DEFAUT, version: int | None = None,
    aujourdhui: date | None = None,
) -> str | None:
    """
    Le cas dans lequel se trouve ce dossier, ou `None` si rien ne tranche.

    Le premier cas dont la condition est CERTAINEMENT vraie gagne ; un cas
    sans condition est le cas par défaut. `None` quand l'information qui
    départage n'est pas encore connue — l'appelant ne doit alors pas conclure,
    et surtout pas retenir le cas par défaut : mieux vaut pas de cas du tout
    qu'un cas faux inscrit sur un dossier.

    `aujourdhui` sert à rejouer une démarche à une autre date (simulateur,
    étape 4.3) : sans lui, un délai se mesurait toujours depuis la date du
    jour, et le cas affiché n'était pas celui du scénario joué.
    """
    for ligne in cas(type_demarche, version):
        condition = ligne.get("condition")
        if not condition:
            return ligne["code"]
        resultat = conditions.evaluer(condition, slots, aujourdhui)
        if resultat == conditions.VRAI:
            return ligne["code"]
        if resultat == conditions.INCONNU:
            return None
    return None


# ============================================================================
# Phrases adressées au citoyen (étape 3)
#
# Chaque phrase voyage avec son pulaar validé, s'il existe, jusqu'à la
# synthèse vocale : c'est ce qui permet de ne plus appeler le traducteur pour
# une phrase connue d'avance (`temps_reel/parole.py`).
# ============================================================================

#: Repli des phrases système quand `phrases_systeme` est hors d'atteinte.
#: Mêmes textes que ceux semés par la migration 020.
_REPLI_PHRASES_SYSTEME = {
    "confirmation_reponse": "C'est noté.",
    "confirmation_photo": "Merci, photo bien reçue.",
    "champ_facultatif_abandonne": "Ce n'est pas obligatoire, on continue.",
    "document_facultatif_abandonne": "Pas de problème, ce n'est pas obligatoire, on continue.",
    "document_obligatoire_abandonne": (
        "D'accord, on continue sans cette photo pour l'instant — un agent de la mairie "
        "vous recontactera pour l'obtenir."
    ),
    "repeter": "Excusez-moi, je n'ai pas bien compris. Pouvez-vous répéter, s'il vous plaît ?",
    "blocage_relecture": (
        "Je rencontre des difficultés à finaliser votre demande après plusieurs tentatives. "
        "Un agent de votre mairie va reprendre votre dossier directement — vous n'avez rien "
        "d'autre à faire pour l'instant."
    ),
    "refus_date_future": "Cette date est dans le futur, ce qui n'est pas possible ici.",
    "refus_date_incomprise": "Je n'ai pas compris cette date — précisez le jour, le mois et l'année.",
    "refus_reponse_vide": "Je n'ai rien entendu.",
    "refus_reponse_longue": "La réponse est trop longue pour être un nom ou un lieu.",
    "refus_oui_non": "Dites-moi simplement oui, ou non.",
    "refus_nombre": "Ce n'est pas un nombre que j'ai compris.",
    # Tours de politesse pendant la collecte (cf. services/tours_sociaux.py).
    # Courtes par nécessité : elles précèdent la question, qui est reposée
    # juste après, et le tout est dit à voix haute.
    "social_salutation": "Bonjour !",
    "social_remerciement": "Je vous en prie.",
    "social_patience": "D'accord, prenez votre temps. Je vous écoute.",
}


def _phrases_systeme() -> dict[str, dict]:
    def charger() -> dict[str, dict]:
        lignes = _table("phrases_systeme")
        if not lignes:
            log.warning("phrases_systeme illisible — repli sur les textes figés (aucun pulaar validé).")
            return {}
        return {l["cle"]: l for l in lignes}

    return _lire("phrases_systeme", charger)


#: Préfixe des phrases système qui portent le libellé d'une valeur
#: d'énumération (migration 033). Voir `libelles_enum_pulaar`.
PREFIXE_VALEUR_ENUM = "valeur_"


def libelles_enum_pulaar() -> dict[str, str]:
    """
    Code d'énumération (« polygamie_2 ») -> son pulaar RELU.

    Les codes non relus sont absents du dictionnaire, jamais présents avec
    leur traduction automatique : `gabarits._valeur_pulaar` renvoie alors
    `None`, et le français repart au traducteur. C'est la règle de tout le
    dispositif — une traduction que personne n'a lue n'est jamais dite.
    """
    return {
        ligne["cle"][len(PREFIXE_VALEUR_ENUM):]: ligne["pulaar"].strip()
        for ligne in _phrases_systeme().values()
        if ligne["cle"].startswith(PREFIXE_VALEUR_ENUM)
        and ligne.get("pulaar_valide")
        and (ligne.get("pulaar") or "").strip()
    }


def phrase_systeme(cle: str) -> Phrase:
    """
    Une phrase fixe de l'agent, par sa clé.

    Une clé inconnue ne fait pas taire l'agent : elle produit une phrase de
    secours visible, préférable à un silence pour quelqu'un qui ne lit pas.
    """
    ligne = _phrases_systeme().get(cle)
    if ligne is None:
        repli = _REPLI_PHRASES_SYSTEME.get(cle)
        if repli is None:
            log.error("Phrase système inconnue : %r", cle)
            return Phrase(francais="Un instant, s'il vous plaît.", origine=f"systeme:{cle}")
        return Phrase(francais=repli, origine=f"systeme:{cle}")
    return Phrase(
        francais=ligne.get("francais") or "",
        pulaar=ligne.get("pulaar"),
        pulaar_valide=bool(ligne.get("pulaar_valide")),
        audio=ligne.get("audio"),
        origine=f"systeme:{cle}",
    )


def valide_au_rang(ligne: dict, colonne_drapeaux: str, index: int) -> bool:
    """
    La relecture du rang `index`, ou celle de la ligne entière à défaut.

    Une ligne porte plusieurs phrases — une question et ses relances — et
    `pulaar_valide` ne vaut que pour la ligne. Valider une relance validerait
    donc la question avec elle, et une phrase que personne n'a lue se mettrait
    à être dite. La migration 024 ajoute un drapeau par rang ; un tableau vide
    dit « rien de décidé par phrase » et laisse `pulaar_valide` trancher,
    exactement comme avant.
    """
    drapeaux = list(ligne.get(colonne_drapeaux) or [])
    if index < len(drapeaux):
        return bool(drapeaux[index])
    return bool(ligne.get("pulaar_valide"))


def message_document(ligne: dict, tentative: int) -> Phrase:
    """
    Ce que l'agent dit pour réclamer une pièce.

    `tentative` vaut 0 pour la première demande, puis 1, 2… pour les rappels,
    pris à tour de rôle dans la liste. Deux rappels consécutifs identiques mot
    pour mot donnent au citoyen l'impression de ne pas être entendu.
    """
    type_document = ligne.get("type_document", "cette pièce")
    origine = f"document:{type_document}"
    if tentative <= 0:
        return Phrase(
            francais=ligne.get("message_demande") or f"J'ai besoin d'une photo : {type_document}.",
            pulaar=ligne.get("message_demande_pulaar"),
            pulaar_valide=bool(ligne.get("pulaar_valide")),
            audio=ligne.get("message_audio"),
            origine=origine,
        )
    rappels = list(ligne.get("messages_rappel") or [])
    if not rappels:
        return Phrase(
            francais=f"Je n'ai toujours pas reçu la photo : {type_document}.", origine=origine
        )
    index = (tentative - 1) % len(rappels)
    rappels_pulaar = list(ligne.get("messages_rappel_pulaar") or [])
    return Phrase(
        francais=rappels[index],
        pulaar=rappels_pulaar[index] if index < len(rappels_pulaar) else None,
        pulaar_valide=valide_au_rang(ligne, "messages_rappel_pulaar_valide", index),
        origine=f"{origine}:rappel{index}",
    )


def question_champ(ligne: dict) -> Phrase:
    return Phrase(
        francais=ligne.get("question") or "",
        pulaar=ligne.get("question_pulaar"),
        pulaar_valide=bool(ligne.get("pulaar_valide")),
        audio=ligne.get("question_audio"),
        origine=f"champ:{ligne.get('nom_champ', '?')}",
    )


def gabarits_demarche(type_demarche: str = TYPE_DEMARCHE_PAR_DEFAUT) -> dict[str, dict]:
    """
    Tous les gabarits à trous de la démarche, par clé.

    Point d'entrée UNIQUE : l'atelier de relecture lisait le cache
    directement, avec un chargeur qui ne chargeait rien. Les gabarits
    n'apparaissaient donc que si un autre appel les y avait déjà mis — jamais
    dans un script qui démarre. Le récapitulatif est resté invisible à la
    relecture sans que rien ne le signale.
    """
    def charger() -> dict[str, dict]:
        lignes = _table("demarche_gabarits", type_demarche=type_demarche)
        return {l["cle"]: l for l in lignes}

    return _lire(f"gabarits:{type_demarche}", charger)


def gabarit(cle: str, type_demarche: str = TYPE_DEMARCHE_PAR_DEFAUT) -> dict | None:
    """Un gabarit à trous du BROUILLON (`demarche_gabarits`), ou `None`."""
    return gabarits_demarche(type_demarche).get(cle)


def gabarits_en_vigueur(
    type_demarche: str = TYPE_DEMARCHE_PAR_DEFAUT, version: int | None = None
) -> dict[str, dict]:
    """
    Les gabarits que le dialogue doit dire : ceux de SA version.

    Une version publiée avant qu'on fige les gabarits n'en contient pas ; on
    retombe alors sur le brouillon, comme avant l'étape 4.4 — c'est le seul
    texte qu'on ait.
    """
    if version is not None:
        fige = instantane(type_demarche, version)
        if fige.fige and fige.gabarits is not None:
            return fige.gabarits
    return gabarits_demarche(type_demarche)


def rendre_gabarit(
    cle: str,
    slots: dict,
    type_demarche: str = TYPE_DEMARCHE_PAR_DEFAUT,
    version: int | None = None,
) -> Phrase | None:
    """
    Une phrase à trous, remplie avec les réponses du citoyen (étape 3.2).

    Le pulaar n'accompagne la phrase que si DEUX conditions sont réunies : le
    gabarit pulaar est relu, et toutes ses valeurs sont énonçables — une date
    illisible, par exemple, ne peut pas être dite. Sinon le français part au
    traducteur, comme avant.

    `None` quand même le français ne peut pas être rendu : mieux vaut ne rien
    dire que faire confirmer au citoyen un récapitulatif à trous.
    """
    ligne = gabarits_en_vigueur(type_demarche, version).get(cle)
    if ligne is None:
        return None
    definitions = champs(type_demarche, version)
    francais = gabarits.rendre(ligne.get("francais"), slots, definitions, gabarits.FRANCAIS)
    if francais is None:
        return None
    pulaar = None
    if ligne.get("pulaar_valide") and ligne.get("pulaar"):
        pulaar = gabarits.rendre(
            ligne["pulaar"], slots, definitions, gabarits.PULAAR,
            libelles_pulaar=libelles_enum_pulaar(),
        )
    return Phrase(
        francais=francais,
        pulaar=pulaar,
        pulaar_valide=bool(pulaar),
        origine=f"gabarit:{cle}",
    )


def relance_champ(ligne: dict, tentative: int) -> Phrase:
    """
    Ce que l'agent dit quand la réponse ne convient pas.

    Cette phrase était IMPROVISÉE par le modèle à chaque fois, donc traduite à
    la volée : le pire endroit pour du mauvais pulaar, puisque le citoyen ne
    comprenait déjà pas la question. Elle est désormais choisie à tour de rôle
    dans `demarche_champs.relances`. À défaut, la question elle-même est
    reposée — jamais rien d'inventé.
    """
    nom_champ = ligne.get("nom_champ", "?")
    relances = list(ligne.get("relances") or [])
    if not relances:
        return question_champ(ligne)
    index = max(tentative, 0) % len(relances)
    relances_pulaar = list(ligne.get("relances_pulaar") or [])
    return Phrase(
        francais=relances[index],
        pulaar=relances_pulaar[index] if index < len(relances_pulaar) else None,
        pulaar_valide=valide_au_rang(ligne, "relances_pulaar_valide", index),
        origine=f"champ:{nom_champ}:relance{index}",
    )
