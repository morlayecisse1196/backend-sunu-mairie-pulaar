"""
Édition d'une démarche : vérifier d'abord, écrire ensuite (étape 4.1).

CE QUI REND CET ÉCRAN DANGEREUX

Une démarche est le script d'une conversation avec quelqu'un qui ne sait pas
lire. Une modification fautive ne fait pas planter le serveur : elle DÉRAILLE
un dialogue, en silence, devant un citoyen qui n'a aucun moyen de comprendre
ce qui se passe ni de le signaler.

Renommer un champ laisse les conditions qui le citent parler d'un champ qui
n'existe plus — et `evaluer()`, par conception, ne lève jamais : elle rend
INCONNU, l'agent pose une question hors sujet et personne n'est alerté.
Supprimer le cas par défaut laisse des dossiers sans cas légal. Enlever une
accolade du récapitulatif le rend irrendable, donc muet, au moment précis où
le citoyen doit confirmer ce qui ira sur un acte d'état civil.

D'OÙ LA FORME DE CE MODULE

Toute écriture passe par `_verifier`, qui travaille sur la démarche TELLE
QU'ELLE SERAIT APRÈS la modification. Un problème BLOQUANT refuse l'écriture ;
un AVERTISSEMENT la laisse passer mais remonte à l'écran. Vérifier après coup
ne servirait à rien : le dialogue suivant est déjà parti.

LE FRANÇAIS ET LE PULAAR VONT ENSEMBLE

Changer le texte français d'une question retire sa relecture pulaar. Le
relecteur avait approuvé une traduction DE L'ANCIEN TEXTE ; elle ne traduit
plus rien. Même règle que dans l'atelier, pour la même raison.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services import conditions, demarche, gabarits
from services.journal import obtenir_logger
from supabase_client import get_supabase_client

log = obtenir_logger("editeur")

BLOQUANT = "bloquant"
AVERTISSEMENT = "avertissement"

#: Les types que le reste du code sait énoncer et comparer
#: (cf. `services/gabarits.py` et `services/conditions.py`).
TYPES_VALEUR = ("texte", "date", "age", "booleen", "nombre", "enum")

#: Le texte français d'une phrase, et la relecture pulaar qui en dépend.
#: Changer l'un retire l'autre.
TEXTES_ET_RELECTURE = {
    "demarche_champs": ("question", "pulaar_valide"),
    "demarche_documents": ("message_demande", "pulaar_valide"),
    "demarche_gabarits": ("francais", "pulaar_valide"),
}


@dataclass(frozen=True)
class Probleme:
    gravite: str
    #: Identifiant de l'élément fautif (`champ:nom_enfant`, `cas:tardif`…),
    #: pour que l'interface puisse y emmener directement.
    ou: str
    message: str

    def en_dict(self) -> dict:
        return {"gravite": self.gravite, "ou": self.ou, "message": self.message}


def _bloquant(ou: str, message: str) -> Probleme:
    return Probleme(BLOQUANT, ou, message)


def _avertissement(ou: str, message: str) -> Probleme:
    return Probleme(AVERTISSEMENT, ou, message)


# ============================================================================
# Vérification
# ============================================================================


def _verifier_conditions(
    lignes: list[dict], prefixe: str, cle: str, noms_champs: set[str]
) -> list[Probleme]:
    """Une condition doit s'analyser ET ne citer que des champs qui existent."""
    problemes: list[Probleme] = []
    for ligne in lignes:
        expression = (ligne.get("condition") or "").strip()
        if not expression:
            continue
        ou = f"{prefixe}:{ligne.get(cle, '?')}"
        try:
            conditions.analyser(expression)
        except conditions.ConditionInvalide as exc:
            problemes.append(_bloquant(ou, f"Condition impossible à lire : {exc}"))
            continue
        inconnus = sorted(conditions.champs_utilises(expression) - noms_champs)
        if inconnus:
            # Le piège : `evaluer()` ne lève jamais. Un champ inexistant rend
            # INCONNU, la condition ne se déclenche jamais, et rien ne le dit.
            problemes.append(_bloquant(
                ou,
                f"La condition parle de {', '.join(inconnus)}, qui n'existe pas dans cette "
                f"démarche. Elle ne se déclencherait jamais, sans erreur visible.",
            ))
    return problemes


def _verifier_champs(champs: list[dict]) -> list[Probleme]:
    problemes: list[Probleme] = []
    vus: dict[str, int] = {}
    ordres: dict[int, list[str]] = {}

    for champ in champs:
        nom = (champ.get("nom_champ") or "").strip()
        ou = f"champ:{nom or '?'}"
        if not nom:
            problemes.append(_bloquant("champ:?", "Un champ n'a pas de nom."))
            continue
        if not nom.replace("_", "a").isalnum() or nom[0].isdigit():
            # Le tokeniseur des conditions n'accepte que ces noms-là ; un nom
            # exotique rendrait le champ inutilisable dans toute condition.
            problemes.append(_bloquant(
                ou, f"« {nom} » ne peut pas être cité dans une condition. "
                    f"Lettres, chiffres et tirets bas uniquement, sans chiffre en tête."))
        vus[nom] = vus.get(nom, 0) + 1
        if not (champ.get("question") or "").strip():
            problemes.append(_bloquant(
                ou, "Ce champ n'a pas de question : l'agent resterait muet en arrivant dessus."))
        if champ.get("type_valeur") not in TYPES_VALEUR:
            problemes.append(_bloquant(
                ou, f"Type « {champ.get('type_valeur')} » inconnu. "
                    f"Attendu : {', '.join(TYPES_VALEUR)}."))
        elif champ.get("type_valeur") == "enum" and len(
                [v for v in (champ.get("regle_validation") or "").split("|") if v.strip()]) < 2:
            # Sans liste, toute réponse serait refusée : le citoyen tournerait
            # en rond sur cette question jusqu'à l'abandon.
            problemes.append(_bloquant(
                ou, "Un choix doit lister au moins deux valeurs, séparées par « | »."))
        if not (champ.get("relances") or []):
            problemes.append(_avertissement(
                ou, "Aucune relance : si la réponse ne convient pas, l'agent reposera la "
                    "question à l'identique."))
        ordres.setdefault(champ.get("ordre", 0), []).append(nom)

    for nom, fois in vus.items():
        if fois > 1:
            problemes.append(_bloquant(
                f"champ:{nom}", f"Le nom « {nom} » est utilisé {fois} fois. "
                                f"Les réponses de l'un écraseraient celles de l'autre."))
    for ordre, noms in ordres.items():
        if len(noms) > 1:
            problemes.append(_avertissement(
                f"champ:{noms[0]}",
                f"{', '.join(noms)} ont le même rang ({ordre}) : leur ordre de passage "
                f"n'est pas déterminé."))
    return problemes


def _verifier_documents(documents: list[dict], noms_champs: set[str]) -> list[Probleme]:
    problemes: list[Probleme] = []
    for document in documents:
        type_document = (document.get("type_document") or "").strip()
        ou = f"document:{type_document or '?'}"
        if not type_document:
            problemes.append(_bloquant("document:?", "Une pièce n'a pas de type."))
            continue
        if not (document.get("message_demande") or "").strip():
            problemes.append(_bloquant(
                ou, "Aucun message de demande : l'agent ne saurait pas réclamer cette pièce."))
        apres = document.get("apres_champ")
        if apres and apres not in noms_champs:
            problemes.append(_bloquant(
                ou, f"Cette pièce est demandée après « {apres} », qui n'existe pas. "
                    f"Elle ne serait jamais réclamée."))
        if not (document.get("messages_rappel") or []):
            problemes.append(_avertissement(
                ou, "Aucun rappel : l'agent répétera toujours la même phrase, et le citoyen "
                    "aura l'impression de ne pas être entendu."))
    return problemes


def _verifier_cas(cas: list[dict]) -> list[Probleme]:
    """
    Le dernier cas doit être INCONDITIONNEL.

    `determiner_cas` parcourt les cas dans l'ordre et s'arrête au premier
    certainement vrai. Sans cas de repli, un dossier qui ne correspond à aucune
    condition n'a pas de cas légal du tout — et c'est le cas légal qui décide
    des pièces à fournir.
    """
    problemes: list[Probleme] = []
    if not cas:
        return [_bloquant("cas:?", "Aucun cas légal défini : aucun dossier ne pourrait être classé.")]

    ordonnes = sorted(cas, key=lambda c: c.get("ordre", 0))
    defaut = [c for c in ordonnes if not (c.get("condition") or "").strip()]
    if not defaut:
        problemes.append(_bloquant(
            f"cas:{ordonnes[-1].get('code', '?')}",
            "Aucun cas par défaut : un dossier qui ne remplit aucune condition resterait "
            "sans cas légal, et les pièces à fournir en dépendent."))
    else:
        rang_defaut = ordonnes.index(defaut[0])
        inatteignables = ordonnes[rang_defaut + 1:]
        for ligne in inatteignables:
            problemes.append(_avertissement(
                f"cas:{ligne.get('code', '?')}",
                f"Placé après le cas par défaut « {defaut[0].get('code')} », ce cas ne sera "
                f"jamais atteint."))
        if len(defaut) > 1:
            problemes.append(_avertissement(
                f"cas:{defaut[1].get('code', '?')}",
                "Plusieurs cas sans condition : seul le premier servira."))

    codes = [c.get("code") for c in cas]
    for code in set(codes):
        if codes.count(code) > 1:
            problemes.append(_bloquant(f"cas:{code}", f"Le code « {code} » apparaît plusieurs fois."))
    return problemes


def _verifier_gabarits(lignes: list[dict], noms_champs: set[str]) -> list[Probleme]:
    problemes: list[Probleme] = []
    for ligne in lignes:
        cle = ligne.get("cle", "?")
        for langue, colonne in (("français", "francais"), ("pulaar", "pulaar")):
            texte = ligne.get(colonne) or ""
            if not texte.strip():
                if colonne == "francais":
                    problemes.append(_bloquant(f"gabarit:{cle}", "Gabarit vide."))
                continue
            inconnus = sorted(set(gabarits.trous(texte)) - noms_champs)
            if inconnus:
                problemes.append(_bloquant(
                    f"gabarit:{cle}",
                    f"Le gabarit {langue} cite {', '.join(inconnus)}, qui n'existe pas. "
                    f"La phrase ne pourrait pas être dite du tout."))
    return problemes


def _verifier_definition(definition: dict, champs: list[dict]) -> list[Probleme]:
    problemes: list[Probleme] = []
    champ_age = definition.get("champ_age")
    if champ_age:
        correspondant = next((c for c in champs if c.get("nom_champ") == champ_age), None)
        if correspondant is None:
            problemes.append(_bloquant(
                "demarche", f"Le champ d'âge « {champ_age} » n'existe pas."))
        elif correspondant.get("type_valeur") != "age":
            problemes.append(_avertissement(
                "demarche",
                f"Le champ d'âge « {champ_age} » est de type "
                f"« {correspondant.get('type_valeur')} », pas « age »."))
    if not (definition.get("libelle") or "").strip():
        # C'est le nom sous lequel la démarche est proposée au citoyen, et
        # celui que le modèle recopie pour dire laquelle commencer (étape 5.2).
        problemes.append(_bloquant(
            "demarche", "Cette démarche n'a pas de nom : rien ne permettrait de la proposer."))
    if definition.get("traitable") and not definition.get("mots_cles"):
        problemes.append(_bloquant(
            "demarche",
            "Aucun mot-clé : le dialogue ne saurait jamais reconnaître cette démarche "
            "quand un citoyen la demande."))
    return problemes


def _verifier(
    definition: dict, champs: list[dict], documents: list[dict],
    cas: list[dict], regles: list[dict], lignes_gabarits: list[dict],
) -> list[Probleme]:
    """La démarche entière, telle qu'elle serait. Fonction pure, donc testable."""
    noms = {(c.get("nom_champ") or "").strip() for c in champs if (c.get("nom_champ") or "").strip()}
    return [
        *_verifier_definition(definition, champs),
        *_verifier_champs(champs),
        *_verifier_documents(documents, noms),
        *_verifier_cas(cas),
        *_verifier_gabarits(lignes_gabarits, noms),
        *_verifier_conditions(champs, "champ", "nom_champ", noms),
        *_verifier_conditions(documents, "document", "type_document", noms),
        *_verifier_conditions(cas, "cas", "code", noms),
        *_verifier_conditions(regles, "regle", "code", noms),
    ]


def verifier(type_demarche: str = demarche.TYPE_DEMARCHE_PAR_DEFAUT) -> list[Probleme]:
    """Les problèmes de la démarche telle qu'elle est en base, maintenant."""
    vivant = demarche.instantane(type_demarche)
    return _verifier(
        {
            "libelle": vivant.definition.libelle,
            "champ_age": vivant.definition.champ_age,
            "traitable": vivant.definition.traitable,
            "mots_cles": list(vivant.definition.mots_cles),
        },
        vivant.champs, vivant.documents, vivant.cas, vivant.regles,
        list(demarche.gabarits_demarche(type_demarche).values()),
    )


# ============================================================================
# Écriture
# ============================================================================

#: Comment retrouver une ligne, par famille.
CLES = {
    "champ": ("demarche_champs", "nom_champ"),
    "document": ("demarche_documents", "type_document"),
    "cas": ("demarche_cas", "code"),
    "regle": ("demarche_regles", "code"),
    "gabarit": ("demarche_gabarits", "cle"),
}


class EditionRefusee(ValueError):
    """Porte les problèmes qui ont fait refuser l'écriture."""

    def __init__(self, problemes: list[Probleme]):
        self.problemes = problemes
        super().__init__(" ; ".join(p.message for p in problemes))


def _projeter(famille: str, cle_valeur: str, valeurs: dict | None,
              type_demarche: str) -> tuple[dict, list, list, list, list, list]:
    """
    La démarche telle qu'elle serait après cette modification.

    `cle_valeur` dit QUELLE ligne est touchée ; `valeurs` dit ce qui change —
    y compris, éventuellement, la clé elle-même. Les confondre revenait à
    réécrire l'ancien nom par-dessus le nouveau : un renommage était accepté,
    annoncé comme enregistré, et n'arrivait jamais en base.
    """
    vivant = demarche.instantane(type_demarche)
    tables = {
        "champ": list(vivant.champs),
        "document": list(vivant.documents),
        "cas": list(vivant.cas),
        "regle": list(vivant.regles),
        "gabarit": list(demarche.gabarits_demarche(type_demarche).values()),
    }
    _table, colonne = CLES[famille]
    lignes = tables[famille]
    reste = [l for l in lignes if l.get(colonne) != cle_valeur]
    ancienne = next((l for l in lignes if l.get(colonne) == cle_valeur), None)
    if valeurs is not None:
        nouvelle = {**(ancienne or {}), **valeurs}
        nouvelle.setdefault(colonne, cle_valeur)
        reste.append(nouvelle)
    tables[famille] = reste
    definition = {
        "libelle": vivant.definition.libelle,
        "champ_age": vivant.definition.champ_age,
        "traitable": vivant.definition.traitable,
        "mots_cles": list(vivant.definition.mots_cles),
    }
    return (definition, tables["champ"], tables["document"], tables["cas"],
            tables["regle"], tables["gabarit"])


def _refuser_si_casse(projection) -> list[Probleme]:
    problemes = _verifier(*projection)
    bloquants = [p for p in problemes if p.gravite == BLOQUANT]
    if bloquants:
        raise EditionRefusee(bloquants)
    return problemes


def _retirer_relecture_si_le_francais_change(
    table: str, valeurs: dict, ancienne: dict | None
) -> None:
    """
    Le pulaar traduisait l'ANCIEN français. Il ne traduit plus rien.

    Le laisser marqué « relu » ferait dire au citoyen, en pulaar validé, une
    phrase qui ne correspond plus à la question posée. Même règle que dans
    l'atelier (`services/atelier.py`).
    """
    paire = TEXTES_ET_RELECTURE.get(table)
    if paire is None or ancienne is None:
        return
    colonne_texte, colonne_relecture = paire
    if colonne_texte not in valeurs:
        return
    if (valeurs[colonne_texte] or "").strip() != (ancienne.get(colonne_texte) or "").strip():
        valeurs[colonne_relecture] = False
        log.info("Relecture pulaar retirée : le français de %r a changé.", ancienne.get(colonne_texte, "")[:40])


def enregistrer(
    famille: str, cle_valeur: str, valeurs: dict,
    *, type_demarche: str = demarche.TYPE_DEMARCHE_PAR_DEFAUT,
) -> list[Probleme]:
    """
    Crée ou modifie un élément, après vérification de la démarche entière.

    Retourne les AVERTISSEMENTS restants — ce qui mérite d'être vu sans
    empêcher d'avancer. Lève `EditionRefusee` sur un problème bloquant, sans
    rien écrire.
    """
    if famille not in CLES:
        raise ValueError(f"Famille inconnue : {famille!r}")
    table, colonne = CLES[famille]
    avertissements = _refuser_si_casse(_projeter(famille, cle_valeur, valeurs, type_demarche))

    client = get_supabase_client()
    existantes = [l for l in _lignes(famille, type_demarche) if l.get(colonne) == cle_valeur]
    ancienne = existantes[0] if existantes else None
    # `valeurs` l'emporte sur la clé d'identification : c'est ce qui rend un
    # renommage possible. La clé ne sert qu'à retrouver la ligne à modifier.
    a_ecrire = {colonne: cle_valeur, **valeurs, "type_demarche": type_demarche}
    _retirer_relecture_si_le_francais_change(table, a_ecrire, ancienne)

    if ancienne is None:
        client.table(table).insert(a_ecrire).execute()
    else:
        client.table(table).update(a_ecrire).eq("type_demarche", type_demarche).eq(
            colonne, cle_valeur).execute()
    demarche.vider_cache()
    return avertissements


def supprimer(
    famille: str, cle_valeur: str,
    *, type_demarche: str = demarche.TYPE_DEMARCHE_PAR_DEFAUT,
) -> list[Probleme]:
    """
    Retire un élément — si rien d'autre n'en dépend.

    C'est la modification la plus risquée : supprimer un champ cité par une
    condition ou par le récapitulatif ne casse rien de visible ici, et casse
    tout dans le dialogue.
    """
    if famille not in CLES:
        raise ValueError(f"Famille inconnue : {famille!r}")
    table, colonne = CLES[famille]
    avertissements = _refuser_si_casse(_projeter(famille, cle_valeur, None, type_demarche))
    get_supabase_client().table(table).delete().eq("type_demarche", type_demarche).eq(
        colonne, cle_valeur).execute()
    demarche.vider_cache()
    return avertissements


def reordonner(
    famille: str, cles_dans_l_ordre: list[str],
    *, type_demarche: str = demarche.TYPE_DEMARCHE_PAR_DEFAUT,
) -> None:
    """
    Renumérote une famille d'après l'ordre donné.

    Les rangs sont espacés de 10 : insérer un élément entre deux autres reste
    possible sans tout renuméroter.
    """
    if famille not in CLES:
        raise ValueError(f"Famille inconnue : {famille!r}")
    table, colonne = CLES[famille]
    connues = {l.get(colonne) for l in _lignes(famille, type_demarche)}
    inconnues = [c for c in cles_dans_l_ordre if c not in connues]
    if inconnues:
        raise ValueError(f"Élément(s) inconnu(s) : {', '.join(inconnues)}")
    oubliees = sorted(connues - set(cles_dans_l_ordre))
    if oubliees:
        # Réordonner une liste partielle laisserait les absents à leur ancien
        # rang, donc à une place arbitraire dans la nouvelle séquence.
        raise ValueError(f"Élément(s) absent(s) de l'ordre donné : {', '.join(oubliees)}")

    client = get_supabase_client()
    for rang, cle in enumerate(cles_dans_l_ordre, start=1):
        client.table(table).update({"ordre": rang * 10}).eq(
            "type_demarche", type_demarche).eq(colonne, cle).execute()
    demarche.vider_cache()


def _lignes(famille: str, type_demarche: str) -> list[dict]:
    vivant = demarche.instantane(type_demarche)
    return {
        "champ": vivant.champs,
        "document": vivant.documents,
        "cas": vivant.cas,
        "regle": vivant.regles,
        "gabarit": list(demarche.gabarits_demarche(type_demarche).values()),
    }[famille]


def sequence(type_demarche: str = demarche.TYPE_DEMARCHE_PAR_DEFAUT) -> list[dict]:
    """
    Le déroulé du dialogue, champs et pièces mêlés dans l'ordre réel.

    Un champ et une pièce se lisent dans deux tables différentes, mais le
    citoyen, lui, les rencontre dans une seule suite. Éditer la séquence sans
    la voir telle qu'elle se déroule, c'est éditer à l'aveugle.
    """
    etapes: list[dict] = []
    for champ in demarche.champs(type_demarche):
        etapes.append({
            "genre": "champ",
            "cle": champ.get("nom_champ"),
            "ordre": champ.get("ordre", 0),
            "libelle": champ.get("question") or champ.get("nom_champ"),
            "type_valeur": champ.get("type_valeur"),
            "obligatoire": bool(champ.get("obligatoire", True)),
            "condition": champ.get("condition"),
        })
    for document in demarche.documents(type_demarche):
        etapes.append({
            "genre": "document",
            "cle": document.get("type_document"),
            "ordre": document.get("ordre", 0),
            "libelle": document.get("message_demande") or document.get("type_document"),
            "apres_champ": document.get("apres_champ"),
            "obligatoire": bool(document.get("obligatoire", True)),
            "condition": document.get("condition"),
        })
    return sorted(etapes, key=lambda e: (e["ordre"], e["genre"]))
