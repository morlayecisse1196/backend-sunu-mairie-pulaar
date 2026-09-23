"""
Langage de conditions des démarches (étape 2.1 du plan maître).

POURQUOI UN LANGAGE ET PAS UN BOOLÉEN

Les règles réelles de l'état civil sénégalais ne se ramènent pas toutes à
« ce champ est-il obligatoire ». Les démarches visées en demandent quatre
formes distinctes :

1. **Champ obligatoire** — une question à laquelle il faut répondre.
   → colonne `obligatoire` (déjà en base), désormais réellement respectée.
2. **Délai qui interrompt la démarche** — la constatation de mariage n'est
   plus possible passé six mois ; au-delà d'un an, un décès ne s'inscrit plus
   sans jugement d'autorisation d'inscription tardive.
   → `mois_depuis(date_mariage) > 6`, `annees_depuis(date_deces) >= 1`
3. **Condition croisée entre deux champs** — l'option polygamique interdit le
   régime de la communauté de biens.
   → `option_matrimoniale = polygamie et regime_biens = communaute`
4. **Alternative entre deux pièces** — un certificat médical **ou** deux
   témoins.
   → colonne `groupe` sur `demarche_documents` (traitée dans slot_controller)

Les formes 2 et 3 sont des conditions *calculées*, pas des cases à cocher :
d'où ce petit langage, écrit pour être lisible par un officier d'état civil
autant que par le moteur, et éditable depuis l'interface admin (étape 4).

GRAMMAIRE

    expression  := disjonction
    disjonction := conjonction ( "ou" conjonction )*
    conjonction := facteur ( "et" facteur )*
    facteur     := "non" facteur | "(" expression ")" | comparaison
    comparaison := operande [ ("="|"!="|"<"|"<="|">"|">=") valeur ]
    operande    := nom_champ | fonction "(" nom_champ ")"
    fonction    := jours_depuis | mois_depuis | annees_depuis | age_jours | rempli
    valeur      := nombre | "texte" | mot | oui | non

Une comparaison réduite à un opérande seul teste sa vérité : `parents_maries`
équivaut à `parents_maries = oui`.

TROIS VALEURS, PAS DEUX

Un champ pas encore renseigné ne rend pas la condition fausse : elle est
**indéterminée**. La distinction n'est pas théorique — avec deux valeurs, un
document conditionné par « parents_maries » serait sauté *avant* que la
question ne soit posée, et ne serait jamais demandé. `et`, `ou` et `non`
propagent donc INCONNU, sauf quand le résultat est déjà certain
(`faux et inconnu` vaut FAUX, `vrai ou inconnu` vaut VRAI).

`rempli(champ)` fait exception : il répond toujours VRAI ou FAUX, puisque son
objet est précisément de tester la présence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from dialogue_engine import normaliser_age
from services.journal import obtenir_logger

log = obtenir_logger("conditions")

Trivalent = Literal["vrai", "faux", "inconnu"]

VRAI: Trivalent = "vrai"
FAUX: Trivalent = "faux"
INCONNU: Trivalent = "inconnu"


class ConditionInvalide(ValueError):
    """Condition mal écrite — signalée à l'auteur de la règle, jamais au citoyen."""


# ============================================================================
# Analyse lexicale et syntaxique
# ============================================================================

_MOTS_CLES = {"et", "ou", "non", "oui"}
_FONCTIONS = {"jours_depuis", "mois_depuis", "annees_depuis", "age_jours", "rempli"}
_OPERATEURS = {"=", "!=", "<", "<=", ">", ">="}

_JETON = re.compile(
    r"""\s*(?:
          (?P<parenthese>[()])
        | (?P<operateur><=|>=|!=|=|<|>)
        | (?P<nombre>\d+(?:[.,]\d+)?)
        | (?P<chaine>"[^"]*"|'[^']*')
        | (?P<mot>[A-Za-zÀ-ÿ_][A-Za-zÀ-ÿ0-9_]*)
    )""",
    re.VERBOSE,
)


def _decouper(expression: str) -> list[str]:
    jetons: list[str] = []
    position = 0
    while position < len(expression):
        if expression[position].isspace():
            position += 1
            continue
        correspondance = _JETON.match(expression, position)
        if correspondance is None:
            raise ConditionInvalide(
                f"Caractère inattendu à la position {position} : {expression[position]!r} — {expression!r}"
            )
        jetons.append(correspondance.group().strip())
        position = correspondance.end()
    return jetons


@dataclass(frozen=True)
class Operande:
    """Un champ, éventuellement passé à une fonction (`mois_depuis(date_mariage)`)."""

    champ: str
    fonction: str | None = None


@dataclass(frozen=True)
class Comparaison:
    operande: Operande
    operateur: str | None = None
    valeur: Any = None


@dataclass(frozen=True)
class Et:
    membres: tuple[Any, ...]


@dataclass(frozen=True)
class Ou:
    membres: tuple[Any, ...]


@dataclass(frozen=True)
class Non:
    membre: Any


class _Analyseur:
    def __init__(self, jetons: list[str], source: str):
        self.jetons = jetons
        self.source = source
        self.position = 0

    def _courant(self) -> str | None:
        return self.jetons[self.position] if self.position < len(self.jetons) else None

    def _avancer(self) -> str:
        jeton = self._courant()
        if jeton is None:
            raise ConditionInvalide(f"Condition incomplète : {self.source!r}")
        self.position += 1
        return jeton

    def analyser(self):
        arbre = self._disjonction()
        if self._courant() is not None:
            raise ConditionInvalide(f"Texte en trop après la condition ({self._courant()!r}) : {self.source!r}")
        return arbre

    def _disjonction(self):
        membres = [self._conjonction()]
        while self._courant() == "ou":
            self._avancer()
            membres.append(self._conjonction())
        return membres[0] if len(membres) == 1 else Ou(tuple(membres))

    def _conjonction(self):
        membres = [self._facteur()]
        while self._courant() == "et":
            self._avancer()
            membres.append(self._facteur())
        return membres[0] if len(membres) == 1 else Et(tuple(membres))

    def _facteur(self):
        jeton = self._courant()
        if jeton == "non":
            self._avancer()
            return Non(self._facteur())
        if jeton == "(":
            self._avancer()
            interieur = self._disjonction()
            if self._courant() != ")":
                raise ConditionInvalide(f"Parenthèse fermante manquante : {self.source!r}")
            self._avancer()
            return interieur
        return self._comparaison()

    def _comparaison(self) -> Comparaison:
        operande = self._operande()
        if self._courant() in _OPERATEURS:
            operateur = self._avancer()
            return Comparaison(operande, operateur, self._valeur())
        return Comparaison(operande)

    def _operande(self) -> Operande:
        mot = self._avancer()
        if mot in _OPERATEURS or mot in ("(", ")"):
            raise ConditionInvalide(f"Nom de champ attendu, trouvé {mot!r} : {self.source!r}")
        if mot in _FONCTIONS:
            if self._courant() != "(":
                raise ConditionInvalide(f"Parenthèse attendue après {mot!r} : {self.source!r}")
            self._avancer()
            champ = self._avancer()
            if self._courant() != ")":
                raise ConditionInvalide(f"Parenthèse fermante manquante après {mot}({champ} : {self.source!r}")
            self._avancer()
            return Operande(champ=champ, fonction=mot)
        if mot in _MOTS_CLES:
            raise ConditionInvalide(f"{mot!r} est un mot réservé, il ne peut pas nommer un champ : {self.source!r}")
        return Operande(champ=mot)

    def _valeur(self) -> Any:
        jeton = self._avancer()
        if jeton.startswith(('"', "'")):
            return jeton[1:-1]
        if re.fullmatch(r"\d+(?:[.,]\d+)?", jeton):
            nombre = float(jeton.replace(",", "."))
            return int(nombre) if nombre.is_integer() else nombre
        if jeton == "oui":
            return True
        if jeton == "non":
            return False
        return jeton


def analyser(expression: str):
    """
    Transforme une condition en arbre, ou lève `ConditionInvalide`.

    Réservé à la validation d'une règle au moment où on l'écrit (tests,
    interface admin). En plein dialogue, c'est `evaluer` qu'il faut appeler :
    elle ne lève jamais.
    """
    if expression is None or not expression.strip():
        raise ConditionInvalide("Condition vide.")
    return _Analyseur(_decouper(expression), expression).analyser()


def champs_utilises(expression: str) -> set[str]:
    """
    Les champs référencés par une condition — sert à vérifier qu'une règle ne
    cite pas un champ qui n'existe pas dans la démarche (faute de frappe qui
    rendrait la règle silencieusement indéterminée, donc sans effet).
    """
    def parcourir(noeud) -> set[str]:
        if isinstance(noeud, Comparaison):
            return {noeud.operande.champ}
        if isinstance(noeud, (Et, Ou)):
            return set().union(*(parcourir(m) for m in noeud.membres))
        if isinstance(noeud, Non):
            return parcourir(noeud.membre)
        return set()

    return parcourir(analyser(expression))


# ============================================================================
# Évaluation
# ============================================================================


def _comme_date(valeur: Any) -> date | None:
    """Les dates arrivent normalisées en ISO par `slot_controller.valider_valeur`."""
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    if isinstance(valeur, str):
        try:
            return date.fromisoformat(valeur.strip()[:10])
        except ValueError:
            return None
    return None


def _jours_dans_le_mois(annee: int, mois: int) -> int:
    if mois == 12:
        return (date(annee + 1, 1, 1) - date(annee, 12, 1)).days
    return (date(annee, mois + 1, 1) - date(annee, mois, 1)).days


def _ajouter_mois(depuis: date, mois: int) -> date:
    """`depuis` décalée de `mois` mois, le 31 se repliant sur la fin du mois visé."""
    total = depuis.month - 1 + mois
    annee, mois_cible = depuis.year + total // 12, total % 12 + 1
    return date(annee, mois_cible, min(depuis.day, _jours_dans_le_mois(annee, mois_cible)))


def _mois_ecoules(depuis: date, jusqu_a: date) -> float:
    """
    Mois écoulés au sens du CALENDRIER, avec la fraction du mois entamé.

    Deux raisons de ne pas se contenter d'un entier de mois révolus, ni d'une
    division par 30 :

    - Un mois civil n'est pas trente jours. Du 31 janvier au 31 juillet, il
      s'est écoulé six mois, que ces mois fassent 28 ou 31 jours.
    - « Passé six mois » doit devenir vrai le LENDEMAIN du sixième mois, pas
      un mois plus tard. Avec des mois entiers, `mois_depuis(x) > 6` ne serait
      vrai qu'au septième mois révolu : un dossier hors délai depuis trois
      semaines serait encore accepté. La fraction règle exactement ce cas —
      au 1er août, six mois et un jour valent 6,03, donc « plus de six mois ».
    """
    mois = (jusqu_a.year - depuis.year) * 12 + (jusqu_a.month - depuis.month)
    if jusqu_a.day < depuis.day:
        mois -= 1
    anniversaire = _ajouter_mois(depuis, mois)
    jours_restants = (jusqu_a - anniversaire).days
    if jours_restants <= 0:
        return float(mois)
    suivant = _ajouter_mois(depuis, mois + 1)
    longueur = (suivant - anniversaire).days or 30
    return mois + jours_restants / longueur


def _appliquer_fonction(fonction: str, valeur: Any, aujourdhui: date) -> Any:
    if fonction == "rempli":
        return valeur is not None
    if fonction == "age_jours":
        # Champ de type `age` : {"valeur": 3, "unite": "mois"}.
        if not isinstance(valeur, dict):
            return None
        try:
            return normaliser_age(valeur.get("valeur"), valeur.get("unite") or "")
        except (ValueError, TypeError):
            return None
    d = _comme_date(valeur)
    if d is None:
        return None
    if fonction == "jours_depuis":
        return (aujourdhui - d).days
    if fonction == "mois_depuis":
        return _mois_ecoules(d, aujourdhui)
    if fonction == "annees_depuis":
        return _mois_ecoules(d, aujourdhui) / 12
    raise ConditionInvalide(f"Fonction inconnue : {fonction!r}")


def _comme_nombre(valeur: Any) -> float | None:
    if isinstance(valeur, bool):
        return None
    if isinstance(valeur, (int, float)):
        return float(valeur)
    try:
        return float(str(valeur).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


#: Opérateurs qui demandent un ordre — donc deux valeurs réellement ordonnables.
_ORDRE = {"<", "<=", ">", ">="}


def _normaliser_pour_comparaison(gauche: Any, droite: Any) -> tuple[Any, Any, bool]:
    """
    Aligne les deux côtés et dit s'ils sont ORDONNABLES.

    Le troisième élément n'est pas un détail : sans lui, `nom > 3` comparait
    « Diallo » à « 3 » comme deux textes et répondait vrai, ce qui n'a aucun
    sens. Une comparaison d'ordre entre un texte et un nombre ne doit rien
    trancher du tout.
    """
    if isinstance(gauche, bool) or isinstance(droite, bool):
        return bool(gauche), bool(droite), False
    nombre_gauche, nombre_droite = _comme_nombre(gauche), _comme_nombre(droite)
    if nombre_gauche is not None and nombre_droite is not None:
        return nombre_gauche, nombre_droite, True
    date_gauche, date_droite = _comme_date(gauche), _comme_date(droite)
    if date_gauche is not None and date_droite is not None:
        return date_gauche, date_droite, True
    if (nombre_gauche is None) != (nombre_droite is None):
        # Un seul côté est un nombre : comparables pour l'égalité (toujours
        # fausse), jamais pour l'ordre.
        return str(gauche).strip().casefold(), str(droite).strip().casefold(), False
    return str(gauche).strip().casefold(), str(droite).strip().casefold(), True


def _evaluer_comparaison(noeud: Comparaison, slots: dict, aujourdhui: date) -> Trivalent:
    brut = slots.get(noeud.operande.champ)
    if noeud.operande.fonction:
        gauche = _appliquer_fonction(noeud.operande.fonction, brut, aujourdhui)
        if noeud.operande.fonction == "rempli":
            # Seule fonction qui tranche même sur un champ absent.
            resultat = bool(gauche)
            if noeud.operateur is None:
                return VRAI if resultat else FAUX
            gauche = resultat
    else:
        gauche = brut

    if gauche is None:
        return INCONNU  # champ pas encore renseigné : indéterminé, jamais « faux »

    if noeud.operateur is None:
        # `parents_maries` seul = test de vérité. Une chaîne vide ou un zéro
        # comptent comme faux, cohérent avec la lecture naturelle de la règle.
        return VRAI if bool(gauche) else FAUX

    gauche, droite, ordonnables = _normaliser_pour_comparaison(gauche, noeud.valeur)
    if noeud.operateur in _ORDRE and not ordonnables:
        return INCONNU
    try:
        if noeud.operateur == "=":
            resultat = gauche == droite
        elif noeud.operateur == "!=":
            resultat = gauche != droite
        elif noeud.operateur == "<":
            resultat = gauche < droite
        elif noeud.operateur == "<=":
            resultat = gauche <= droite
        elif noeud.operateur == ">":
            resultat = gauche > droite
        else:
            resultat = gauche >= droite
    except TypeError:
        return INCONNU  # types non comparables : on ne tranche pas au hasard
    return VRAI if resultat else FAUX


def _evaluer_noeud(noeud, slots: dict, aujourdhui: date) -> Trivalent:
    if isinstance(noeud, Comparaison):
        return _evaluer_comparaison(noeud, slots, aujourdhui)
    if isinstance(noeud, Non):
        interieur = _evaluer_noeud(noeud.membre, slots, aujourdhui)
        return INCONNU if interieur == INCONNU else (FAUX if interieur == VRAI else VRAI)
    if isinstance(noeud, Et):
        resultats = [_evaluer_noeud(m, slots, aujourdhui) for m in noeud.membres]
        if FAUX in resultats:
            return FAUX  # une seule fausse suffit, même si les autres sont inconnues
        return INCONNU if INCONNU in resultats else VRAI
    if isinstance(noeud, Ou):
        resultats = [_evaluer_noeud(m, slots, aujourdhui) for m in noeud.membres]
        if VRAI in resultats:
            return VRAI
        return INCONNU if INCONNU in resultats else FAUX
    raise ConditionInvalide(f"Nœud d'arbre inattendu : {noeud!r}")


def evaluer(expression: str | None, slots: dict, aujourdhui: date | None = None) -> Trivalent:
    """
    Évalue une condition contre les valeurs déjà collectées.

    Ne lève jamais : une condition absente vaut VRAI (pas de condition = la
    règle s'applique), une condition mal écrite vaut INCONNU. Un dialogue en
    cours ne doit pas s'interrompre parce qu'une règle a été mal saisie côté
    admin — la faute est signalée par `analyser()` au moment de l'écrire.
    """
    if expression is None or not str(expression).strip():
        return VRAI
    try:
        arbre = analyser(str(expression))
    except ConditionInvalide as exc:
        # Une règle mal saisie ne bloque pas le citoyen, mais elle ne doit pas
        # disparaître en silence : sans cette trace, la règle serait sans
        # effet et personne ne le saurait.
        log.error("Condition mal écrite, ignorée (%s) : %r", exc, expression)
        return INCONNU
    try:
        return _evaluer_noeud(arbre, slots or {}, aujourdhui or date.today())
    except ConditionInvalide as exc:
        log.error("Condition inévaluable (%s) : %r", exc, expression)
        return INCONNU
