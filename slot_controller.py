"""
slot_controller.py — Sprint J, Tâches J.2 et J.4 (MEMOIR2/SUNU_MAIRIE_PROMPTS.md).

J.2 : validateurs déterministes par type de champ (`demarche_champs.type_valeur`) —
zéro appel LLM, zéro accès réseau, cf. backend-agent/PLAN_REFACTOR_DIALOGUE_CHAMPS.md §3.

Principe de conception : ces fonctions ne connaissent JAMAIS un nom de champ
en dur (ex. "date_naissance_mere") — toute règle spécifique à un champ passe
par `regle_validation` (donnée en base, `demarche_champs.regle_validation`),
jamais par du code. C'est ce qui rend le contrôleur généralisable à une future
démarche sans modification (cf. plan §7) : seule la donnée change.

DSL supporté pour `regle_validation`, par type :
  - date    : règles combinables séparées par "|" —
                "passee"        -> rejette une date dans le futur
                "avant:<champ>" -> rejette si >= à la valeur du champ nommé
                "apres:<champ>" -> rejette si <= à la valeur du champ nommé
                                    dans `valeurs_connues` (cohérence croisée,
                                    ex. mère née avant l'enfant)
  - nombre  : "min:max" -> plage acceptée (optionnel)
  - enum    : liste de valeurs autorisées séparées par "|"
  - texte, booleen, age : `regle_validation` non utilisé pour l'instant.

J.4 : `charger_definition_demarche`/`charger_documents_demarche` (lecture des
tables de définition), `determiner_etape_courante` (premier champ OU document
non satisfait, ordre combiné) et l'orchestrateur `traiter_tour_administratif`
qui implémente la boucle de contrôle complète (plan §1 et §5) — voir docstring
de chaque fonction plus bas pour le détail.

Câblé dans main.py depuis la Tâche J.5. J.6 ajoute l'écriture réelle dans
`cas_particuliers` sur échecs répétés (champ) et rappels sans réponse
(document), + la détection explicite "je ne l'ai pas" côté document.
"""
import json
from datetime import date, datetime
from typing import Any, Callable

import httpx

from dossiers_repo import list_documents, create_cas_particulier
from services import conditions, demarche, phrases, regles_demarche, tours_sociaux
from prompts import (
    SYSTEM_PROMPT_CHAMP_CIBLE, build_schema_champ_cible, build_prompt_champ_cible,
    SYSTEM_PROMPT_DOCUMENT_INDISPONIBLE, SCHEMA_DOCUMENT_INDISPONIBLE, build_prompt_document_indisponible,
)

from dialogue_engine import normaliser_age

# Mois français reconnus en toutes lettres — les citoyens disent "le 9 août
# 2026" à l'oral, pas "2026-08-09" (cf. Exemple 2.1). Volontairement permissif
# sur les variantes d'accent usuelles (l'ASR peut les perdre).
MOIS_FR = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "août": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12,
}

FORMATS_DATE_NUMERIQUES = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]

MOTS_OUI = {"oui", "d'accord", "daccord", "exact", "vrai", "correct", "ouais", "affirmatif"}
MOTS_NON = {"non", "faux", "incorrect", "pas du tout", "negatif", "négatif"}

TAILLE_MAX_TEXTE = 200


class Refus(str):
    """
    Un motif de refus qui correspond à une PHRASE SYSTÈME (migration 020),
    donc traduisible une fois pour toutes.

    Hérite de `str` pour que `valider_valeur` garde son contrat : elle rend
    toujours un message français lisible. La sous-classe ajoute seulement la
    clé, que le moteur utilise pour retrouver le pulaar validé au lieu de
    faire retraduire la même phrase à chaque refus.

    Les refus dont le texte dépend des données — « doit être antérieure à
    celle de date_naissance_enfant » — restent de simples chaînes : ils ne
    peuvent pas être traduits d'avance, et le gabarit à trous qui les
    remplacera est la tâche 3.2.
    """

    cle: str

    def __new__(cls, cle: str, texte: str):
        instance = super().__new__(cls, texte)
        instance.cle = cle
        return instance


def _refus(cle: str) -> Refus:
    return Refus(cle, demarche.phrase_systeme(cle).francais)


def phrase_refus(raison) -> "phrases.Phrase | None":
    """La phrase à dire pour un motif de refus, avec son pulaar s'il est validé."""
    if raison is None or not str(raison).strip():
        return None
    if isinstance(raison, Refus):
        return demarche.phrase_systeme(raison.cle)
    return phrases.Phrase(francais=str(raison), origine="refus:texte_libre")


def _parser_date_texte(valeur_brute: str) -> date | None:
    """Parse un format numérique connu, ou une forme "9 août 2026" / "le 9 aout 2026"."""
    brut = valeur_brute.strip()
    for fmt in FORMATS_DATE_NUMERIQUES:
        try:
            return datetime.strptime(brut, fmt).date()
        except ValueError:
            continue

    mots = brut.lower().replace("le ", "", 1).replace(",", "").split()
    if len(mots) == 3:
        jour_txt, mois_txt, annee_txt = mots
        mois = MOIS_FR.get(mois_txt.strip("."))
        if mois and jour_txt.isdigit() and annee_txt.isdigit():
            try:
                return date(int(annee_txt), mois, int(jour_txt))
            except ValueError:
                return None
    return None


def _comme_date(valeur: Any) -> date | None:
    if isinstance(valeur, date):
        return valeur
    if valeur is None:
        return None
    return _parser_date_texte(str(valeur))


def _valider_texte(valeur_brute: Any, regle_validation: str | None):
    if valeur_brute is None:
        return False, None, _refus("refus_reponse_vide")
    texte = str(valeur_brute).strip()
    if not texte:
        return False, None, _refus("refus_reponse_vide")
    if len(texte) > TAILLE_MAX_TEXTE:
        return False, None, _refus("refus_reponse_longue")
    return True, texte, None


def _valider_date(valeur_brute: Any, regle_validation: str | None, valeurs_connues: dict | None):
    if valeur_brute is None:
        return False, None, _refus("refus_reponse_vide")
    d = _comme_date(valeur_brute)
    if d is None:
        # La transcription brute n'est PAS répétée au citoyen : relire à voix
        # haute une transcription ratée n'aide personne, et rend la phrase
        # impossible à traduire d'avance.
        return False, None, _refus("refus_date_incomprise")

    for regle in (regle_validation or "").split("|"):
        regle = regle.strip()
        if not regle:
            continue
        if regle == "passee":
            if d > date.today():
                return False, None, _refus("refus_date_future")
        elif regle.startswith("avant:"):
            autre_champ = regle.split(":", 1)[1]
            autre_date = _comme_date((valeurs_connues or {}).get(autre_champ))
            if autre_date is not None and d >= autre_date:
                return False, None, f"Cette date doit être antérieure à celle de {autre_champ}."
        elif regle.startswith("apres:"):
            # Symétrique d'`avant:`. Sans elle, une date de décès antérieure à
            # la naissance passait sans que rien ne le signale (étape 5.3).
            autre_champ = regle.split(":", 1)[1]
            autre_date = _comme_date((valeurs_connues or {}).get(autre_champ))
            if autre_date is not None and d <= autre_date:
                return False, None, f"Cette date doit être postérieure à celle de {autre_champ}."

    return True, d.isoformat(), None


def _valider_nombre(valeur_brute: Any, regle_validation: str | None):
    try:
        nombre = float(str(valeur_brute).strip().replace(",", "."))
    except (TypeError, ValueError, AttributeError):
        return False, None, _refus("refus_nombre")

    if regle_validation and ":" in regle_validation:
        try:
            mini_txt, maxi_txt = regle_validation.split(":", 1)
            mini, maxi = float(mini_txt), float(maxi_txt)
            if not (mini <= nombre <= maxi):
                return False, None, f"La valeur doit être comprise entre {mini:g} et {maxi:g}."
        except ValueError:
            pass  # regle_validation mal formée -> ignorée plutôt que de bloquer le dialogue

    return True, nombre, None


def _valider_booleen(valeur_brute: Any, regle_validation: str | None):
    if isinstance(valeur_brute, bool):
        return True, valeur_brute, None
    texte = str(valeur_brute).strip().lower() if valeur_brute is not None else ""
    if texte in MOTS_OUI:
        return True, True, None
    if texte in MOTS_NON:
        return True, False, None
    return False, None, _refus("refus_oui_non")


def _valider_age(valeur_brute: Any, regle_validation: str | None):
    if not isinstance(valeur_brute, dict):
        return False, None, "Âge attendu sous la forme {valeur, unite}."
    valeur, unite = valeur_brute.get("valeur"), valeur_brute.get("unite")
    if valeur is None or not unite:
        return False, None, "Il manque soit la valeur, soit l'unité de l'âge."
    try:
        age_jours = normaliser_age(valeur, unite)
    except ValueError as exc:
        return False, None, str(exc)
    if age_jours < 0:
        return False, None, "L'âge ne peut pas être négatif."
    return True, {"valeur": valeur, "unite": unite}, None


def _valider_enum(valeur_brute: Any, regle_validation: str | None):
    valeurs_autorisees = [v.strip() for v in (regle_validation or "").split("|") if v.strip()]
    if not valeurs_autorisees:
        return False, None, "Aucune liste de valeurs autorisées définie pour ce champ."
    texte = str(valeur_brute).strip() if valeur_brute is not None else ""
    if texte in valeurs_autorisees:
        return True, texte, None
    return False, None, f"Valeur non reconnue — attendu l'une de : {', '.join(valeurs_autorisees)}."


_VALIDATEURS = {
    "texte": lambda v, r, _c: _valider_texte(v, r),
    "date": lambda v, r, c: _valider_date(v, r, c),
    "nombre": lambda v, r, _c: _valider_nombre(v, r),
    "booleen": lambda v, r, _c: _valider_booleen(v, r),
    "age": lambda v, r, _c: _valider_age(v, r),
    "enum": lambda v, r, _c: _valider_enum(v, r),
}


def valider_valeur(
    type_valeur: str,
    valeur_brute: Any,
    regle_validation: str | None,
    valeurs_connues: dict | None = None,
) -> tuple[bool, Any, str | None]:
    """
    Valide et normalise une valeur extraite pour un champ de type `type_valeur`
    (cf. `demarche_champs.type_valeur`), SANS appel LLM ni réseau.

    `valeurs_connues` (optionnel) : les autres slots déjà remplis du dossier
    courant — utilisé uniquement par les règles de cohérence croisée du DSL
    date (ex. `regle_validation="avant:date_naissance_enfant"`) ; absent ou
    incomplet, la règle correspondante est simplement ignorée (pas encore
    vérifiable), jamais une erreur bloquante.

    Retourne `(valide, valeur_normalisee, raison_erreur)` — `raison_erreur`
    est `None` si `valide` est `True`, sinon un message en français prêt à
    être injecté dans la reformulation adressée au citoyen (Tâche J.3/J.4).
    """
    validateur = _VALIDATEURS.get(type_valeur)
    if validateur is None:
        raise ValueError(f"type_valeur inconnu : {type_valeur!r}")
    return validateur(valeur_brute, regle_validation, valeurs_connues)


# ============================================================================
# Tâche J.4 — Orchestrateur du mode administratif (plan §1, §5, §6)
# ============================================================================

MODEL_GENERATOR_CHAMP_CIBLE = "google/gemini-2.5-flash"  # même modèle que main.py:MODEL_GENERATOR

SEUIL_ECHECS_CHAMP = 3       # 3 réponses invalides de suite sur un champ -> cas_particulier (signal)
SEUIL_RAPPELS_DOCUMENT = 3   # 3 rappels sans réception -> cas_particulier, on avance quand même (§5)

# Les messages de demande de pièce vivent en base depuis l'étape 2.3
# (`demarche_documents.message_demande` / `messages_rappel`, migration 018) —
# ils étaient écrits ici, ce qui obligeait à modifier Python pour corriger une
# tournure. Rien n'a changé par ailleurs : toujours aucun appel au modèle, ce
# sont des instructions fixes pensées pour un citoyen qui ne lit pas (poser le
# document à plat, sans ombre, bouton photo), et toujours au moins deux
# variantes de relance, alternées, pour qu'aucun rappel ne répète le précédent
# mot pour mot. Lecture : `services/demarche.message_document`.


async def _call_openrouter_structured_isole(headers: dict, payload: dict, retries: int = 2) -> dict:
    """
    Variante autonome de main.call_openrouter_structured (même logique de
    retry sur JSON tronqué/invalide, cf. commentaire original dans main.py) —
    dupliquée ici plutôt qu'importée pour ne PAS faire dépendre slot_controller
    de main.py (qui, lui, importera slot_controller en Tâche J.5 — un import
    dans l'autre sens créerait un cycle).
    """
    last_exc = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(retries + 1):
            try:
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload
                )
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError) as e:
                last_exc = e
                continue
            contenu = data["choices"][0]["message"]["content"]
            try:
                return json.loads(contenu)
            except json.JSONDecodeError as e:
                last_exc = e
                print(f"⚠️ JSON structuré invalide (champ ciblé, tentative {attempt + 1}/{retries + 1}) : {contenu[:200]!r}")
    raise last_exc


async def _citoyen_dit_ne_pas_avoir(type_document: str, message: str, headers: dict) -> bool:
    """
    Tâche J.6 : classification LLM légère (structurée, indépendante de la
    langue — même principe que SCHEMA_REPONSE_INFORMATION) — le citoyen
    dit-il CLAIREMENT ne pas avoir ce document ? Permet d'avancer dès ce
    refus explicite, sans attendre SEUIL_RAPPELS_DOCUMENT rappels.
    """
    payload = {
        "model": MODEL_GENERATOR_CHAMP_CIBLE,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_DOCUMENT_INDISPONIBLE},
            {"role": "user", "content": build_prompt_document_indisponible(type_document, message)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "document_indisponible", "strict": True, "schema": SCHEMA_DOCUMENT_INDISPONIBLE},
        },
        "stream": False,
        "temperature": 0.1,
    }
    try:
        parsed = await _call_openrouter_structured_isole(headers, payload)
        return bool(parsed.get("dit_ne_pas_avoir"))
    except Exception as e:
        print(f"⚠️ Classification 'document indisponible' échouée ({e}) — traité comme false (pas de refus détecté).")
        return False


_PREFIXES_ANTI_REPETITION = ["Je reformule : ", "Autrement dit : ", "Pour être plus clair : "]


def _eviter_repetition(etat: dict, cle: str, phrase: "phrases.Phrase") -> "phrases.Phrase":
    """
    Garde-fou déterministe (Tâche J.6) : garantit que le texte renvoyé au
    citoyen n'est JAMAIS mot pour mot identique à celui envoyé au tour
    précédent pour la même étape (`cle` = nom_champ ou "document:<type>") —
    en plus de la consigne donnée au LLM (Tâche J.3) de varier sa
    reformulation, qui ne suffit pas seule à le GARANTIR (un même message
    citoyen invalide, envoyé deux fois de suite, pourrait en théorie produire
    la même reformulation LLM à l'identique).
    """
    dernieres = etat.setdefault("dernieres_reponses", {})
    if dernieres.get(cle) == phrase.francais:
        compteurs_variation = etat.setdefault("compteurs_variation", {})
        compteurs_variation[cle] = compteurs_variation.get(cle, 0) + 1
        prefixe = _PREFIXES_ANTI_REPETITION[compteurs_variation[cle] % len(_PREFIXES_ANTI_REPETITION)]
        # Le préfixe est ajouté au français seulement : il invalide le pulaar
        # validé, qui ne contient pas cette amorce. Mieux vaut retraduire ce
        # tour-là que dire une phrase qui ne correspond pas au texte.
        phrase = phrases.Phrase(francais=f"{prefixe}{phrase.francais}", origine=phrase.origine)
    dernieres[cle] = phrase.francais
    return phrase


def _signaler_champ_en_echec(etat: dict, nom_champ: str, derniere_raison: str | None) -> str | None:
    """
    Tâche J.6 : écrit réellement un `cas_particulier` (`type_incident=
    "champ_manquant"`) quand SEUIL_ECHECS_CHAMP est atteint sur un champ —
    remplace le simple signal `cas_particulier_cree` (sans écriture) de la
    Tâche J.4. Retourne l'id créé, ou None si pas de dossier persisté ou si
    l'écriture échoue (jamais bloquant pour le tour en cours).
    """
    if not etat.get("dossier_id"):
        return None
    cas = create_cas_particulier(
        etat["dossier_id"],
        type_incident="champ_manquant",
        description=(
            f"Le champ '{nom_champ}' n'a pas pu être rempli après {SEUIL_ECHECS_CHAMP} tentatives. "
            f"Dernière raison : {derniere_raison or 'réponse hors sujet ou incomprise'}."
        ),
    )
    return cas["id"] if cas else None


# Les deux chargeurs délèguent à `services/demarche.py` (étape 2.3) : un seul
# point d'accès aux tables de définition, un seul cache, un seul repli quand la
# base est injoignable.
def charger_definition_demarche(type_demarche: str, version: int | None = None) -> list:
    """Champs d'une démarche (`demarche_champs`), triés par `ordre`."""
    return demarche.champs(type_demarche, version)


def charger_documents_demarche(type_demarche: str, version: int | None = None) -> list:
    """Documents d'une démarche (`demarche_documents`), triés par `ordre`."""
    return demarche.documents(type_demarche, version)


def _champ_est_rempli(champ: dict, slots: dict) -> bool:
    valeur = slots.get(champ["nom_champ"])
    if champ["type_valeur"] == "age":
        v = valeur or {}
        return v.get("valeur") is not None and bool(v.get("unite"))
    return valeur is not None


def condition_de(ligne: dict) -> str | None:
    """
    La condition d'une ligne de définition (champ ou document).

    `condition` (migration 017) fait foi. À défaut, l'ancienne colonne
    `condition_champ` est relue et traduite : elle ne savait exprimer qu'une
    chose, « ce champ est vrai ». Le moteur fonctionne donc que la migration
    017 soit appliquée ou non.
    """
    condition = (ligne.get("condition") or "").strip()
    if condition:
        return condition
    champ = ligne.get("condition_champ")
    return f"{champ} = oui" if champ else None


def _etape_demandable(ligne: dict, slots: dict) -> bool:
    """
    Vrai seulement si la condition est CERTAINEMENT vraie.

    Une condition indéterminée (le champ dont elle dépend n'est pas encore
    renseigné) ne fait pas demander l'étape tout de suite — elle reviendra
    d'elle-même quand la réponse sera connue, puisque l'étape courante est
    recalculée à chaque tour.
    """
    return conditions.evaluer(condition_de(ligne), slots) == conditions.VRAI


def grouper_documents(definition_documents: list) -> list[list[dict]]:
    """
    Regroupe les documents en groupes ALTERNATIFS — une seule pièce du groupe
    suffit (certificat médical OU deux témoins ; livret de famille OU
    certificat de mariage).

    La colonne `groupe` (migration 017) nomme le groupe explicitement. Les
    lignes qui ne l'ont pas encore retombent sur la convention historique : un
    même `ordre` valait appartenance au même groupe. Cette convention était
    invisible dans le schéma et se cassait en renumérotant un ordre, d'où la
    colonne — mais elle reste comprise tant que des lignes ne sont pas migrées.
    """
    groupes: dict = {}
    for doc in definition_documents:
        cle = doc.get("groupe") or f"ordre:{doc['ordre']}"
        groupes.setdefault(cle, []).append(doc)
    return sorted(groupes.values(), key=lambda g: min(d["ordre"] for d in g))


def _etapes_ordonnees(definition_champs: list, definition_documents: list) -> list[tuple]:
    """Champs et groupes de documents dans l'ordre où le dialogue les demande."""
    etapes = [("champ", c["ordre"], c) for c in definition_champs] + [
        ("document", min(d["ordre"] for d in groupe), groupe)
        for groupe in grouper_documents(definition_documents)
    ]
    etapes.sort(key=lambda t: t[1])
    return etapes


def champs_obligatoires_manquants(
    slots: dict,
    definition_champs: list,
    champs_ignores: set | None = None,
) -> list[str]:
    """
    Les champs OBLIGATOIRES encore vides que le dialogue peut encore demander.

    Sert de dernier verrou avant la relecture (RG7) : tant qu'il en reste un,
    on ne relit pas un dossier incomplet au citoyen et on ne l'envoie pas à la
    mairie.

    Lit la DÉFINITION de la démarche, jamais une liste écrite dans le code.
    L'ancienne liste en dur ne connaissait que l'extrait de naissance : pour la
    constatation de mariage et la déclaration de décès, elle réclamait
    éternellement des champs qui n'existent pas dans ces démarches, et le
    dialogue ne pouvait jamais aboutir.

    Un champ écarté par sa condition ne manque pas (il ne sera pas demandé).
    Un champ dont la condition est encore INCONNUE manque, lui : on ne relit
    pas un dossier tant qu'on ignore s'il est complet.
    """
    ignores = champs_ignores or set()
    return [
        champ["nom_champ"]
        for champ in definition_champs
        if champ.get("obligatoire")
        and champ["nom_champ"] not in ignores
        and not _champ_est_rempli(champ, slots)
        and conditions.evaluer(condition_de(champ), slots) != conditions.FAUX
    ]


def progression(
    slots: dict,
    documents_satisfaits: set,
    definition_champs: list,
    definition_documents: list,
    champs_ignores: set | None = None,
) -> dict:
    """
    Où en est le citoyen : `{"faites": n, "total": m}` sur les MÊMES étapes que
    `determiner_etape_courante` — c'est la seule façon d'être sûr que la barre
    montre l'avancement réel du dialogue et non un décompte parallèle qui
    dériverait au premier champ conditionnel.

    Une étape écartée par sa condition (« nom du père » quand les parents ne
    sont pas mariés) ne compte dans aucun des deux nombres : elle ne sera
    jamais demandée. Une condition encore INCONNUE compte au total — elle peut
    encore arriver. **Le total peut donc bouger en cours de dialogue** : c'est
    la vérité de ces démarches, où les questions dépendent des réponses.
    """
    ignores = champs_ignores or set()
    faites = total = 0

    for type_etape, _ordre, contenu in _etapes_ordonnees(definition_champs, definition_documents):
        if type_etape == "champ":
            satisfaite = contenu["nom_champ"] in ignores or _champ_est_rempli(contenu, slots)
            ligne = contenu
        else:
            satisfaite = any(d["type_document"] in documents_satisfaits for d in contenu)
            ligne = contenu[0]

        if satisfaite:
            faites += 1
            total += 1
        elif conditions.evaluer(condition_de(ligne), slots) != conditions.FAUX:
            total += 1

    return {"faites": faites, "total": total}


def determiner_etape_courante(
    slots: dict,
    documents_recus: set,
    definition_champs: list,
    definition_documents: list,
    champs_ignores: set | None = None,
) -> dict | None:
    """
    Première étape (champ OU document) non satisfaite, dans l'ordre combiné
    des deux tables (plan §1/§3). Retourne `None` si tout est satisfait —
    l'appelant doit alors déclencher RG7 (relecture), pas ce module (spécifique
    à extrait_naissance tant que la Tâche J.7 optionnelle n'est pas faite).

    Trois façons d'écarter une étape :
      - sa `condition` n'est pas vraie (cf. `_etape_demandable`) ;
      - pour un groupe de documents, l'un des types a déjà été reçu ;
      - pour un champ, il figure dans `champs_ignores` — un champ FACULTATIF
        auquel le citoyen n'a pas su répondre (plan étape 2.1, forme 1). Sans
        cela, un champ non obligatoire bloquait la collecte aussi sûrement
        qu'un champ obligatoire : le moteur ne lisait jamais la colonne.
    """
    ignores = champs_ignores or set()

    for type_etape, _ordre, contenu in _etapes_ordonnees(definition_champs, definition_documents):
        if type_etape == "champ":
            if contenu["nom_champ"] in ignores or _champ_est_rempli(contenu, slots):
                continue
            if not _etape_demandable(contenu, slots):
                continue
            return {"type": "champ", "definition": contenu}
        else:
            groupe = contenu
            if not _etape_demandable(groupe[0], slots):
                continue
            if any(d["type_document"] in documents_recus for d in groupe):
                continue  # au moins un type du groupe reçu -> groupe satisfait
            return {"type": "document", "groupe": groupe}

    return None


def _resultat(reponse: phrases.Reponse, **reste) -> dict:
    """
    Le résultat d'un tour.

    `reponse` porte les morceaux avec leur pulaar validé ; `reponse_fr` reste
    le texte français assemblé, pour tout ce qui l'attend déjà (affichage,
    historique, enregistrement du message).
    """
    return {"reponse": reponse, "reponse_fr": reponse.francais or None, **reste}


def _reponse_pour_etape(etape: dict | None, confirmation: phrases.Phrase | None = None) -> dict:
    """
    Construit le résultat pour ENCHAÎNER sur `etape` (celle qui suit une
    validation réussie) — le LLM ciblé (Tâche J.3) ne pose JAMAIS lui-même la
    question suivante, c'est au code de le faire (cf. SYSTEM_PROMPT_CHAMP_CIBLE).
    """
    if etape is None:
        return _resultat(phrases.Reponse(()), document_attendu=None, phase_suivante="complet")
    if etape["type"] == "champ":
        return _resultat(
            phrases.reponse(confirmation, demarche.question_champ(etape["definition"])),
            document_attendu=None,
            phase_suivante="collecte",
        )
    ligne_document = etape["groupe"][0]
    return _resultat(
        phrases.reponse(confirmation, demarche.message_document(ligne_document, tentative=0)),
        document_attendu=ligne_document["type_document"],
        phase_suivante="collecte",
    )


#: Ce que l'agent dit selon la nature du tour. La question du champ est
#: reposée ensuite, sauf pour une demande de pause : à quoi bon répéter la
#: question à quelqu'un qui vient de demander un instant.
_REPONSE_SOCIALE = {
    tours_sociaux.SALUTATION: ("social_salutation", True),
    tours_sociaux.REMERCIEMENT: ("social_remerciement", True),
    tours_sociaux.PATIENCE: ("social_patience", False),
    # Une demande de répétition n'appelle aucune phrase d'introduction : la
    # question reposée EST la réponse. Y ajouter « je n'ai pas compris »
    # inverserait les rôles — c'est le citoyen qui n'a pas entendu.
    tours_sociaux.REPETITION: (None, True),
}


def _repondre_tour_social(etat: dict, champ: dict, nature: str) -> dict:
    """
    Répond à un tour de politesse sans le compter comme un échec.

    Ni `compteurs` ni `raisons` ne sont touchés : le champ reste visé, et le
    citoyen dispose toujours de ses trois essais pour y répondre.
    """
    cle_phrase, reposer_question = _REPONSE_SOCIALE[nature]
    morceaux = []
    if cle_phrase is not None:
        morceaux.append(demarche.phrase_systeme(cle_phrase))
    if reposer_question:
        morceaux.append(demarche.question_champ(champ))
    return _resultat(
        phrases.reponse(*morceaux),
        document_attendu=None,
        phase_suivante="collecte",
        cas_particulier_cree=False,
    )


def _abandonner_champ(
    etat: dict,
    champ: dict,
    raison: str | None,
    champs_ignores: set,
    *,
    repli: phrases.Phrase | None,
    suite: Callable[[phrases.Phrase], dict],
) -> dict:
    """
    Le citoyen n'a pas su répondre à ce champ après SEUIL_ECHECS_CHAMP essais.

    La suite dépend de `obligatoire` (plan étape 2.1, forme 1), colonne que le
    moteur ne lisait pas :
      - champ OBLIGATOIRE : inchangé — un `cas_particulier` est écrit, un agent
        reprendra le dossier, et la question reste posée.
      - champ FACULTATIF : on passe à la suite et on le dit. Auparavant, un
        champ facultatif sans réponse revenait indéfiniment, exactement comme
        un champ obligatoire : la colonne n'avait aucun effet.
    """
    nom_champ = champ["nom_champ"]
    if champ.get("obligatoire", True):
        cas_particulier_id = _signaler_champ_en_echec(etat, nom_champ, raison)
        return _resultat(
            phrases.reponse(repli or demarche.question_champ(champ)),
            document_attendu=None,
            phase_suivante="collecte",
            cas_particulier_cree=True,
            champ_en_echec=nom_champ,
            cas_particulier_id=cas_particulier_id,
        )

    champs_ignores.add(nom_champ)
    # Enchaîner tout de suite sur l'étape suivante : un citoyen qui ne lit pas
    # n'a aucun moyen de deviner qu'il doit reparler devant un « on continue »
    # qui ne demande rien.
    resultat = suite(demarche.phrase_systeme("champ_facultatif_abandonne"))
    resultat["cas_particulier_cree"] = False
    resultat["champ_ignore"] = nom_champ
    return resultat


def _resultat_blocage(violation: regles_demarche.Violation) -> dict:
    """
    Fin de parcours : la démarche ne peut pas aboutir en l'état (délai dépassé).

    Le message vient de la règle, pas du code : c'est lui qui oriente le
    citoyen vers la bonne procédure, et il diffère d'une règle à l'autre
    (jugement d'autorisation d'inscription tardive, autre démarche, tribunal).
    """
    return _resultat(
        phrases.depuis_texte(violation.message, origine=f"regle:{violation.code}"),
        document_attendu=None,
        phase_suivante="bloque",
        cas_particulier_cree=False,
        regle_declenchee=violation.code,
    )


async def _tour_administratif(etat: dict, message: str, headers: dict, contexte: dict,
                              sans_interpreter: bool = False) -> dict:
    """
    Orchestrateur complet du mode administratif (plan §1) — destiné à
    remplacer, en Tâche J.5, le bloc `elif etat["mode"] == "administratif":`
    de main.py. Détermine le champ/document COURANT (le code décide, jamais le
    LLM), n'interroge le LLM que sur CE champ précis (Tâche J.3), valide
    déterministiquement (`valider_valeur`, Tâche J.2), et n'avance QUE si
    valide — sinon reformule et reboucle sur la MÊME étape, sans jamais
    avancer silencieusement.

    `etat` : le même état en mémoire qu'un `dossier_sessions[session_id]`
    (au minimum `slots`, `dossier_id`, `type_demarche` optionnel — défaut
    "extrait_naissance", seule démarche existante). Deux clés internes sont
    créées à la volée si absentes et PERSISTENT d'un tour à l'autre dans le
    même `etat` (mutation en place, comme le fait déjà main.py pour `slots`) :
      - `compteurs_echecs` : dict nom_champ/"document:<type>" -> int
      - `dernieres_raisons`: dict nom_champ -> dernière raison d'échec (pour
        contextualiser la reformulation LLM du TOUR SUIVANT sur ce champ,
        cf. build_prompt_champ_cible)

    Document réellement bloquant (plan §5) : un document n'est jamais
    considéré reçu parce qu'il a été demandé — SEULE une ligne correspondante
    dans `list_documents(dossier_id)` (vérifiée À CHAQUE TOUR, pas une fois)
    compte. Garde-fou anti-blocage infini : au-delà de SEUIL_RAPPELS_DOCUMENT
    rappels sans réception, un cas_particulier est signalé et le dialogue
    avance quand même (jamais de boucle sans issue).

    Retourne `{reponse_fr, document_attendu, phase_suivante, cas_particulier_cree, ...}` :
      - `phase_suivante` ∈ "collecte" (continuer) | "complet" (RG7 à
        déclencher par l'appelant — `reponse_fr` vaut alors `None`, car la
        relecture complète remplace toujours la réponse du tour, même
        principe que l'ancien code : `construire_recapitulatif` écrase la
        réponse du LLM dès que `dossier_complet()`).
      - `cas_particulier_cree` : True si le seuil d'échecs/rappels est atteint
        (champ OU document) — un vrai `cas_particulier` est alors écrit en
        base (Tâche J.6, `create_cas_particulier`), son id renvoyé dans
        `cas_particulier_id`. Pour un document, "je ne l'ai pas" clairement
        exprimé par le citoyen (détecté via LLM, `_citoyen_dit_ne_pas_avoir`)
        déclenche la même issue IMMÉDIATEMENT, sans attendre le seuil de
        rappels (plan §5).
    """
    type_demarche = etat.get("type_demarche", "extrait_naissance")
    # Version figée au début du dialogue (étape 2.4) : tout ce tour lit la
    # MÊME version — champs, pièces et règles. Sans cela, une publication au
    # milieu d'un tour ferait valider une réponse contre des règles que le
    # citoyen n'a jamais vues.
    version = etat.get("demarche_version")
    definition_champs = charger_definition_demarche(type_demarche, version)
    definition_documents = charger_documents_demarche(type_demarche, version)
    contexte["definition_champs"] = definition_champs
    contexte["definition_documents"] = definition_documents
    regles = regles_demarche.charger_regles(type_demarche, version)
    compteurs = etat.setdefault("compteurs_echecs", {})
    raisons = etat.setdefault("dernieres_raisons", {})
    # Champs FACULTATIFS auxquels le citoyen n'a pas su répondre : écartés pour
    # de bon, comme `documents_ignores` plus bas pour les pièces.
    champs_ignores = etat.setdefault("champs_ignores", set())
    contexte["champs_ignores"] = champs_ignores

    # Délai qui interrompt la démarche (plan étape 2.1, forme 2). Évalué en
    # tête de tour, et pas seulement après une saisie : une session reprise
    # arrive déjà avec ses slots remplis, et six mois ont pu passer entre-temps.
    blocages = regles_demarche.evaluer_regles(regles, etat["slots"], effets=(regles_demarche.BLOQUER,))
    if blocages:
        return _resultat_blocage(blocages[0])
    # Documents dont le garde-fou anti-blocage infini (§5) a déjà été déclenché
    # (seuil de rappels dépassé) : traités comme satisfaits pour la suite du
    # dialogue, SANS jamais avoir été réellement reçus — sinon la même
    # étape reviendrait indéfiniment au tour suivant malgré le message
    # "on continue sans cette photo" déjà envoyé au citoyen.
    documents_ignores = etat.setdefault("documents_ignores", set())

    documents_recus = set()
    if etat.get("dossier_id"):
        documents_recus = {d["type"] for d in list_documents(etat["dossier_id"])}
    documents_satisfaits = documents_recus | documents_ignores
    contexte["documents_satisfaits"] = documents_satisfaits

    etape = determiner_etape_courante(
        etat["slots"], documents_satisfaits, definition_champs, definition_documents, champs_ignores
    )

    def enchainer(confirmation: phrases.Phrase | None) -> dict:
        """La question suivante, une fois l'étape courante réglée."""
        return _reponse_pour_etape(
            determiner_etape_courante(
                etat["slots"], documents_satisfaits, definition_champs, definition_documents, champs_ignores
            ),
            confirmation,
        )

    if etape is None:
        return _resultat(
            phrases.Reponse(()), document_attendu=None, phase_suivante="complet", cas_particulier_cree=False
        )

    # -----------------------------------------------------------------
    # Étape = DOCUMENT : AUCUN appel LLM ici — vérification déterministe en
    # base (plan §5). "déjà demandé à voix haute" NE COMPTE JAMAIS : tant que
    # list_documents() ne le confirme pas, on rappelle (reformulé, pas répété).
    # -----------------------------------------------------------------
    if etape["type"] == "document":
        groupe = etape["groupe"]
        type_principal = groupe[0]["type_document"]
        obligatoire = any(d["obligatoire"] for d in groupe)
        cle = f"document:{type_principal}"
        tentatives_precedentes = compteurs.get(cle, 0)  # 0 = jamais encore demandé
        compteurs[cle] = tentatives_precedentes + 1

        # Détection explicite "je ne l'ai pas" (Tâche J.6) — seulement à
        # partir du 2e tour sur CE document : au tout premier tour, `message`
        # répond encore à la question PRÉCÉDENTE (celle qui a fait avancer
        # jusqu'à ce document), pas à la demande de photo qui vient d'être
        # posée à l'instant — la classifier n'aurait aucun sens.
        dit_ne_pas_avoir = False
        if tentatives_precedentes >= 1:
            dit_ne_pas_avoir = await _citoyen_dit_ne_pas_avoir(type_principal, message, headers)

        if dit_ne_pas_avoir or compteurs[cle] > SEUIL_RAPPELS_DOCUMENT:
            # Garde-fou anti-blocage infini (§5) : jamais une boucle sans
            # issue, obligatoire ou non — seul le TEXTE diffère. Mémorise le
            # groupe entier comme "satisfait" (documents_ignores) pour de bon,
            # sinon la même étape reviendrait au tour suivant.
            compteurs[cle] = 0
            for d in groupe:
                documents_ignores.add(d["type_document"])
            phrase_abandon = demarche.phrase_systeme(
                "document_obligatoire_abandonne" if obligatoire else "document_facultatif_abandonne"
            )
            cas_particulier_id = None
            if etat.get("dossier_id"):
                motif = "déclaré indisponible par le citoyen" if dit_ne_pas_avoir else f"aucune réponse après {SEUIL_RAPPELS_DOCUMENT} rappels"
                cas = create_cas_particulier(
                    etat["dossier_id"],
                    type_incident="document_indisponible",
                    description=f"Document '{type_principal}' {motif}.",
                )
                cas_particulier_id = cas["id"] if cas else None
            return _resultat(
                phrases.reponse(phrase_abandon),
                document_attendu=None,
                phase_suivante="collecte",
                cas_particulier_cree=True,
                document_ignore=type_principal,
                cas_particulier_id=cas_particulier_id,
            )

        demande = demarche.message_document(groupe[0], tentative=tentatives_precedentes)
        demande = _eviter_repetition(etat, cle, demande)

        # --- Dire qu'on a entendu, même si ce n'est pas ce qu'on attend ----
        #
        # Pendant l'attente d'une photo, tout ce que dit le citoyen était
        # écarté EN SILENCE : il entendait la demande de photo se répéter,
        # sans le moindre signe qu'on l'avait écouté. Observé en jouant le
        # dialogue — « Ibrahima Diallo » n'a reçu aucun accusé, et ce nom est
        # tombé dans le vide.
        #
        # On ne tente PAS d'en extraire une valeur : le dialogue traite une
        # information à la fois, et deviner à quel champ ce message répondrait
        # reviendrait sur cette discipline. On dit seulement qu'on l'a entendu,
        # et qu'il faut la photo d'abord.
        #
        # Au PREMIER tour sur ce document, le message répond encore à la
        # question précédente, pas à la demande de photo : rien à accuser.
        # Et une simple politesse n'appelle pas cet accusé — elle a déjà sa
        # réponse ailleurs.
        entendu = None
        if tentatives_precedentes >= 1 and message and not tours_sociaux.est_sans_substance(message):
            entendu = demarche.phrase_systeme("document_message_entendu")

        return _resultat(
            phrases.reponse(entendu, demande),
            document_attendu=type_principal,
            phase_suivante="collecte",
            cas_particulier_cree=False,
        )

    # -----------------------------------------------------------------
    # Étape = CHAMP : UN SEUL appel LLM, scopé à ce champ précis (Tâche J.3) —
    # il ne voit structurellement aucun autre champ du dossier.
    # -----------------------------------------------------------------
    champ = etape["definition"]
    nom_champ = champ["nom_champ"]

    # --- Rien à interpréter dans ce message ? --------------------------
    #
    # Au moment où le citoyen accepte de commencer, le moteur rejoue son
    # message ici. C'est voulu : « je veux un extrait pour mon fils de sept
    # jours » contient déjà la première réponse. Mais sur un simple « eey »,
    # il n'y a rien à extraire — et le modèle jugeait alors la réponse
    # invalide, si bien que la PREMIÈRE question de chaque démarche arrivait
    # précédée de « Je n'ai pas bien compris ».
    #
    # L'appelant sait distinguer les deux cas (intentions.est_confirmation_seule).
    # Ici on se contente de poser la question, sans excuse et sans compteur.
    if sans_interpreter:
        return _resultat(
            phrases.reponse(demarche.question_champ(champ)),
            document_attendu=None,
            phase_suivante="collecte",
            cas_particulier_cree=False,
        )

    # --- Ensuite : est-ce seulement de la politesse ? ------------------
    #
    # « Bonjour », « merci », « attends », « répète » ne répondent pas au
    # champ, et le modèle les jugeait donc invalides : l'agent répondait « Je
    # n'ai pas compris » à quelqu'un qui venait de le saluer. Pire, chaque
    # message de ce genre comptait comme un échec, et trois d'affilée
    # abandonnaient le champ — dire bonjour, merci et attends suffisait à
    # saboter sa propre demande.
    #
    # Ces tours-là ne sont pas des erreurs : ils reçoivent leur propre
    # réponse, la question est reposée telle quelle, et AUCUN compteur ne
    # bouge. Le tri est déterministe et n'avale jamais un message qui porte
    # aussi une réponse (cf. services/tours_sociaux.py).
    nature_sociale = tours_sociaux.classer(message)
    if nature_sociale is not None:
        return _repondre_tour_social(etat, champ, nature_sociale)

    prompt = build_prompt_champ_cible(champ, message, raisons.get(nom_champ))
    schema = build_schema_champ_cible(champ["type_valeur"], champ.get("regle_validation"))
    payload = {
        "model": MODEL_GENERATOR_CHAMP_CIBLE,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_CHAMP_CIBLE},
            {"role": "user", "content": prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "champ_cible", "strict": True, "schema": schema},
        },
        "stream": False,
        "temperature": 0.3,
    }
    parsed = await _call_openrouter_structured_isole(headers, payload)

    if not parsed.get("reponse_valide") or parsed.get("valeur") is None:
        # Le modèle juge que le message ne répond pas à CE champ (ex. le
        # citoyen a parlé d'une autre personne, Tâche J.3). Sa reformulation
        # n'est PLUS dite au citoyen (étape 3) : elle était improvisée, donc
        # retraduite à chaque fois, au moment précis où le citoyen a déjà du
        # mal à suivre. On dit une relance écrite d'avance, traduisible une
        # fois pour toutes.
        compteurs[nom_champ] = compteurs.get(nom_champ, 0) + 1
        relance = _eviter_repetition(
            etat, nom_champ, demarche.relance_champ(champ, compteurs[nom_champ] - 1)
        )
        if compteurs[nom_champ] >= SEUIL_ECHECS_CHAMP:
            compteurs[nom_champ] = 0
            return _abandonner_champ(
                etat, champ, parsed.get("reponse"), champs_ignores,
                repli=relance, suite=enchainer,
            )
        raisons[nom_champ] = parsed.get("reponse") or "réponse hors sujet"
        return _resultat(
            phrases.reponse(relance),
            document_attendu=None,
            phase_suivante="collecte",
            cas_particulier_cree=False,
        )

    # Le LLM juge la réponse valide -> le VRAI garde-fou est ici : validation
    # déterministe, zéro confiance aveugle dans le jugement du LLM (Tâche J.2).
    valide, valeur_normalisee, raison_erreur = valider_valeur(
        champ["type_valeur"], parsed["valeur"], champ.get("regle_validation"), valeurs_connues=etat["slots"]
    )

    if not valide:
        compteurs[nom_champ] = compteurs.get(nom_champ, 0) + 1
        raisons[nom_champ] = raison_erreur
        refus = phrase_refus(raison_erreur)
        if compteurs[nom_champ] >= SEUIL_ECHECS_CHAMP:
            compteurs[nom_champ] = 0
            raisons.pop(nom_champ, None)
            return _abandonner_champ(
                etat, champ, raison_erreur, champs_ignores, repli=refus, suite=enchainer
            )
        # Le motif du refus, puis la question reposée : deux morceaux, chacun
        # avec son pulaar validé s'il en a un.
        question = _eviter_repetition(etat, nom_champ, demarche.question_champ(champ))
        return _resultat(
            phrases.reponse(refus, question),
            document_attendu=None,
            phase_suivante="collecte",
            cas_particulier_cree=False,
        )

    # Valide : enregistrer et avancer — jamais un avancement silencieux avant ce point.
    etat["slots"][nom_champ] = valeur_normalisee
    compteurs[nom_champ] = 0
    raisons.pop(nom_champ, None)

    # Combinaison interdite entre deux champs (plan étape 2.1, forme 3) : la
    # valeur vient d'être écrite, c'est seulement maintenant qu'on peut savoir
    # si elle est incompatible avec une réponse précédente. Elle est alors
    # RETIRÉE — un dossier ne doit jamais garder une combinaison illégale — et
    # la question est reposée.
    interdictions = regles_demarche.evaluer_regles(regles, etat["slots"], effets=(regles_demarche.INTERDIRE,))
    if interdictions:
        violation = interdictions[0]
        champ_a_reprendre = violation.champ or nom_champ
        etat["slots"].pop(champ_a_reprendre, None)
        definition_a_reprendre = next(
            (c for c in definition_champs if c["nom_champ"] == champ_a_reprendre), champ
        )
        raisons[champ_a_reprendre] = violation.message
        return _resultat(
            phrases.reponse(
                phrases.Phrase(francais=violation.message, origine=f"regle:{violation.code}"),
                _eviter_repetition(etat, champ_a_reprendre, demarche.question_champ(definition_a_reprendre)),
            ),
            document_attendu=None,
            phase_suivante="collecte",
            cas_particulier_cree=False,
            regle_declenchee=violation.code,
        )

    blocages = regles_demarche.evaluer_regles(regles, etat["slots"], effets=(regles_demarche.BLOQUER,))
    if blocages:
        return _resultat_blocage(blocages[0])

    # La confirmation du modèle n'est plus dite non plus : « C'est noté » est
    # la même phrase à chaque fois, elle n'a aucune raison d'être réinventée
    # puis retraduite.
    resultat = enchainer(demarche.phrase_systeme("confirmation_reponse"))
    resultat["cas_particulier_cree"] = False
    return resultat


async def traiter_tour_administratif(etat: dict, message: str, headers: dict,
                                     sans_interpreter: bool = False) -> dict:
    """
    Le tour administratif, plus l'avancement dans la démarche.

    La progression est calculée APRÈS le tour, sur l'état qu'il laisse : elle
    dit donc « voilà où vous en êtes maintenant », et non où on en était avant
    la réponse. Elle est absente quand le tour s'arrête avant d'avoir regardé
    les pièces (démarche bloquée par une règle) : il n'y a alors plus
    d'avancement à montrer.
    """
    contexte: dict = {}
    resultat = await _tour_administratif(etat, message, headers, contexte, sans_interpreter)
    if "documents_satisfaits" in contexte:
        resultat["manquants"] = champs_obligatoires_manquants(
            etat["slots"], contexte["definition_champs"], contexte["champs_ignores"]
        )
        resultat["progression"] = progression(
            etat["slots"],
            contexte["documents_satisfaits"],
            contexte["definition_champs"],
            contexte["definition_documents"],
            contexte["champs_ignores"],
        )
    return resultat


def verifier_document_recu_et_avancer(etat: dict) -> dict | None:
    """
    Bug réel remonté en test terrain (2026-08-24) : après avoir envoyé la
    photo demandée (POST /dossiers/{id}/documents, REST — canal séparé du
    WebSocket), le dialogue restait SILENCIEUX tant que le citoyen ne
    reparlait pas de lui-même — vérifié : le backend redémarrait bien la
    conversation dès que le citoyen reparlait (pas un vrai deadlock), mais un
    citoyen analphabète n'a aucun moyen de deviner qu'il doit reparler sans
    qu'on le lui dise. Cette fonction permet à l'appelant (main.py,
    `notifier_document_recu`) de pousser la confirmation + la question
    suivante immédiatement après un upload réel, SANS attendre un nouveau
    message vocal.

    Contrairement à `traiter_tour_administratif`, AUCUN appel LLM ici : pas de
    message du citoyen à traiter, juste une ré-évaluation de l'étape courante
    maintenant que `list_documents(dossier_id)` a changé.

    Retourne le même format que `traiter_tour_administratif` (`reponse_fr`,
    `document_attendu`, `phase_suivante`, `cas_particulier_cree`) pour la
    NOUVELLE étape, ou `None` si rien n'a changé (le document attendu n'est
    toujours pas là, ou l'étape courante n'est de toute façon pas un document
    — rien à pousser dans ce cas, le citoyen n'a rien à confirmer).
    """
    if not etat.get("dossier_id"):
        return None

    type_demarche = etat.get("type_demarche", "extrait_naissance")
    version = etat.get("demarche_version")
    definition_champs = charger_definition_demarche(type_demarche, version)
    definition_documents = charger_documents_demarche(type_demarche, version)
    documents_ignores = etat.setdefault("documents_ignores", set())
    documents_recus = {d["type"] for d in list_documents(etat["dossier_id"])}
    documents_satisfaits = documents_recus | documents_ignores

    etape = determiner_etape_courante(etat["slots"], documents_satisfaits, definition_champs, definition_documents)

    if etape is not None and etape["type"] == "document":
        type_principal = etape["groupe"][0]["type_document"]
        deja_demande = type_principal in etat.get("documents_demandes", set())
        if deja_demande:
            # Toujours la même étape qu'avant cet upload -> le document reçu
            # ne correspondait pas à celui réellement attendu (upload d'un
            # autre type, ou doublon) : rien de nouveau à annoncer.
            return None

    resultat = _reponse_pour_etape(etape, confirmation=demarche.phrase_systeme("confirmation_photo"))
    resultat["cas_particulier_cree"] = False
    resultat["manquants"] = champs_obligatoires_manquants(
        etat["slots"], definition_champs, etat.get("champs_ignores")
    )
    return resultat
