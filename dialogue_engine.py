"""
dialogue_engine.py — Sprint B, Tâche B.1 (MEMOIR2/SUNU_MAIRIE_PROMPTS.md).

Détermination du cas légal (RG1/RG2/RG3, `DSF_SUNU-MAIRIE (1).md §5`) à partir
de l'âge de l'enfant en jours, et normalisation d'un âge exprimé dans une
unité quelconque (jours/semaines/mois/années) en jours.

Hypothèses de simplification assumées ici — à relire si contestées :

- RG1 dit littéralement « 1 mois après la naissance (jusqu'à 45 jours en zone
  rurale éloignée selon les sources) » : le DSF lui-même signale l'incertitude
  ("selon les sources") et ne fixe pas de seuil en jours exact. Les exemples
  de dialogue concrets (`Exemples_Dialogues_Agent_SUNU-MAIRIE.md`, 1.1/1.2/1.3)
  tranchent tous avec un seuil dur : "age < 30 jours" → dans_les_delais,
  "1 mois < age <= 1 an" → tardif, "age > 1 an" → jugement_requis. C'est cette
  convention (déjà utilisée ailleurs dans le projet) qui est implémentée ici.
- L'exception "jusqu'à 45 jours en zone rurale éloignée" n'est PAS implémentée :
  rien dans le modèle de données actuel (table `communes`) ne permet de
  distinguer une commune rurale éloignée d'une autre. À traiter en backlog si
  confirmé nécessaire par l'encadrant — ne pas deviner quelles communes
  qualifient.
- 1 mois = 30 jours, 1 an = 365 jours (conversion calendaire approximative,
  cohérente avec le seuil dur ci-dessus — pas de prise en compte des mois de
  durée variable ni des années bissextiles).
"""
from typing import Literal

CasLegal = Literal["dans_les_delais", "tardif", "jugement_requis"]

SEUIL_DANS_LES_DELAIS_JOURS = 30
SEUIL_JUGEMENT_REQUIS_JOURS = 365

# Alias tolérés côté unité (accord singulier/pluriel, avec/sans accent — les
# entités NLU des exemples de dialogue utilisent "jours"/"mois"/"annees").
JOURS_PAR_UNITE = {
    "jour": 1,
    "jours": 1,
    "semaine": 7,
    "semaines": 7,
    "mois": 30,
    "an": 365,
    "ans": 365,
    "annee": 365,
    "annees": 365,
    "année": 365,
    "années": 365,
}


def normaliser_age(valeur: float, unite: str) -> int:
    """
    Convertit un âge exprimé dans une unité arbitraire (jours/semaines/mois/
    années, cf. entités NLU de `Exemples_Dialogues_Agent_SUNU-MAIRIE.md`,
    exemple 1.1) en nombre entier de jours.

    Lève ValueError si l'unité n'est pas reconnue — mieux vaut un échec net,
    remonté au dialogue, qu'un cas légal silencieusement erroné.
    """
    unite_normalisee = unite.strip().lower()
    if unite_normalisee not in JOURS_PAR_UNITE:
        raise ValueError(
            f"Unité d'âge inconnue : {unite!r}. "
            f"Attendu l'une de : {sorted(set(JOURS_PAR_UNITE))}."
        )
    return round(valeur * JOURS_PAR_UNITE[unite_normalisee])


def determiner_cas_legal(age_jours: int) -> CasLegal:
    """
    RG1/RG2/RG3 (DSF §5), seuils durs (cf. docstring du module) :
      - age_jours <= 30        → "dans_les_delais"
      - 30 < age_jours <= 365  → "tardif"
      - age_jours > 365        → "jugement_requis"
    """
    if age_jours < 0:
        raise ValueError(f"age_jours ne peut pas être négatif : {age_jours}")
    if age_jours <= SEUIL_DANS_LES_DELAIS_JOURS:
        return "dans_les_delais"
    if age_jours <= SEUIL_JUGEMENT_REQUIS_JOURS:
        return "tardif"
    return "jugement_requis"


# ============================================================================
# Relecture obligatoire (RG7) — Sprint B, Tâche B.4.
#
# Nœud de dialogue codé en dur, jamais délégué au LLM : dès que tous les slots
# requis sont remplis, le tour suivant DOIT être le récapitulatif complet
# (cf. Exemples_Dialogues_Agent_SUNU-MAIRIE.md, exemple 2.1 — "RÈGLE
# OBLIGATOIRE (RG7 du DSF): cette étape ne peut jamais être sautée"). C'est le
# code (dialogue_engine.dossier_complet + construire_recapitulatif, appelés
# depuis main.py) qui décide et impose ce tour, pas une proposition du LLM.
# ============================================================================

# age_enfant n'est PAS dans cette liste : c'est une précondition d'entrée en
# mode administratif (cas_legal déjà déterminé dessus au moment de la
# bascule, cf. Tâche B.3), pas une question reposée dans la boucle de
# collecte UC2 — sa complétude est vérifiée séparément ci-dessous.
SLOTS_REQUIS_RELECTURE = [
    "commune_naissance",
    "nom_enfant",
    "date_naissance_enfant",
    "nom_declarant",
    "nom_mere",
    "date_naissance_mere",
    "parents_maries",
]


def slots_manquants(slots: dict) -> list:
    """
    Liste les slots requis (cf. SLOTS_REQUIS_RELECTURE + age_enfant) encore vides.

    ⚠️ HÉRITÉ, ET SPÉCIFIQUE À L'EXTRAIT DE NAISSANCE. Cette liste est écrite
    dans le code : pour la constatation de mariage ou la déclaration de décès,
    elle réclame éternellement des champs qui n'existent pas dans ces
    démarches. Elle a empêché ces deux dialogues d'aboutir jusqu'au correctif
    de l'étape 5.

    Pour savoir s'il reste quelque chose à demander, utilisez
    `slot_controller.champs_obligatoires_manquants`, qui lit la DÉFINITION de
    la démarche. Ne rebranchez pas celle-ci dans le moteur.
    """
    manquants = [cle for cle in SLOTS_REQUIS_RELECTURE if slots.get(cle) is None]
    age = slots.get("age_enfant") or {}
    if age.get("valeur") is None or not age.get("unite"):
        manquants.append("age_enfant")
    return manquants


def dossier_complet(slots: dict) -> bool:
    """True dès que tous les slots requis sont remplis — déclenche la relecture obligatoire."""
    return not slots_manquants(slots)


# ============================================================================
# Documents (upload de pièces) — Sprint B, Tâche B.5.
# ============================================================================

# Types valides pour POST /dossiers/{id}/documents — repris de l'enum retiré
# du CHECK SQL (migration 002_documents_type_texte_libre.sql), validé
# désormais côté applicatif plutôt qu'en base.
TYPES_DOCUMENT_VALIDES = [
    "certificat_naissance", "cni_declarant", "cni_conjoint",
    "livret_famille", "certificat_mariage",
    # Ajoutés Sprint J (retour terrain du 2026-08-24) : la CNI du déclarant
    # doit être photographiée recto ET verso (une seule face ne suffit pas à
    # un consultant pour la vérifier) — remplace "cni_declarant" comme type
    # demandé par le dialogue (cf. demarche_documents, migration 009).
    # "cni_declarant" reste une valeur valide (déjà utilisée par des documents
    # existants et par test_document_generator.py) — jamais retirée en place.
    "cni_declarant_recto", "cni_declarant_verso",
]

# Sous-ensemble effectivement demandé par le dialogue de l'extrait de
# naissance (cf. Exemples_Dialogues_Agent_SUNU-MAIRIE.md, exemple 2.1 — texte
# d'origine, la recto/verso CNI est une évolution Sprint J, migration 009).
# certificat_mariage existe dans le modèle pour une démarche future (ex. acte
# de mariage) — hors périmètre actuel (décision actée : extrait de naissance
# seul pour l'instant), mais devenu une ALTERNATIVE valide à livret_famille
# pour l'extrait de naissance aussi (cf. seed demarche_documents, Tâche J.1).
TYPES_DOCUMENT_EXTRAIT_NAISSANCE = [
    "certificat_naissance", "cni_declarant_recto", "cni_declarant_verso", "livret_famille", "certificat_mariage",
]

TYPES_MIME_DOCUMENT_VALIDES = ["image/jpeg", "image/png", "image/webp"]
MAX_DOCUMENT_BYTES = 15 * 1024 * 1024  # ~15 Mo : photo de pièce prise au téléphone


# ============================================================================
# Formulaires consultant (pré-remplissage depuis les slots) — Sprint C, Tâche C.3.
#
# Mapping VOLONTAIREMENT PARTIEL entre les slots du dialogue et les champs du
# formulaire consultant (alignés sur extrait_naissance.xsd, cf. Flux §2.2) :
# seuls les champs avec une correspondance 1:1 fiable sont pré-remplis
# (source="dialogue"). Les autres — ex. prenomEnfant/nomFamilleEnfant séparés
# de notre slot nom_enfant (un seul champ "nom complet"), sexe (jamais
# collecté à l'oral), prenomPere (le dialogue ne connaît que nom_declarant,
# pas garanti être le père) — restent vides (source="manuel"). On ne devine
# jamais une valeur non fournie explicitement (même principe que pour la
# géographie des communes ou la phonétique pulaar) : le consultant les lit
# sur l'image et les saisit, comportement V1 décrit dans le Flux.
# ============================================================================

CHAMPS_FORMULAIRE_PAR_TYPE_DOCUMENT = {
    "certificat_naissance": [
        "prenomEnfant", "nomFamilleEnfant", "dateNaissance", "lieuNaissance",
        "sexe", "prenomPere", "prenomMere", "nomFamilleMere",
        # Ajoutés en construisant la Tâche D.2 (oubliés ici en C.3) : ces 3
        # champs de acteNaissance (XSD) n'avaient pas de formulaire du tout.
        "dateNaissanceLettres", "heureNaissance", "paysNaissanceEtranger",
    ],
    "cni_declarant": ["nomDeclarant", "numeroCNI"],  # conservé pour compat (anciens documents/tests, cf. TYPES_DOCUMENT_VALIDES)
    # Recto/verso (Sprint J, étendu Sprint K.3 avec les champs réellement
    # extraits par le modèle OCR, cf. ocr_cni_service.py/CLASSES_CNI.md) :
    # "nomDeclarant"/"numeroCNI" restent les 2 champs pré-remplis DEPUIS LE
    # DIALOGUE (source="dialogue", cf. _MAPPING_CHAMP_VERS_SLOT) — les
    # nouveaux champs ci-dessous ne sont jamais pré-remplis par le dialogue,
    # seulement par l'OCR (source="ocr", fusionner_champs_ocr côté
    # slot_controller-like) ou saisis à la main. Mapping classe YOLO -> champ :
    # fname->prenomsDeclarant, lname->nomFamilleDeclarant, dob->dateNaissanceDeclarant,
    # sex->sexeDeclarant, id->numeroCNI, bp->lieuNaissanceDeclarant (recto) ;
    # region->regionDeclarant, dp->departementDeclarant, annot->arrondissementDeclarant,
    # com->communeDeclarant, bureau->numeroBureauVoteDeclarant, nin->ninDeclarant,
    # numero->numeroElecteurDeclarant, lieu->lieuVoteDeclarant (verso).
    "cni_declarant_recto": [
        "nomDeclarant", "prenomsDeclarant", "nomFamilleDeclarant",
        "dateNaissanceDeclarant", "sexeDeclarant", "numeroCNI", "lieuNaissanceDeclarant",
    ],
    "cni_declarant_verso": [
        "regionDeclarant", "departementDeclarant", "arrondissementDeclarant", "communeDeclarant",
        "numeroBureauVoteDeclarant", "ninDeclarant", "numeroElecteurDeclarant", "lieuVoteDeclarant",
    ],
    "cni_conjoint": ["nomConjoint", "numeroCNI"],
    "livret_famille": ["parentsMaries", "dateMariage"],
    "certificat_mariage": ["parentsMaries", "dateMariage"],
    # "extrait_naissance" = le document de SORTIE lui-même, pas une pièce
    # uploadée par le citoyen — trouvé nécessaire en construisant D.2
    # (document_generator.py) : numeroActe/registre, l'officier signataire et
    # le bloc jugement ne sont rattachés à AUCUN document photographié, ils
    # sont propres à l'acte final. Créé par
    # dossiers_repo.get_or_create_formulaire_acte(), pas via l'upload B.5.
    "extrait_naissance": [
        "numeroActe", "anneeRegistreLettres", "anneeRegistreChiffres",
        "numeroRegistreLettres", "numeroRegistreChiffres", "typeCentre",
        "officierEtatCivil", "notesMentionsMarginales",
        # Bloc jugement (uniquement pertinent si cas_legal == jugement_requis,
        # cf. XSD JugementSupplement) — jamais collecté à l'oral (décision Q1,
        # §1 du roadmap : le passage au tribunal reste physique).
        "tribunalOuJuge", "dateJugementLettres", "numeroJugementLettres",
        "numeroJugementChiffres", "dateInscriptionRegistre", "anneeJugement",
    ],
    # Idem pour le certificat de mariage constaté (étape 5.5) : le document de
    # SORTIE, pas une pièce photographiée. Le dialogue collecte tout ce qui
    # concerne les époux ; ce qui reste ici vient du REGISTRE PAPIER que le
    # consultant a sous les yeux — numéro et année du registre, mentions « en
    # toutes lettres », signataire. Sans ce formulaire, un dossier de mariage
    # complet ne pouvait pas être généré : le consultant n'avait nulle part où
    # saisir ces champs, et la génération échouait sans recours.
    # Ces noms sont ceux des attributs `cle` de templates/certificat_mariage_v1.xml.
    "constatation_mariage": [
        "numeroRegistreChiffres", "anneeRegistreLettres", "moisRegistreLettres",
        "heureRegistreLettres", "minuteRegistreLettres",
        "dateNaissanceEpouxLettres", "dateNaissanceEpouseLettres",
        "dateCelebrationLettres", "dateEnregistrementLettres",
        "typeCentre", "officierEtatCivil", "notesMentionsMarginales",
    ],
    # Acte de décès (étape 5.5). Le dialogue collecte tout ce qui concerne le
    # défunt et le déclarant ; ce qui reste vient du registre papier, du
    # certificat médical que le déclarant apporte (l'heure), ou de l'acte
    # français donné en exemple et non demandé à l'oral au Sénégal (âge,
    # profession et adresse du déclarant, nom du conjoint).
    # Noms = attributs `cle` de templates/acte_deces_v1.xml.
    "declaration_deces": [
        "numeroActe", "typeCentre",
        "dateNaissanceDefuntLettres", "nomConjointDefunt",
        "dateDecesLettres", "heureDecesLettres", "dateDressageLettres",
        "ageDeclarant", "professionDeclarant", "domicileDeclarant",
        "officierEtatCivil", "notesMentionsMarginales",
    ],
}

# Champ formulaire -> slot dialogue, uniquement les correspondances 1:1
# fiables (cf. avertissement ci-dessus). Un champ absent d'ici est toujours
# vide en V1, quel que soit l'état des slots.
_MAPPING_CHAMP_VERS_SLOT = {
    "dateNaissance": "date_naissance_enfant",
    "lieuNaissance": "commune_naissance",
    "nomDeclarant": "nom_declarant",
    "parentsMaries": "parents_maries",
    "sexe": "sexe_enfant",
}

# ============================================================================
# OCR CNI (Sprint K, Tâche K.3) — mapping classe YOLO -> champ formulaire.
# cf. model_OCR/CLASSES_CNI.md pour la taxonomie complète des 14 classes et
# ocr_cni_service.py pour l'appel au pipeline (YOLO + EasyOCR).
# ============================================================================

MAPPING_CLASSE_OCR_VERS_CHAMP = {
    # Recto
    "fname": "prenomsDeclarant",
    "lname": "nomFamilleDeclarant",
    "dob": "dateNaissanceDeclarant",
    "sex": "sexeDeclarant",
    "id": "numeroCNI",
    "bp": "lieuNaissanceDeclarant",
    # Verso
    "region": "regionDeclarant",
    "dp": "departementDeclarant",
    "annot": "arrondissementDeclarant",
    "com": "communeDeclarant",
    "bureau": "numeroBureauVoteDeclarant",
    "nin": "ninDeclarant",
    "numero": "numeroElecteurDeclarant",
    "lieu": "lieuVoteDeclarant",
}


def fusionner_champs_ocr(champs_existants: list, resultat_ocr: dict) -> list:
    """
    Met à jour la liste de champs d'un formulaire (`construire_champs_formulaire`)
    avec les résultats du pipeline OCR CNI (`ocr_cni_service.extraire_cni`,
    Tâche K.2) — utilisé par POST /consultant/dossiers/{id}/ocr-cni (K.4).

    Règles :
    - Un champ déjà `verifie_par_consultant=true` n'est JAMAIS écrasé — le
      consultant a déjà tranché, l'OCR ne doit pas revenir dessus.
    - `needs_review` (nouveau, absent des formulaires pré-OCR — `False` par
      défaut à la lecture) = `needs_review` du pipeline OU `not is_valid_format`
      : un champ jamais fiable (bp/lieu/fname/lname, cf. CLASSES_CNI.md) reste
      signalé quelle que soit sa confiance.
    - Un champ dont la classe OCR correspondante n'a rien détecté
      (`value_cleaned is None`) n'est pas modifié (garde sa valeur existante,
      `manuel` par défaut).
    """
    resultat = []
    for champ in champs_existants:
        champ = dict(champ)  # ne jamais muter l'original
        if champ.get("verifie_par_consultant"):
            resultat.append(champ)
            continue

        classe_ocr = next(
            (c for c, nom_champ in MAPPING_CLASSE_OCR_VERS_CHAMP.items() if nom_champ == champ["nom"]),
            None,
        )
        entree_ocr = resultat_ocr.get(classe_ocr) if classe_ocr else None
        if not entree_ocr or entree_ocr.get("value_cleaned") is None:
            resultat.append(champ)
            continue

        champ["valeur"] = entree_ocr["value_cleaned"]
        champ["source"] = "ocr"
        champ["confiance"] = entree_ocr.get("confidence_detection")
        champ["needs_review"] = bool(entree_ocr.get("needs_review")) or not entree_ocr.get("is_valid_format", True)
        resultat.append(champ)
    return resultat


def construire_champs_formulaire(type_document: str, slots: dict) -> list:
    """
    Construit la liste de champs {nom, valeur, source, confiance,
    verifie_par_consultant} d'un formulaire, pré-remplie depuis les slots du
    dialogue là où la correspondance est fiable (cf. avertissement du module).
    `confiance` reste toujours None en V1 (pas d'OCR) — cf. Flux §2.2, point
    d'implémentation : le composant doit déjà savoir consommer ce champ.
    """
    noms_champs = CHAMPS_FORMULAIRE_PAR_TYPE_DOCUMENT.get(type_document, [])
    champs = []
    for nom in noms_champs:
        slot_correspondant = _MAPPING_CHAMP_VERS_SLOT.get(nom)
        valeur = slots.get(slot_correspondant) if slot_correspondant else None
        champs.append({
            "nom": nom,
            "valeur": valeur,
            "source": "dialogue" if valeur is not None else "manuel",
            "confiance": None,
            "verifie_par_consultant": False,
        })
    return champs


def _valeur_lisible(champ: dict, slots: dict) -> str:
    """Rend la valeur d'un champ prononçable à l'oral, quel que soit son `type_valeur`."""
    valeur = slots.get(champ["nom_champ"])
    if champ["type_valeur"] == "age":
        age = valeur or {}
        if age.get("valeur") is None or not age.get("unite"):
            return "non renseigné"
        return f"{age['valeur']} {age['unite']}"
    if champ["type_valeur"] == "booleen":
        return "oui" if valeur else "non"
    return str(valeur) if valeur is not None else "non renseigné"


def construire_recapitulatif(slots: dict, definition_champs: list | None = None) -> str:
    """
    Construit le récapitulatif oral avant relecture (RG7 — nœud non
    contournable, jamais généré par le LLM).

    `definition_champs` (Tâche J.7, optionnel) : lignes `demarche_champs`
    triées par `ordre` (cf. slot_controller.charger_definition_demarche). Si
    fourni, le récapitulatif est construit GÉNÉRIQUEMENT (une phrase par champ,
    dans l'ordre) — fonctionne pour n'importe quelle démarche décrite en base,
    pas seulement l'extrait de naissance.

    Si `None` (comportement HISTORIQUE, conservé pour compatibilité stricte
    avec les appelants existants qui n'ont qu'un `slots` — cf.
    test_relecture_confirmation.py) : gabarit figé en dur (f-string), au
    récit plus naturel, repris de Exemples_Dialogues_Agent_SUNU-MAIRIE.md,
    exemple 2.1 — volontairement PAS remplacé par la version générique pour
    l'extrait de naissance en production (le récit narratif se lit mieux à
    l'oral qu'une liste mécanique "question : valeur", cf. avertissement de
    la Tâche J.7).

    Précondition (les deux formes) : dossier_complet(slots) est vrai (sinon
    certains champs apparaîtraient "non renseigné"/None — l'appelant doit
    vérifier avant).
    """
    if definition_champs is None:
        mariage_txt = "parents mariés" if slots.get("parents_maries") else "parents non mariés"
        return (
            "Je vous relis maintenant tout ce que j'ai noté pour vérifier que c'est correct : "
            f"« {slots.get('nom_enfant')}, né(e) le {slots.get('date_naissance_enfant')} "
            f"à {slots.get('commune_naissance')}, enfant de {slots.get('nom_declarant')} "
            f"et de {slots.get('nom_mere')}, née le {slots.get('date_naissance_mere')}, {mariage_txt}. » "
            "Est-ce que tout est exact ?"
        )

    parties = []
    for champ in sorted(definition_champs, key=lambda c: c["ordre"]):
        libelle = champ["question"].rstrip("?").strip()
        parties.append(f"{libelle} : {_valeur_lisible(champ, slots)}")
    corps = ". ".join(parties)
    return (
        "Je vous relis maintenant tout ce que j'ai noté pour vérifier que c'est correct : "
        f"{corps}. Est-ce que tout est exact ?"
    )


# ============================================================================
# Cas particuliers — Sprint E, Tâche E.3.
# Taxonomie reprise telle quelle de Flux_Consultant_Generation_Document_
# SUNU-MAIRIE.md §2.5 (bloc JSON "type_incident").
# ============================================================================
TYPES_INCIDENT_CAS_PARTICULIER = [
    "incoherence_non_resolue", "champ_manquant", "document_inattendu", "autre",
    # Ajouté Sprint J, Tâche J.6 (au-delà de la taxonomie d'origine du Flux) :
    # un citoyen qui déclare explicitement ne pas avoir un document demandé
    # (ou qui ne répond jamais après plusieurs rappels, cf. PLAN_REFACTOR_
    # DIALOGUE_CHAMPS.md §5) n'est ni une incohérence, ni un champ textuel
    # manquant, ni un document inattendu — un type dédié évite au consultant
    # de confondre ce cas avec les 3 précédents dans la liste de supervision.
    "document_indisponible",
]
