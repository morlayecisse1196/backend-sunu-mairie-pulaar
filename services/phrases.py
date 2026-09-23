"""
Une phrase dite au citoyen, et son pulaar quand il a été relu (étape 3).

POURQUOI CE MODULE

Le pulaar est incohérent parce que des phrases connues d'avance — « Quelle est
sa date de naissance exacte ? » est écrite en base depuis des mois — sont
retraduites par le modèle à chaque conversation, différemment à chaque fois.
Le citoyen entend trois formulations pour la même question selon le jour.

Une phrase dont le pulaar est relu par un locuteur ne doit donc plus jamais
repasser par le modèle. Encore faut-il que le pulaar VOYAGE avec le français,
du moment où la phrase est choisie jusqu'à la synthèse vocale. C'est le rôle de
`Phrase` et de `Reponse` : le moteur construit une réponse morceau par morceau,
chaque morceau sachant s'il a déjà son pulaar.

UNE RÉPONSE EST FAITE DE MORCEAUX

Un tour de dialogue dit rarement une seule phrase : « C'est noté. » suivi de
la question suivante, ou un motif de refus suivi de la question reposée. Ces
morceaux ne sont pas au même stade — la confirmation peut être validée alors
que la question ne l'est pas encore. Traiter la réponse comme un bloc unique
obligerait à tout retraduire dès qu'un seul morceau manque.

CE QUI N'EST JAMAIS DIT

Une traduction présente mais NON RELUE n'est jamais prononcée. Elle attend
dans sa colonne, et c'est le français qui part au traducteur, comme avant.
Faire dire au citoyen une traduction automatique en la présentant comme
validée serait pire que l'état actuel : personne ne saurait plus ce qui a été
relu.
"""
from __future__ import annotations

from dataclasses import dataclass

from services.journal import obtenir_logger

log = obtenir_logger("phrases")


@dataclass(frozen=True)
class Phrase:
    """Un morceau de réponse : son français, et son pulaar s'il a été relu."""

    francais: str
    pulaar: str | None = None
    pulaar_valide: bool = False
    audio: str | None = None
    #: D'où vient la phrase — sert au signalement (étape 3.5) et aux journaux.
    origine: str = "?"

    def pulaar_pret(self) -> str | None:
        """
        Le pulaar utilisable tel quel, ou `None` s'il faut traduire.

        Une traduction non relue vaut `None` : elle existe peut-être en base,
        mais la dire reviendrait à la faire passer pour validée.
        """
        if self.pulaar_valide and self.pulaar and self.pulaar.strip():
            return self.pulaar.strip()
        return None


@dataclass(frozen=True)
class Reponse:
    """La réponse complète d'un tour, en morceaux."""

    morceaux: tuple[Phrase, ...] = ()

    @property
    def francais(self) -> str:
        return " ".join(m.francais.strip() for m in self.morceaux if m.francais.strip()).strip()

    @property
    def entierement_validee(self) -> bool:
        """Vrai si aucun morceau n'a besoin du traducteur."""
        return bool(self.morceaux) and all(m.pulaar_pret() for m in self.morceaux)

    def a_valider(self) -> tuple[Phrase, ...]:
        """Les morceaux qui repassent encore par le modèle."""
        return tuple(m for m in self.morceaux if not m.pulaar_pret())


def reponse(*morceaux: Phrase | str | None) -> Reponse:
    """
    Assemble une réponse. Les `None` sont ignorés, une chaîne devient une
    phrase sans pulaar — pratique pour un texte qui n'existe pas encore en base.
    """
    assemblees: list[Phrase] = []
    for morceau in morceaux:
        if morceau is None:
            continue
        if isinstance(morceau, str):
            if morceau.strip():
                assemblees.append(Phrase(francais=morceau.strip(), origine="texte_libre"))
        elif morceau.francais.strip():
            assemblees.append(morceau)
    return Reponse(tuple(assemblees))


def depuis_texte(texte: str | None, origine: str = "texte_libre") -> Reponse:
    """Une réponse d'un seul morceau, sans pulaar : tout repasse par le modèle."""
    if not texte or not texte.strip():
        return Reponse(())
    return Reponse((Phrase(francais=texte.strip(), origine=origine),))


# ============================================================================
# Étape 3.5 — signalement des phrases encore à relire
# ============================================================================

#: Ce qui a été vu depuis le démarrage du serveur : origine -> nombre de fois.
#: Volontairement en mémoire et non en base — c'est un indicateur de travail
#: restant, pas une donnée métier, et il ne doit rien coûter en plein dialogue.
_signalements: dict[str, int] = {}


def signaler(reponse_dite: Reponse) -> None:
    """
    Note les morceaux qui ont dû être traduits à la volée.

    Sans ce signalement, une phrase oubliée resterait traduite par le modèle
    pour toujours, sans que personne ne s'en aperçoive — le dialogue
    fonctionnerait, simplement moins bien, et en silence.
    """
    for morceau in reponse_dite.a_valider():
        _signalements[morceau.origine] = _signalements.get(morceau.origine, 0) + 1
        log.info(
            "Phrase sans pulaar validé, traduite à la volée [%s] : %.80s",
            morceau.origine,
            morceau.francais,
        )


def signalements() -> dict[str, int]:
    """Copie du compteur, pour l'exposer à l'admin (étape 4.2)."""
    return dict(_signalements)


def reinitialiser_signalements() -> None:
    _signalements.clear()
