"""
Atelier pulaar : ce qui est à relire, et comment le ranger (étape 4.2).

POURQUOI UN SERVICE

Cette logique vivait dans `scripts/atelier_pulaar.py`. Un script ne se teste
pas : c'est là qu'un gabarit est resté invisible à la relecture pendant deux
étapes sans que rien ne le signale. Elle est maintenant ici, testée, et le
script comme l'interface web en sont de simples appelants.

CE QU'UNE PHRASE PORTE

Son identifiant — stable, c'est lui qui dit où la remettre en base — son
français, son pulaar actuel, l'état de sa relecture, et le contexte SANS
lequel une traduction est un pari : « C'est noté » se traduit autrement selon
qu'on confirme une réponse ou qu'on clôt un dossier.

CE QUI N'EST JAMAIS FAIT ICI

Marquer validée une phrase vide. `pulaar_valide` est la seule chose qui
distingue, dans tout le système, une phrase qu'un humain a lue d'une
traduction automatique déposée en attendant. Une case cochée sur du vide lui
ferait perdre ce sens.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services import catalogue_audio, demarche
from services.journal import obtenir_logger
from supabase_client import get_supabase_client

log = obtenir_logger("atelier")

#: Où va l'audio pré-généré selon la table — `None` quand la table n'a pas de
#: colonne pour le porter (relances, rappels : l'empreinte du texte suffit,
#: cf. `services/catalogue_audio.cle_phrase`).
COLONNE_AUDIO = {
    "phrases_systeme": "audio",
    "demarche_champs": "question_audio",
    "demarche_documents": "message_audio",
    "demarche_gabarits": None,  # texte à trous : jamais pré-généré
}

#: Le tableau de drapeaux qui accompagne un tableau de traductions
#: (migration 024). Valider la relance n°1 ne doit pas valider la question.
COLONNE_DRAPEAUX = {
    "relances_pulaar": "relances_pulaar_valide",
    "messages_rappel_pulaar": "messages_rappel_pulaar_valide",
}


@dataclass(frozen=True)
class Cible:
    """Où se range une traduction : table, ligne, colonne, et rang si liste."""

    table: str
    colonne_cle: str
    valeur_cle: str
    colonne: str
    index: int | None = None


@dataclass(frozen=True)
class Phrase:
    identifiant: str
    francais: str
    pulaar: str
    valide: bool
    contexte: str
    cible: Cible
    #: L'audio de CE texte exact existe-t-il déjà (étape 3.4) ?
    audio_pret: bool = False

    def en_dict(self) -> dict[str, Any]:
        """Forme transmise à l'interface web."""
        return {
            "identifiant": self.identifiant,
            "francais": self.francais,
            "pulaar": self.pulaar,
            "valide": self.valide,
            "contexte": self.contexte,
            "audio_pret": self.audio_pret,
            "a_des_trous": "{" in self.francais,
        }


def _phrase(identifiant, francais, pulaar, valide, contexte, cible) -> Phrase:
    return Phrase(
        identifiant=identifiant,
        francais=francais or "",
        pulaar=pulaar or "",
        valide=bool(valide),
        contexte=contexte or "",
        cible=cible,
        audio_pret=catalogue_audio.phrase_deja_generee(pulaar or ""),
    )


def collecter(type_demarche: str = demarche.TYPE_DEMARCHE_PAR_DEFAUT) -> list[Phrase]:
    """
    Toutes les phrases dites au citoyen pour cette démarche.

    L'ordre suit celui du dialogue : questions et relances d'un champ
    ensemble, puis les pièces, puis le récapitulatif, puis les phrases
    système. Un relecteur qui descend la liste suit la conversation.
    """
    phrases: list[Phrase] = []

    for champ in demarche.champs(type_demarche):
        nom = champ["nom_champ"]
        valide = champ.get("pulaar_valide")
        phrases.append(_phrase(
            f"champ:{nom}:question", champ.get("question"), champ.get("question_pulaar"),
            valide, f"Question du champ « {nom} »",
            Cible("demarche_champs", "nom_champ", nom, "question_pulaar"),
        ))
        deja = list(champ.get("relances_pulaar") or [])
        for index, relance in enumerate(champ.get("relances") or []):
            phrases.append(_phrase(
                f"champ:{nom}:relance{index}", relance,
                deja[index] if index < len(deja) else "",
                demarche.valide_au_rang(champ, "relances_pulaar_valide", index),
                f"Relance {index + 1} du champ « {nom} », quand la réponse ne convient pas",
                Cible("demarche_champs", "nom_champ", nom, "relances_pulaar", index),
            ))

    for document in demarche.documents(type_demarche):
        type_document = document["type_document"]
        valide = document.get("pulaar_valide")
        phrases.append(_phrase(
            f"document:{type_document}:demande", document.get("message_demande"),
            document.get("message_demande_pulaar"), valide,
            f"Demande de la pièce « {type_document} »",
            Cible("demarche_documents", "type_document", type_document, "message_demande_pulaar"),
        ))
        deja = list(document.get("messages_rappel_pulaar") or [])
        for index, rappel in enumerate(document.get("messages_rappel") or []):
            phrases.append(_phrase(
                f"document:{type_document}:rappel{index}", rappel,
                deja[index] if index < len(deja) else "",
                demarche.valide_au_rang(document, "messages_rappel_pulaar_valide", index),
                f"Rappel {index + 1} pour la pièce « {type_document} »",
                Cible("demarche_documents", "type_document", type_document,
                      "messages_rappel_pulaar", index),
            ))

    for cle, ligne in sorted(demarche.gabarits_demarche(type_demarche).items()):
        phrases.append(_phrase(
            f"gabarit:{cle}", ligne.get("francais"), ligne.get("pulaar"),
            ligne.get("pulaar_valide"),
            (ligne.get("contexte") or "")
            + " ⚠️ Gardez les trous {nom_champ} tels quels : ils sont remplacés par "
              "les réponses du citoyen. Les traduire rendrait la phrase inutilisable.",
            Cible("demarche_gabarits", "cle", cle, "pulaar"),
        ))

    for ligne in sorted(demarche._phrases_systeme().values(), key=lambda l: l["cle"]):
        phrases.append(_phrase(
            f"systeme:{ligne['cle']}", ligne.get("francais"), ligne.get("pulaar"),
            ligne.get("pulaar_valide"), ligne.get("contexte"),
            Cible("phrases_systeme", "cle", ligne["cle"], "pulaar"),
        ))

    return [p for p in phrases if p.francais.strip()]


def _liste_actuelle(phrases: list[Phrase], cible: Cible) -> list[str]:
    """La liste complète (relances, rappels) telle qu'elle est en base."""
    rangs = {
        p.cible.index: p.pulaar
        for p in phrases
        if p.cible.table == cible.table
        and p.cible.valeur_cle == cible.valeur_cle
        and p.cible.colonne == cible.colonne
        and p.cible.index is not None
    }
    return [rangs.get(i, "") for i in range(max(rangs, default=-1) + 1)]


def _ou_trouver(identifiants: list[str], sauf: str) -> list[str]:
    """Les autres démarches qui connaissent ces phrases, pour le diagnostic."""
    trouvees: list[str] = []
    try:
        autres = [d.type_demarche for d in demarche.demarches_traitables()
                  if d.type_demarche != sauf]
    except Exception:  # noqa: BLE001
        return []
    for autre in autres:
        try:
            connues = {p.identifiant for p in collecter(autre)}
        except Exception:  # noqa: BLE001
            continue
        if any(i in connues for i in identifiants):
            trouvees.append(autre)
    return trouvees


def enregistrer(
    traductions: dict[str, str],
    *,
    valider: bool = False,
    par: str | None = None,
    type_demarche: str = demarche.TYPE_DEMARCHE_PAR_DEFAUT,
) -> dict[str, Any]:
    """
    Range des traductions, et retourne ce qui a été fait.

    `traductions` va de l'identifiant au texte pulaar. Un identifiant inconnu
    fait TOUT échouer sans rien écrire : si la première colonne d'un fichier a
    été modifiée, la traduction irait se ranger au mauvais endroit, et on
    l'entendrait seulement en dialogue.

    `valider` ne s'applique qu'aux phrases effectivement remplies.
    """
    connues = {p.identifiant: p for p in collecter(type_demarche)}
    inconnus = sorted(i for i in traductions if i not in connues)
    if inconnus:
        # Dire OÙ l'on a cherché : l'erreur la plus fréquente n'est pas une
        # faute de frappe, c'est une phrase demandée dans la mauvaise
        # démarche — et « identifiant inconnu » seul n'aide pas à le voir.
        ailleurs = _ou_trouver(inconnus, type_demarche)
        raise ValueError(
            f"Identifiant(s) inconnu(s) dans la démarche « {type_demarche} » : "
            + ", ".join(inconnus[:5]) + (" …" if len(inconnus) > 5 else "")
            + (f". Trouvé(s) dans : {', '.join(ailleurs)}." if ailleurs else "")
        )

    retenues = {i: t.strip() for i, t in traductions.items() if t and t.strip()}
    if not retenues:
        return {"phrases": 0, "lignes": 0, "validees": 0}

    toutes = list(connues.values())
    # Une même ligne de base porte plusieurs phrases (une question et ses
    # relances) : on regroupe pour n'écrire qu'une fois par ligne.
    groupes: dict[tuple[str, str, str], dict] = {}
    for identifiant, texte in retenues.items():
        cible = connues[identifiant].cible
        entree = groupes.setdefault(
            (cible.table, cible.colonne_cle, cible.valeur_cle), {"simples": {}, "listes": {}}
        )
        if cible.index is None:
            entree["simples"][cible.colonne] = texte
        else:
            entree["listes"].setdefault(cible.colonne, {})[cible.index] = texte

    brutes = {(p.cible.table, p.cible.valeur_cle): p for p in toutes}
    client = get_supabase_client()
    for (table, colonne_cle, valeur_cle), entree in groupes.items():
        donnees: dict[str, Any] = dict(entree["simples"])
        for colonne, par_rang in entree["listes"].items():
            actuelle = _liste_actuelle(toutes, Cible(table, colonne_cle, valeur_cle, colonne, 0))
            taille = max([*par_rang, len(actuelle) - 1, -1]) + 1
            liste = [actuelle[i] if i < len(actuelle) else "" for i in range(taille)]
            for rang, texte in par_rang.items():
                liste[rang] = texte
            donnees[colonne] = liste
            if valider and colonne in COLONNE_DRAPEAUX:
                donnees[COLONNE_DRAPEAUX[colonne]] = _drapeaux(
                    toutes, table, valeur_cle, colonne, set(par_rang), taille
                )
        # Le drapeau de LIGNE ne se pose que si une phrase de ligne — une
        # question, un message de demande — a été relue. Sinon valider une
        # relance validerait la question qui la précède, que personne n'a lue.
        if valider and entree["simples"]:
            donnees["pulaar_valide"] = True
        elif not valider:
            _retirer_validation(donnees, connues, entree, table, colonne_cle, valeur_cle, toutes)
        # L'audio pré-généré ne dit plus ce texte-ci. Le laisser ferait croire
        # à l'atelier qu'il n'y a rien à regénérer (étape 3.4).
        colonne_audio = COLONNE_AUDIO.get(table, "audio")
        if colonne_audio:
            donnees.setdefault(colonne_audio, None)
        client.table(table).update(donnees).eq(colonne_cle, valeur_cle).execute()

    _journaliser(retenues, connues, valider=valider, par=par, type_demarche=type_demarche)
    demarche.vider_cache()
    return {
        "phrases": len(retenues),
        "lignes": len(groupes),
        "validees": len(retenues) if valider else 0,
    }


def _retirer_validation(
    donnees: dict, connues: dict, entree: dict,
    table: str, colonne_cle: str, valeur_cle: str, toutes: list,
) -> None:
    """
    Un texte CHANGÉ sans être revalidé perd sa relecture.

    Le relecteur avait approuvé l'ancien texte ; celui-ci n'existe plus. Le
    laisser marqué « relu » ferait dire au citoyen une phrase que personne n'a
    jamais lue — c'est exactement ce qui est arrivé avec trois lignes d'un
    fichier mal formé, dont le pulaar était en réalité du français.

    Même raisonnement que pour l'audio pré-généré : ce qui a été validé, c'est
    un texte précis, pas un emplacement.
    """
    for colonne, texte in entree["simples"].items():
        ancienne = next(
            (p for p in toutes
             if p.cible.table == table and p.cible.valeur_cle == valeur_cle
             and p.cible.colonne == colonne and p.cible.index is None),
            None,
        )
        if ancienne is not None and ancienne.valide and texte != ancienne.pulaar.strip():
            donnees["pulaar_valide"] = False
            log.info("Relecture retirée : %r a changé sans être revalidée.", ancienne.identifiant)
            _figer_relectures_voisines(donnees, toutes, table, valeur_cle)

    for colonne, par_rang in entree["listes"].items():
        drapeaux_colonne = COLONNE_DRAPEAUX.get(colonne)
        if drapeaux_colonne is None:
            continue
        retires = {
            rang for rang, texte in par_rang.items()
            if any(p.cible.index == rang and p.valide and texte != p.pulaar.strip()
                   for p in toutes
                   if p.cible.table == table and p.cible.valeur_cle == valeur_cle
                   and p.cible.colonne == colonne)
        }
        if retires:
            taille = len(donnees[colonne])
            donnees[drapeaux_colonne] = [
                False if i in retires else _valide_connu(toutes, table, valeur_cle, colonne, i)
                for i in range(taille)
            ]


def _figer_relectures_voisines(donnees: dict, toutes: list, table: str, valeur_cle: str) -> None:
    """
    Retirer la relecture d'une QUESTION ne doit pas retirer celle de ses relances.

    Le drapeau de ligne vient de tomber. Or une relance sans drapeau par rang
    se rabat sur celui de la ligne (migration 024) : elle perdrait donc sa
    relecture sans que son texte ait bougé, et sans que personne ne l'ait
    demandé. On inscrit d'abord ce que ces relances valaient, pour qu'elles le
    gardent. Le sens va dans le seul sens acceptable : une phrase relue reste
    relue tant que SON texte n'a pas changé.
    """
    colonnes = {
        p.cible.colonne for p in toutes
        if p.cible.table == table and p.cible.valeur_cle == valeur_cle and p.cible.index is not None
    }
    for colonne in colonnes:
        drapeaux = COLONNE_DRAPEAUX.get(colonne)
        if drapeaux is None or drapeaux in donnees:
            continue
        rangs = [
            p.cible.index for p in toutes
            if p.cible.table == table and p.cible.valeur_cle == valeur_cle
            and p.cible.colonne == colonne
        ]
        if not rangs:
            continue
        donnees[drapeaux] = [
            _valide_connu(toutes, table, valeur_cle, colonne, i) for i in range(max(rangs) + 1)
        ]


def _valide_connu(toutes: list, table: str, valeur_cle: str, colonne: str, rang: int) -> bool:
    return any(
        p.cible.index == rang and p.valide
        for p in toutes
        if p.cible.table == table and p.cible.valeur_cle == valeur_cle and p.cible.colonne == colonne
    )


def _drapeaux(
    phrases: list[Phrase], table: str, valeur_cle: str, colonne: str,
    rangs_valides: set, taille: int,
) -> list[bool]:
    """
    Les drapeaux de relecture d'un tableau, après validation de certains rangs.

    Les rangs non touchés gardent ce qu'ils avaient. Un rang jamais décidé
    hérite de la relecture qu'on lui connaissait — sinon valider la relance
    n°2 ferait silencieusement RETIRER la relance n°1 du circuit.
    """
    connus = {
        p.cible.index: p.valide
        for p in phrases
        if p.cible.table == table and p.cible.valeur_cle == valeur_cle
        and p.cible.colonne == colonne and p.cible.index is not None
    }
    return [bool(i in rangs_valides or connus.get(i, False)) for i in range(taille)]


def _journaliser(
    retenues: dict[str, str],
    connues: dict[str, Phrase],
    *,
    valider: bool,
    par: str | None,
    type_demarche: str,
) -> None:
    """
    Garde trace de qui a relu quoi (étape 4.2, « historique »).

    Sans cela, `pulaar_valide` dit qu'une phrase a été relue mais pas par qui
    ni quand : impossible, trois mois plus tard, de savoir si une formulation
    contestée vient d'un locuteur ou d'une traduction automatique validée à la
    hâte. L'écriture est au mieux : perdre une ligne d'historique ne doit pas
    faire perdre une traduction.
    """
    lignes = [
        {
            "identifiant": identifiant,
            "type_demarche": type_demarche,
            "pulaar_avant": connues[identifiant].pulaar or None,
            "pulaar_apres": texte,
            "valide": bool(valider),
            "par": par or "inconnu",
        }
        for identifiant, texte in retenues.items()
        # Un texte inchangé qu'on ne revalide pas n'est PAS un événement :
        # réimporter le même fichier écrivait une ligne d'historique par
        # phrase, noyant les vraies corrections au milieu de 53 non-événements.
        if texte != connues[identifiant].pulaar
        or (valider and not connues[identifiant].valide)
    ]
    if not lignes:
        return
    try:
        get_supabase_client().table("atelier_historique").insert(lignes).execute()
    except Exception as exc:  # noqa: BLE001 — migration 023 pas encore appliquée, ou base capricieuse
        log.warning("Historique de l'atelier non écrit (%s) — les traductions sont enregistrées.", exc)


def historique(
    identifiant: str | None = None,
    type_demarche: str = demarche.TYPE_DEMARCHE_PAR_DEFAUT,
    limite: int = 50,
) -> list[dict]:
    """Les relectures passées, la plus récente d'abord."""
    try:
        requete = (
            get_supabase_client().table("atelier_historique").select("*")
            .eq("type_demarche", type_demarche)
        )
        if identifiant:
            requete = requete.eq("identifiant", identifiant)
        return requete.order("le", desc=True).limit(limite).execute().data or []
    except Exception as exc:  # noqa: BLE001
        log.warning("Historique de l'atelier illisible (%s).", exc)
        return []


def avancement(type_demarche: str = demarche.TYPE_DEMARCHE_PAR_DEFAUT) -> dict[str, int]:
    """Où en est la relecture — ce que l'interface affiche en tête."""
    phrases = collecter(type_demarche)
    relues = [p for p in phrases if p.valide and p.pulaar.strip()]
    return {
        "total": len(phrases),
        "relues": len(relues),
        "deposees": len([p for p in phrases if p.pulaar.strip() and not p.valide]),
        "vides": len([p for p in phrases if not p.pulaar.strip()]),
        "audios_prets": len([p for p in relues if p.audio_pret]),
    }
