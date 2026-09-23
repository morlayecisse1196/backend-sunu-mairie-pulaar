"""
Brouillon d'une démarche (plan maître, étape 4.4).

Le brouillon existait déjà sans porter de nom. Depuis l'étape 2.4, un dialogue
retient au démarrage le numéro de la version PUBLIÉE et lit l'instantané figé
(`demarche_versions`) : les tables vivantes, celles que l'éditeur et l'atelier
modifient, ne touchent donc aucun citoyen avant la publication suivante.

Ce qui manquait, c'est de le VOIR. L'écran affirmait « une modification prend
effet sur les prochaines conversations » — c'était faux, et un agent qui
corrige une question, ne l'entend pas au téléphone, en conclut que l'outil ne
marche pas. Ce module dit ce qui attend d'être publié, et permet d'y renoncer.

CE QUE CE MODULE NE COUVRE PAS

Les phrases système (`phrases_systeme` : accueil, « pouvez-vous répéter ? »…).
Elles n'appartiennent à aucune démarche, ne sont pas versionnées, et une
correction de l'atelier s'y entend tout de suite.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from services import demarche
from services.journal import obtenir_logger
from supabase_client import get_supabase_client

log = obtenir_logger("brouillon")

#: famille -> (table, colonne qui identifie la ligne, clé dans l'instantané)
FAMILLES = {
    "champ": ("demarche_champs", "nom_champ", "champs"),
    "document": ("demarche_documents", "type_document", "documents"),
    "regle": ("demarche_regles", "code", "regles"),
    "cas": ("demarche_cas", "code", "cas"),
    "gabarit": ("demarche_gabarits", "cle", "gabarits"),
}

#: Colonnes qui ne disent rien de ce que le citoyen entend. Les fichiers audio
#: en font partie : ils suivent le texte (clé = empreinte du texte, et le
#: déclencheur de la migration 022 les efface quand le pulaar change).
TECHNIQUES = frozenset({
    "id", "created_at", "updated_at", "type_demarche",
    "question_audio", "message_audio", "audio",
})

AJOUTE, RETIRE, MODIFIE = "ajoute", "retire", "modifie"


@dataclass(frozen=True)
class Ecart:
    famille: str
    cle: str
    nature: str
    colonnes: tuple[str, ...] = ()

    def en_dict(self) -> dict:
        return {"famille": self.famille, "cle": self.cle, "nature": self.nature,
                "colonnes": list(self.colonnes)}


@dataclass
class Etat:
    """Où en est le brouillon par rapport à la version publiée."""

    version_publiee: int | None
    ecarts: list[Ecart] = field(default_factory=list)
    #: La version publiée ne contient pas les gabarits (publiée avant 4.4).
    gabarits_non_figes: bool = False

    @property
    def a_publier(self) -> bool:
        return self.version_publiee is None or bool(self.ecarts) or self.gabarits_non_figes

    def en_dict(self) -> dict:
        return {
            "version_publiee": self.version_publiee,
            "ecarts": [e.en_dict() for e in self.ecarts],
            "gabarits_non_figes": self.gabarits_non_figes,
            "a_publier": self.a_publier,
        }


def _publiee(type_demarche: str) -> demarche.Instantane | None:
    """L'instantané de la dernière version publiée, ou `None` s'il n'y en a pas."""
    lignes = demarche.lire_strictement("demarche_definitions", type_demarche=type_demarche)
    if not lignes:
        return None
    version = int(lignes[0].get("version") or 1)
    publiees = demarche.lire_strictement(
        "demarche_versions", type_demarche=type_demarche, version=version)
    if not publiees:
        return None
    # Relue ici, pas via `demarche.instantane` : son cache peut contenir un
    # repli sur le vivant, et comparer le brouillon à lui-même ne montrerait
    # aucun écart.
    return demarche.instantane_publie(publiees[0])


def _par_cle(lignes, colonne: str) -> dict[str, dict]:
    return {l.get(colonne): l for l in lignes or []}


def _colonnes_changees(publiee: dict, vivante: dict) -> tuple[str, ...]:
    """
    Seules les colonnes présentes DES DEUX CÔTÉS se comparent.

    Une colonne ajoutée par une migration postérieure à la publication
    (les drapeaux de la 024, par exemple) est absente de l'instantané. La
    comparer à `None` signalerait un changement que personne n'a fait.
    """
    communes = (set(publiee) & set(vivante)) - TECHNIQUES
    return tuple(sorted(c for c in communes if publiee.get(c) != vivante.get(c)))


def etat(type_demarche: str = demarche.TYPE_DEMARCHE_PAR_DEFAUT) -> Etat:
    """Ce qui attend d'être publié. Lève `LectureImpossible` plutôt que de deviner."""
    publiee = _publiee(type_demarche)
    if publiee is None:
        return Etat(version_publiee=None)

    resultat = Etat(version_publiee=publiee.version,
                    gabarits_non_figes=publiee.gabarits is None)
    for famille, (table, colonne, attribut) in FAMILLES.items():
        lignes_publiees = getattr(publiee, attribut)
        if lignes_publiees is None:  # gabarits d'une version d'avant 4.4
            continue
        if isinstance(lignes_publiees, dict):
            lignes_publiees = list(lignes_publiees.values())
        avant = _par_cle(lignes_publiees, colonne)
        apres = _par_cle(demarche.lire_strictement(table, type_demarche=type_demarche), colonne)
        for cle in sorted(set(avant) | set(apres), key=str):
            if cle not in avant:
                resultat.ecarts.append(Ecart(famille, cle, AJOUTE))
            elif cle not in apres:
                resultat.ecarts.append(Ecart(famille, cle, RETIRE))
            else:
                colonnes = _colonnes_changees(avant[cle], apres[cle])
                if colonnes:
                    resultat.ecarts.append(Ecart(famille, cle, MODIFIE, colonnes))
    return resultat


class AbandonImpossible(RuntimeError):
    pass


def abandonner(type_demarche: str = demarche.TYPE_DEMARCHE_PAR_DEFAUT,
               *, par: str | None = None) -> int:
    """
    Remet les tables vivantes dans l'état de la version publiée.

    Retourne le nombre d'éléments remis en place. Les écritures d'abord, les
    suppressions en dernier : si la base tombe au milieu, on a perdu le moins
    possible. Un abandon interrompu laisse un brouillon partiellement
    restauré — jamais publié, puisque la publication repasse par le
    vérificateur.

    Refusé quand il n'y a pas de version publiée à restaurer, ou qu'elle ne
    contient aucun champ : remettre une démarche « à zéro » n'est pas un
    abandon de brouillon, c'est une suppression.
    """
    publiee = _publiee(type_demarche)
    if publiee is None:
        raise AbandonImpossible("Aucune version publiée à restaurer.")
    if not publiee.champs:
        raise AbandonImpossible(
            f"La version {publiee.version} ne contient aucun champ : la restaurer viderait la démarche.")

    client = get_supabase_client()
    remis = 0
    a_retirer: list[tuple[str, str, str]] = []
    for famille, (table, colonne, attribut) in FAMILLES.items():
        lignes_publiees = getattr(publiee, attribut)
        if lignes_publiees is None:
            # Version d'avant 4.4 : on ignore ce que disaient les gabarits.
            # Les laisser tels quels est le seul choix honnête.
            continue
        if isinstance(lignes_publiees, dict):
            lignes_publiees = list(lignes_publiees.values())
        avant = _par_cle(lignes_publiees, colonne)
        apres = _par_cle(demarche.lire_strictement(table, type_demarche=type_demarche), colonne)
        # Une colonne supprimée du schéma depuis la publication ferait échouer
        # l'écriture : on n'écrit que celles que la table a encore.
        colonnes_existantes = set().union(*apres.values()) if apres else None

        for cle, ligne in avant.items():
            a_ecrire = {c: v for c, v in ligne.items()
                        if c not in TECHNIQUES
                        and (colonnes_existantes is None or c in colonnes_existantes)}
            if cle not in apres:
                client.table(table).insert({**a_ecrire, "type_demarche": type_demarche}).execute()
                remis += 1
            elif _colonnes_changees(ligne, apres[cle]):
                client.table(table).update(a_ecrire).eq("type_demarche", type_demarche).eq(
                    colonne, cle).execute()
                remis += 1
        a_retirer.extend((table, colonne, cle) for cle in apres if cle not in avant)

    for table, colonne, cle in a_retirer:
        client.table(table).delete().eq("type_demarche", type_demarche).eq(colonne, cle).execute()
        remis += 1

    demarche.vider_cache()
    log.warning("Brouillon de %r abandonné par %s : %s élément(s) remis à la version %s.",
                type_demarche, par or "inconnu", remis, publiee.version)
    return remis
