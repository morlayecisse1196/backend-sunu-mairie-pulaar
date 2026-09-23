"""
Simulateur : jouer une démarche entière avant de la publier (étape 4.3).

POURQUOI

Vérifier une modification demandait un téléphone, un réseau, le service vocal
réveillé, et quelqu'un pour parler pulaar pendant dix minutes. Autant dire
qu'on ne vérifiait pas — on publiait, et on découvrait le problème dans un
vrai dialogue.

Le simulateur déroule la démarche avec les MÊMES fonctions que le dialogue
réel : `slot_controller.determiner_etape_courante` pour la séquence,
`valider_valeur` pour accepter ou refuser une réponse, `demarche.determiner_cas`
pour le cas légal, `demarche.rendre_gabarit` pour le récapitulatif. Simuler
avec un moteur différent ne prouverait rien.

CE QU'IL NE SIMULE PAS, ET IL FAUT LE SAVOIR

L'EXTRACTION. Dans un vrai dialogue, le citoyen parle et un modèle en tire la
valeur : « je crois qu'il est né un mardi de mars » devient — ou ne devient
pas — une date. Le simulateur reçoit la valeur déjà extraite. Il répond donc à
« ma démarche se déroule-t-elle correctement ? », pas à « le modèle comprend-il
mes concitoyens ? ». La deuxième question a besoin d'un vrai téléphone.

CE QU'IL DIT DE PLUS

Pour chaque phrase prononcée : passe-t-elle encore par le traducteur, et son
audio est-il prêt ? C'est le critère de vérification de l'étape 3 — « un
dialogue complet sans un seul appel de traduction » — rendu observable sans
décrocher un téléphone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import slot_controller
from services import catalogue_audio, demarche, regles_demarche
from services.journal import obtenir_logger
from services.phrases import Phrase

log = obtenir_logger("simulateur")

#: Garde-fou : une démarche mal formée peut boucler (une étape qui ne se
#: remplit jamais). Mieux vaut un rapport tronqué et explicite qu'une requête
#: qui ne revient pas.
TOURS_MAX = 100

QUESTION = "question"
PIECE = "piece"
REFUS = "refus"
RECAPITULATIF = "recapitulatif"
BLOCAGE = "blocage"
MANQUE = "manque"


@dataclass(frozen=True)
class Tour:
    """Un échange : ce que l'agent dit, ce que le citoyen répond."""

    genre: str
    cle: str
    dit: str
    #: Le pulaar relu, ou `None` si cette phrase repart au traducteur.
    pulaar: str | None
    audio_pret: bool
    origine: str
    repondu: Any = None
    accepte: bool = True
    motif: str | None = None

    def en_dict(self) -> dict:
        return {
            "genre": self.genre, "cle": self.cle, "dit": self.dit,
            "pulaar": self.pulaar, "audio_pret": self.audio_pret,
            "origine": self.origine, "repondu": self.repondu,
            "accepte": self.accepte, "motif": self.motif,
        }


@dataclass
class Rapport:
    tours: list[Tour] = field(default_factory=list)
    slots: dict = field(default_factory=dict)
    documents_recus: list[str] = field(default_factory=list)
    cas: str | None = None
    termine: bool = False
    #: Ce qui a arrêté la simulation avant la fin, en clair.
    arret: str | None = None

    @property
    def a_traduire(self) -> list[str]:
        """Les phrases qui repasseraient encore par le modèle."""
        return [t.origine for t in self.tours if t.pulaar is None]

    @property
    def sans_audio(self) -> list[str]:
        return [t.origine for t in self.tours if t.pulaar is not None and not t.audio_pret]

    def en_dict(self) -> dict:
        return {
            "tours": [t.en_dict() for t in self.tours],
            "slots": self.slots,
            "documents_recus": self.documents_recus,
            "cas": self.cas,
            "termine": self.termine,
            "arret": self.arret,
            "a_traduire": self.a_traduire,
            "sans_audio": self.sans_audio,
            "sans_traducteur": not self.a_traduire,
        }


def _tour(genre: str, cle: str, phrase: Phrase, **reste) -> Tour:
    pulaar = phrase.pulaar_pret()
    return Tour(
        genre=genre, cle=cle, dit=phrase.francais, pulaar=pulaar,
        audio_pret=bool(pulaar) and catalogue_audio.phrase_deja_generee(pulaar),
        origine=phrase.origine, **reste,
    )


def _blocage(rapport: Rapport, violation: regles_demarche.Violation) -> Rapport:
    # Ce que le citoyen entend vraiment : le message de la RÈGLE, qui
    # l'oriente vers la bonne procédure (slot_controller._resultat_blocage).
    # Afficher ici la phrase générique de blocage montrait un texte qu'il
    # n'entendrait jamais, et cachait celui qu'on voulait relire.
    phrase = Phrase(francais=violation.message, origine=f"regle:{violation.code}")
    rapport.tours.append(_tour(BLOCAGE, violation.code, phrase, motif=f"règle « {violation.code} »"))
    rapport.arret = f"Règle « {violation.code} » : {violation.message}"
    return rapport


def jouer(
    reponses: dict[str, Any],
    type_demarche: str = demarche.TYPE_DEMARCHE_PAR_DEFAUT,
    version: int | None = None,
    aujourdhui: date | None = None,
) -> Rapport:
    """
    Déroule la démarche avec le scénario donné.

    `reponses` va du nom de champ à ce que le citoyen répond — sous la forme
    où le modèle l'aurait extrait (une date en `AAAA-MM-JJ`, un âge en
    `{"valeur": 7, "unite": "jours"}`, « oui »/« non »…). Un type de pièce
    présent dans `reponses` avec une valeur vraie signifie « photo fournie ».

    La simulation s'arrête dès qu'une étape n'a pas de réponse au scénario :
    c'est une information, pas une erreur — elle dit jusqu'où le scénario mène.
    """
    instantane = demarche.instantane(type_demarche, version)
    rapport = Rapport(slots=demarche.slots_vides(type_demarche, version))
    documents_recus: set[str] = set()
    champs_ignores: set[str] = set()

    for _ in range(TOURS_MAX):
        # Les règles bloquantes d'abord : une démarche interdite ne doit pas
        # continuer à poser des questions (étape 2.1).
        violations = regles_demarche.evaluer_regles(
            instantane.regles, rapport.slots,
            effets=(regles_demarche.BLOQUER,), aujourdhui=aujourdhui,
        )
        if violations:
            return _blocage(rapport, violations[0])

        etape = slot_controller.determiner_etape_courante(
            rapport.slots, documents_recus, instantane.champs, instantane.documents,
            champs_ignores,
        )

        if etape is None:
            rapport.cas = demarche.determiner_cas(
                rapport.slots, type_demarche, version, aujourdhui)
            rapport.documents_recus = sorted(documents_recus)
            recapitulatif = demarche.rendre_gabarit(
                "recapitulatif", rapport.slots, type_demarche, version)
            if recapitulatif is None:
                rapport.tours.append(Tour(
                    genre=MANQUE, cle="recapitulatif", origine="gabarit:recapitulatif",
                    dit="(aucun gabarit de récapitulatif utilisable — le dialogue réel "
                        "retomberait sur le texte figé du code)",
                    pulaar=None, audio_pret=False, accepte=False,
                ))
            else:
                rapport.tours.append(_tour(RECAPITULATIF, "recapitulatif", recapitulatif))
            rapport.termine = True
            return rapport

        if etape["type"] == "champ":
            if not _jouer_champ(etape["definition"], reponses, rapport, champs_ignores):
                return rapport
        else:
            if not _jouer_document(etape["groupe"], reponses, rapport, documents_recus):
                return rapport

    rapport.arret = (
        f"Arrêt après {TOURS_MAX} tours : une étape ne se remplit jamais. "
        f"Vérifiez les conditions de la démarche."
    )
    log.warning("Simulation de %r interrompue après %s tours.", type_demarche, TOURS_MAX)
    return rapport


def _jouer_champ(
    ligne: dict, reponses: dict, rapport: Rapport, champs_ignores: set[str]
) -> bool:
    """Retourne False quand la simulation doit s'arrêter là."""
    nom = ligne["nom_champ"]
    question = demarche.question_champ(ligne)

    if nom not in reponses:
        rapport.tours.append(_tour(QUESTION, nom, question, accepte=False))
        rapport.arret = f"Le scénario ne dit pas quoi répondre à « {nom} »."
        return False

    brute = reponses[nom]
    valide, valeur, motif = slot_controller.valider_valeur(
        ligne.get("type_valeur", "texte"), brute,
        ligne.get("regle_validation"), rapport.slots,
    )
    rapport.tours.append(
        _tour(QUESTION, nom, question, repondu=brute, accepte=valide, motif=motif))

    if not valide:
        # Le dialogue réel relancerait. On montre la relance et on s'arrête :
        # rejouer la même réponse en boucle n'apprendrait rien de plus.
        relance = demarche.relance_champ(ligne, 0)
        rapport.tours.append(_tour(REFUS, nom, relance, motif=motif))
        rapport.arret = f"Réponse refusée pour « {nom} » : {motif}"
        return False

    rapport.slots[nom] = valeur
    champs_ignores.discard(nom)
    return True


def _jouer_document(
    groupe: list[dict], reponses: dict, rapport: Rapport, documents_recus: set[str]
) -> bool:
    ligne = groupe[0]
    types = [d["type_document"] for d in groupe]
    message = demarche.message_document(ligne, tentative=0)

    fournis = [t for t in types if reponses.get(t)]
    rapport.tours.append(_tour(
        PIECE, ligne["type_document"], message,
        repondu=fournis[0] if fournis else None, accepte=bool(fournis),
    ))
    if not fournis:
        rapport.arret = (
            f"Le scénario ne fournit aucune pièce parmi : {', '.join(types)}."
        )
        return False
    documents_recus.add(fournis[0])
    return True


def _annees_a_reculer(champs: list[dict]) -> dict[str, int]:
    """
    De combien de générations reculer chaque date pour respecter les règles.

    Certaines dates doivent en précéder d'autres — `regle_validation` porte
    alors `avant:autre_champ` (ou `apres:`, lu dans l'autre sens). Un scénario
    de départ qui donne la même date à
    la mère et à l'enfant se fait refuser dès la deuxième question, et
    l'utilisateur croit avoir cassé quelque chose alors qu'il ouvre l'écran.

    On lit la règle plutôt que le nom du champ : une démarche ajoutée demain
    en profite sans toucher à ce module.
    """
    precede: dict[str, str] = {}
    for champ in champs:
        for morceau in (champ.get("regle_validation") or "").split("|"):
            if morceau.startswith("avant:"):
                precede[champ["nom_champ"]] = morceau.split(":", 1)[1]
            elif morceau.startswith("apres:"):
                # « F après Y » se lit dans l'autre sens : c'est Y qui précède F.
                precede.setdefault(morceau.split(":", 1)[1], champ["nom_champ"])

    profondeurs: dict[str, int] = {}

    def profondeur(nom: str, vus: tuple = ()) -> int:
        if nom in profondeurs:
            return profondeurs[nom]
        cible = precede.get(nom)
        # `vus` protège d'une règle circulaire (A avant B, B avant A) : une
        # démarche mal formée ne doit pas faire boucler le simulateur.
        valeur = 0 if cible is None or cible in vus else profondeur(cible, (*vus, nom)) + 1
        profondeurs[nom] = valeur
        return valeur

    return {
        c["nom_champ"]: profondeur(c["nom_champ"])
        for c in champs if c.get("type_valeur") == "date"
    }


def scenario_type(
    type_demarche: str = demarche.TYPE_DEMARCHE_PAR_DEFAUT,
    version: int | None = None,
    aujourdhui: date | None = None,
) -> dict[str, Any]:
    """
    Un scénario de départ, rempli de valeurs plausibles.

    Sert à ouvrir l'écran sur quelque chose qui se déroule, plutôt que sur un
    formulaire vide : on corrige ensuite ce qu'on veut éprouver. Les valeurs
    sont volontairement banales — le but est de voir la séquence, pas de
    piéger la validation.
    """
    from datetime import timedelta

    champs = demarche.champs(type_demarche, version)
    reculs = _annees_a_reculer(champs)
    # Une naissance récente : cohérente avec l'âge proposé, et « passée ».
    naissance = (aujourdhui or date.today()) - timedelta(days=7)
    exemples = {
        "texte": "Ibrahima Diallo",
        "age": {"valeur": 7, "unite": "jours"},
        "booleen": "oui",
        "nombre": "1",
    }

    def valeur(champ: dict) -> Any:
        if champ.get("type_valeur") == "date":
            annees = reculs.get(champ["nom_champ"], 0) * 25
            return naissance.replace(year=naissance.year - annees).isoformat()
        if champ.get("type_valeur") == "enum":
            # La première valeur autorisée : « à remplir » serait refusé.
            choix = [v.strip() for v in (champ.get("regle_validation") or "").split("|") if v.strip()]
            return choix[0] if choix else "à remplir"
        return exemples.get(champ.get("type_valeur", "texte"), "à remplir")

    scenario: dict[str, Any] = {c["nom_champ"]: valeur(c) for c in champs}
    for document in demarche.documents(type_demarche, version):
        scenario[document["type_document"]] = True
    return scenario
