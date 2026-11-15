"""
document_generator.py — Sprint D, Tâche D.2.

generer_document(dossier_id) -> bytes : pipeline complet décrit en §5.5 du
roadmap :
  1. charge le dossier + ses DocumentFormulaire (y compris le formulaire
     "extrait_naissance", créé à la volée — cf. Tâche D.2, dossiers_repo.py)
  2. résout chaque source="..." du template XML (extrait_naissance_v1.xml,
     Tâche D.1) contre ces données
  3. échoue EXPLICITEMENT (pas de PDF silencieux) si un champ obligatoire="true"
     n'a pas de valeur résolue, OU si les valeurs résolues échouent la
     validation XSD — dans les deux cas, crée un CasParticulier (traitement
     complet du cas = Sprint E, pas construit ici, juste le déclenchement)
  4. injecte dans le template HTML (extrait_naissance_v1.html, Jinja2)
  5. convertit en PDF via weasyprint — bandeau "brouillon officiel" (§5.4)
     déjà intégré au template HTML, rien à faire de spécial ici pour ça.

Limite d'environnement connue (pas une limite du code) : weasyprint nécessite
des bibliothèques système (Pango/GObject/Cairo) absentes par défaut sous
Windows — l'import de weasyprint est donc fait à l'intérieur de la fonction
qui en a besoin (_convertir_pdf), pas au niveau du module, pour que le reste
du pipeline (résolution, validation XSD, rendu HTML) reste testable sans ces
bibliothèques installées. Sur le VPS (Debian/Ubuntu), un simple
`apt install libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf2.0-0`
suffit — problème d'environnement de dev Windows, pas de portabilité VPS.
"""
import base64
import os
from datetime import datetime, timezone

import jinja2
from lxml import etree

from admin_repo import telecharger_tampon
from dossiers_repo import (
    get_dossier, get_commune, list_document_formulaires,
    get_or_create_formulaire_acte, create_cas_particulier,
)

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

XSI_NAMESPACE = "http://www.w3.org/2001/XMLSchema-instance"


class Modele:
    """
    Un modèle de document, pour UNE démarche (étape 5.5).

    Avant, les trois fichiers de l'extrait de naissance étaient des constantes
    de module, et la structure de l'instance XML était recopiée à la main en
    Python (`_ORDRE_ENTETE`, `_ORDRE_ACTE`, ...). Ajouter le certificat de
    mariage dans ce moule aurait voulu dire une deuxième copie de la même
    structure, à tenir synchronisée avec le XSD et le template — deux endroits
    où se tromper en silence.

    L'ordre et le caractère obligatoire des éléments sont donc lus DANS le
    template XML, qui est déjà calqué sur le XSD. Un modèle ne déclare plus que
    ses fichiers, et les deux particularités qu'un fichier XML ne peut pas
    porter : les attributs de l'élément racine, et les valeurs calculées pour
    l'affichage HTML (une énumération écrite en toutes lettres, par exemple).
    """

    def __init__(self, type_demarche, fichier_xml, fichier_xsd, fichier_html,
                 attributs_racine=None, contexte_html=None):
        self.type_demarche = type_demarche
        self.chemin_xml = os.path.join(TEMPLATES_DIR, fichier_xml)
        self.chemin_xsd = os.path.join(TEMPLATES_DIR, fichier_xsd)
        self.fichier_html = fichier_html
        self.attributs_racine = attributs_racine or (lambda _jugement_requis: {})
        self.contexte_html = contexte_html or (lambda _valeurs: {})

    @property
    def nom(self) -> str:
        """
        Ce qui est archivé dans `documents_generes.template_utilise`.

        Dérivé du fichier HTML plutôt que redéclaré : la colonne contient déjà
        « extrait_naissance_v1 » pour les documents produits jusqu'ici, et un
        nom écrit à part finirait par diverger du gabarit réellement employé —
        exactement le genre d'écart qu'on ne remarque que des mois plus tard,
        en relisant un document qu'on ne sait plus reproduire.

        Le suffixe de version (`_v1`) fait partie du nom : c'est lui qui dira,
        le jour où un modèle change, avec quelle version un acte donné a été
        établi.
        """
        return os.path.splitext(self.fichier_html)[0]

    def arbre(self):
        with open(self.chemin_xml, "rb") as f:
            return etree.parse(f).getroot()


def _attributs_extrait_naissance(jugement_requis: bool) -> dict:
    # Le XSD distingue l'acte ordinaire de l'acte supplétif par un attribut de
    # l'élément racine, pas par un élément — donc pas exprimable dans le
    # template.
    return {"typeActe": "supplétif" if jugement_requis else "ordinaire"}


def _contexte_html_extrait_naissance(valeurs: dict) -> dict:
    return {"sexe_lettres": SEXE_EN_LETTRES.get(valeurs.get("sexe"), valeurs.get("sexe") or "")}


def _contexte_html_acte_deces(valeurs: dict) -> dict:
    """
    Les accords de l'acte de décès.

    « est décédé » / « est décédée », « fils de » / « fille de » : sur un acte
    d'état civil, un accord au masculin par défaut pour une femme n'est pas une
    coquille, c'est une erreur sur la personne. Le sexe est collecté par le
    dialogue ; il sert ici, et n'est pas imprimé tel quel — le modèle réel ne
    l'imprime pas non plus.
    """
    feminin = valeurs.get("defuntSexe") == "feminin"
    return {
        "accord_decede": "décédée" if feminin else "décédé",
        "accord_e": "e" if feminin else "",
        "lien_filiation": "fille" if feminin else "fils",
        "situation_lettres": _situation_lettres(valeurs.get("defuntSituationMatrimoniale"), feminin),
    }


def _situation_lettres(code, feminin: bool) -> str:
    """« marié » / « mariée », « veuf » / « veuve » — un couple par code."""
    accords = SITUATIONS_EN_LETTRES.get(code)
    if not accords:
        # Valeur hors du dialogue : rendue telle quelle, la validation XSD la
        # refusera plutôt que de laisser passer une mention inventée.
        return code or ""
    return accords[1] if feminin else accords[0]


def _contexte_html_certificat_mariage(valeurs: dict) -> dict:
    # Le certificat imprime « Monogamie », pas « monogamie » ; le dossier, lui,
    # stocke le code du Code de la famille. La traduction est ici, jamais dans
    # le XSD (qui doit rester le contrat de données).
    return {
        "option_lettres": OPTIONS_EN_LETTRES.get(valeurs.get("optionMatrimoniale"),
                                                 valeurs.get("optionMatrimoniale") or ""),
        "regime_lettres": REGIMES_EN_LETTRES.get(valeurs.get("regimeMatrimonial"),
                                                 valeurs.get("regimeMatrimonial") or ""),
    }


#: Les démarches dont le document de sortie a un modèle. Tant qu'une démarche
#: n'y figure pas, on REFUSE de générer : sans son modèle, le moteur
#: fabriquerait l'acte d'une autre démarche avec ses données — un extrait de
#: naissance à partir d'un dossier de mariage (plan maître, étape 5.5).
MODELES = {
    "extrait_naissance": Modele(
        "extrait_naissance",
        "extrait_naissance_v1.xml", "extrait_naissance.xsd", "extrait_naissance_v1.html",
        attributs_racine=_attributs_extrait_naissance,
        contexte_html=_contexte_html_extrait_naissance,
    ),
    "constatation_mariage": Modele(
        "constatation_mariage",
        "certificat_mariage_v1.xml", "certificat_mariage.xsd", "certificat_mariage_v1.html",
        contexte_html=_contexte_html_certificat_mariage,
    ),
    # ⚠️ Modèle construit d'après un acte FRANÇAIS donné en exemple : toutes
    # ses mentions sont des hypothèses de forme, à confirmer par un officier
    # d'état civil sénégalais (avertissement en tête de acte_deces.xsd).
    "declaration_deces": Modele(
        "declaration_deces",
        "acte_deces_v1.xml", "acte_deces.xsd", "acte_deces_v1.html",
        contexte_html=_contexte_html_acte_deces,
    ),
}

DEMARCHES_AVEC_MODELE = tuple(MODELES)

DEMARCHE_PAR_DEFAUT = "extrait_naissance"


def modele_pour(type_demarche):
    """
    Le modèle d'une démarche, ou None si elle n'en a pas encore (déclaration de
    décès aujourd'hui). None, et pas une exception : les appelants qui ne font
    que lire des valeurs (narration audio, analyse de l'assistant) doivent
    pouvoir passer leur chemin sans casser ; seul `generer_document` refuse.
    """
    return MODELES.get(type_demarche or DEMARCHE_PAR_DEFAUT)


class ErreurGenerationDocument(Exception):
    """
    Levée quand la génération échoue explicitement (champs obligatoires
    manquants ou validation XSD échouée) — jamais de PDF silencieusement
    incomplet. Un CasParticulier a déjà été créé en base au moment où cette
    exception est levée (cf. generer_document).
    """
    def __init__(self, message: str, erreurs: list):
        super().__init__(f"{message} : {', '.join(erreurs)}")
        self.erreurs = erreurs


def _resoudre_valeur(source: str, dossier: dict, commune: dict, champs_formulaire: dict):
    # "a|b" : la première source qui donne une valeur l'emporte.
    if "|" in source:
        for alternative in source.split("|"):
            valeur = _resoudre_valeur(alternative.strip(), dossier, commune, champs_formulaire)
            if valeur not in (None, ""):
                return valeur
        return None
    if source.startswith("dossier."):
        return (dossier.get("slots") or {}).get(source[len("dossier."):])
    if source.startswith("commune."):
        return (commune or {}).get(source[len("commune."):])
    if source.startswith("formulaire."):
        return champs_formulaire.get(source[len("formulaire."):])
    if source.startswith("lettres."):
        # « lettres.dossier.date_deces » : la même source, écrite en toutes
        # lettres. Dans les templates, elle vient TOUJOURS après la saisie
        # manuelle du consultant (« formulaire.x|lettres.dossier.y ») : s'il a
        # recopié la mention du registre papier, c'est la sienne qui sort.
        brut = _resoudre_valeur(source[len("lettres."):], dossier, commune, champs_formulaire)
        return date_en_lettres(brut)
    if source.startswith("systeme."):
        champ = source[len("systeme."):]
        if champ == "date_generation":
            return datetime.now(timezone.utc).date().isoformat()
        return None
    raise ValueError(f"Préfixe de source inconnu dans le template : {source!r}")


_SEXE = {
    "m": "M", "masculin": "M", "garcon": "M", "garçon": "M", "homme": "M",
    "f": "F", "feminin": "F", "féminin": "F", "fille": "F", "femme": "F",
}

SEXE_EN_LETTRES = {"M": "MASCULIN", "F": "FÉMININ"}

# Codes du Code de la famille -> ce qui est imprimé sur le certificat de
# mariage. Définis dans `services.libelles_document` et importés ici : la même
# traduction sert au PDF et à la lecture à voix haute du document au citoyen.
# Les tenir à deux endroits, c'est les voir diverger.
# Une valeur inconnue est rendue telle quelle : la validation XSD la refusera,
# plutôt que de laisser passer un document muet sur l'option souscrite — c'est
# une mention qui engage les époux.
from services.libelles_document import (  # noqa: E402
    OPTIONS_EN_LETTRES, REGIMES_EN_LETTRES, SITUATIONS_EN_LETTRES,
)
from services.dates_en_lettres import date_en_lettres  # noqa: E402


def normaliser_sexe(valeur):
    """
    M ou F, quelle que soit la façon dont le consultant ou le dialogue l'a
    écrit. Une valeur non reconnue est rendue telle quelle : la validation
    XSD la refusera, plutôt que de deviner.
    """
    if valeur is None:
        return None
    return _SEXE.get(str(valeur).strip().lower(), valeur)


def _cle(element) -> str:
    """
    Le nom sous lequel une feuille est rangée dans le dictionnaire de valeurs.

    C'est le nom de l'élément, sauf si le template donne un `cle` explicite.
    Le certificat de mariage en a besoin : le mari et l'épouse portent les
    MÊMES noms d'éléments (`prenoms`, `nomFamille`, ...), comme l'exige son
    XSD. Sans clé distincte, l'épouse écraserait le mari dans le dictionnaire
    — et le certificat sortirait avec deux fois la même personne, sans erreur.
    """
    return element.get("cle") or element.tag


def resoudre_template(dossier: dict, commune: dict, champs_formulaire: dict, jugement_requis: bool):
    """
    Parcourt le template XML de la démarche du dossier, résout chaque
    source="..." et collecte les champs obligatoires non résolus.

    Le modèle est choisi d'après `dossier["type_demarche"]` : c'est ce qui
    garantit qu'un dossier de mariage ne peut pas être résolu contre le
    template d'un extrait de naissance. Un bloc marqué `conditionnel` (le
    jugement supplétif) n'est ni résolu ni exigé hors de son cas.
    """
    modele = modele_pour(dossier.get("type_demarche"))
    if modele is None:
        return {}, []
    template_root = modele.arbre()

    blocs_conditionnels = {e.tag for e in template_root if e.get("conditionnel") is not None}

    valeurs = {}
    erreurs = []
    for element in template_root.iter():
        source = element.get("source")
        if source is None:
            continue
        dans_conditionnel = any(a.tag in blocs_conditionnels for a in element.iterancestors())
        if dans_conditionnel and not jugement_requis:
            continue

        valeur = _resoudre_valeur(source, dossier, commune, champs_formulaire)
        # M/F : la forme attendue par le XSD de l'extrait de naissance, dont le
        # champ s'appelle simplement « sexe ». On se fie à la CLÉ, pas au nom
        # de l'élément : l'acte de décès a lui aussi un élément `sexe`, mais il
        # attend les valeurs du dialogue (masculin/feminin) pour accorder
        # « décédé » / « décédée ». Normaliser les deux de la même façon
        # rendrait l'acte de décès invalide, en silence.
        if _cle(element) == "sexe":
            valeur = normaliser_sexe(valeur)
        valeurs[_cle(element)] = valeur

        if element.get("obligatoire") == "true" and (valeur is None or valeur == ""):
            erreurs.append(f"{_cle(element)} (source={source})")

    return valeurs, erreurs


def construire_resume_document_genere(valeurs: dict,
                                      type_demarche: str = DEMARCHE_PAR_DEFAUT) -> str:
    """
    Phrase FR courte résumant le contenu du document généré, dite à voix haute
    au citoyen. Chaque démarche a la sienne : lire un certificat de mariage
    avec la phrase d'un extrait de naissance donnerait « Ceci est un extrait de
    naissance pour l'enfant » sur un dossier de mariage — du charabia annoncé
    avec aplomb, ce qui est pire qu'un silence.
    """
    if type_demarche == "constatation_mariage":
        return _resume_certificat_mariage(valeurs)
    if type_demarche == "declaration_deces":
        return _resume_acte_deces(valeurs)
    return _resume_extrait_naissance(valeurs)


def _resume_acte_deces(valeurs: dict) -> str:
    """
    Dit à voix haute à la famille. Sobre, et sans aucune cause : l'acte n'en
    porte pas, et cette application n'en collecte pas.
    """
    nom = " ".join(x for x in (valeurs.get("defuntPrenoms"), valeurs.get("defuntNomFamille")) if x)
    feminin = valeurs.get("defuntSexe") == "feminin"

    phrase = f"Ceci est l'acte de décès de {nom}" if nom else "Ceci est un acte de décès"
    if valeurs.get("dateDecesLettres"):
        phrase += f", {'décédée' if feminin else 'décédé'} le {valeurs['dateDecesLettres']}"
    if valeurs.get("lieuDeces"):
        phrase += f" à {valeurs['lieuDeces']}"
    return phrase + "."


def _resume_certificat_mariage(valeurs: dict) -> str:
    mari = " ".join(x for x in (valeurs.get("epouxPrenoms"), valeurs.get("epouxNomFamille")) if x)
    epouse = " ".join(x for x in (valeurs.get("epousePrenoms"), valeurs.get("epouseNomFamille")) if x)

    if mari and epouse:
        phrase = f"Ceci est un certificat de mariage entre {mari} et {epouse}"
    else:
        # Un seul nom résolu : on le dit, sans inventer l'autre.
        phrase = f"Ceci est un certificat de mariage pour {mari or epouse}" if (mari or epouse) \
            else "Ceci est un certificat de mariage"

    if valeurs.get("dateCelebrationLettres"):
        phrase += f", marié le {valeurs['dateCelebrationLettres']}"
    if valeurs.get("lieuCelebration"):
        phrase += f" à {valeurs['lieuCelebration']}"

    option = OPTIONS_EN_LETTRES.get(valeurs.get("optionMatrimoniale"))
    if option:
        # L'option souscrite engage les époux : elle est dite, pas laissée au
        # hasard d'une relecture du PDF.
        phrase += f". Option souscrite : {option.lower()}"

    return phrase + "."


def _resume_extrait_naissance(valeurs: dict) -> str:
    """
    Phrase FR courte résumant le CONTENU d'un extrait de naissance déjà généré
    (Tâche 7.5 mobile — narration audio, `POST /mes-dossiers/{id}/document/audio`) —
    à partir des mêmes `valeurs` que `resoudre_template()` (aucune extraction
    depuis le PDF, elles existent déjà en dict structuré à ce stade). Le PDF
    est un formulaire (champs, cases, tableaux) : le lire mot pour mot serait
    imbuvable à l'oral, d'où cette phrase de synthèse.

    `dateNaissanceLettres`/`lieuNaissance` : déjà du texte prêt à l'oral (pas
    la date ISO `dateNaissance`) — même convention que le reste du document.
    Le père n'a pas de nom de famille propre dans le XSD (`prenomPere` seul,
    optionnel) : omis proprement si absent, jamais une phrase bancale.
    """
    prenom = valeurs.get("prenomEnfant") or "l'enfant"
    nom_famille = valeurs.get("nomFamilleEnfant") or ""
    nom_complet_enfant = f"{prenom} {nom_famille}".strip()

    sexe = valeurs.get("sexe")
    ne_ou_nee = "née" if sexe == "F" else "né" if sexe == "M" else "né(e)"

    phrase = f"Ceci est un extrait de naissance pour {nom_complet_enfant}, {ne_ou_nee}"
    if valeurs.get("dateNaissanceLettres"):
        phrase += f" le {valeurs['dateNaissanceLettres']}"
    if valeurs.get("lieuNaissance"):
        phrase += f" à {valeurs['lieuNaissance']}"

    prenom_mere = valeurs.get("prenomMere")
    nom_mere = valeurs.get("nomFamilleMere")
    mere = f"{prenom_mere} {nom_mere}".strip() if (prenom_mere or nom_mere) else None
    prenom_pere = valeurs.get("prenomPere")

    lien = "fille" if sexe == "F" else "fils" if sexe == "M" else "enfant"
    if prenom_pere and mere:
        phrase += f", {lien} de {prenom_pere} et {mere}"
    elif prenom_pere:
        phrase += f", {lien} de {prenom_pere}"
    elif mere:
        phrase += f", {lien} de {mere}"

    return phrase + "."


def champs_obligatoires_pour(cas_legal: str, type_demarche: str = DEMARCHE_PAR_DEFAUT) -> set:
    """
    Ensemble des noms de champs marqués obligatoire="true" dans le template
    XML pour un cas_legal donné (respecte le bloc conditionnel
    jugementSupplement, cf. resoudre_template). Réutilisé par l'endpoint
    d'analyse de l'assistant consultant (Sprint E, Tâche E.2) pour que la
    complétude évaluée par le LLM s'appuie sur les VRAIES règles du XSD, pas
    une supposition — trouvé nécessaire en testant E.2 (l'assistant listait
    des champs optionnels comme "manquants" au même niveau que les vrais
    champs obligatoires, faute de le savoir).
    """
    modele = modele_pour(type_demarche)
    if modele is None:
        return set()
    template_root = modele.arbre()
    blocs_conditionnels = {e.tag for e in template_root if e.get("conditionnel") is not None}
    jugement_requis = cas_legal == "jugement_requis"
    obligatoires = set()
    for element in template_root.iter():
        source = element.get("source")
        if source is None:
            continue
        dans_conditionnel = any(a.tag in blocs_conditionnels for a in element.iterancestors())
        if dans_conditionnel and not jugement_requis:
            continue
        if element.get("obligatoire") == "true":
            obligatoires.add(_cle(element))
    return obligatoires


def _sous_element(parent, espace_noms: str, tag: str, valeur):
    el = etree.SubElement(parent, f"{{{espace_noms}}}{tag}")
    el.text = str(valeur) if valeur is not None else None
    return el


def _retenir(element, valeurs: dict) -> bool:
    """
    Une feuille part dans l'instance si elle a une valeur. Un champ non
    renseigné est ABSENT, jamais un élément vide : le XSD refuse une chaîne
    vide là où il attend du texte, et un élément vide dirait « renseigné, mais
    rien » — ce n'est pas la même chose.

    Cette fonction testait aussi `obligatoire="true"`, pour émettre quand même
    un élément obligatoire resté vide. Ce cas ne peut pas arriver : un champ
    obligatoire sans valeur arrête la génération bien avant, dans
    `resoudre_template`. La condition était donc invérifiable — une campagne de
    mutation l'a montrée en la supprimant sans qu'aucun test ne bronche.
    """
    return bool(valeurs.get(_cle(element)))


def _construire_instance_xsd(valeurs: dict, jugement_requis: bool, modele: Modele = None):
    """
    Reconstruit une instance XML conforme au XSD du modèle à partir des valeurs
    résolues — c'est CETTE instance qui est validée (§5.5), pas le template
    lui-même (qui ne peut pas l'être : ses feuilles portent des sources, pas
    des valeurs).

    La structure (ordre des blocs, ordre des éléments, caractère obligatoire)
    est lue dans le template XML, qui est déjà calqué sur le XSD. Elle n'est
    donc écrite qu'une fois : recopier cet ordre en Python, comme avant,
    revenait à tenir un troisième fichier synchronisé à la main.
    """
    modele = modele or MODELES[DEMARCHE_PAR_DEFAUT]
    template_root = modele.arbre()
    espace_noms = template_root.get("espaceNoms")
    racine = template_root.get("racine")

    root = etree.Element(f"{{{espace_noms}}}{racine}",
                         nsmap={None: espace_noms, "xsi": XSI_NAMESPACE})
    root.set(f"{{{XSI_NAMESPACE}}}schemaLocation",
             f"{espace_noms} {os.path.basename(modele.chemin_xsd)}")
    for nom, valeur in modele.attributs_racine(jugement_requis).items():
        root.set(nom, valeur)

    for element in template_root:
        if len(element) == 0:
            # Feuille directement sous la racine (le numéro d'acte).
            if _retenir(element, valeurs):
                _sous_element(root, espace_noms, element.tag, valeurs.get(_cle(element)))
            continue

        if element.get("conditionnel") is not None and not jugement_requis:
            continue

        bloc = etree.SubElement(root, f"{{{espace_noms}}}{element.tag}")
        for feuille in element:
            if _retenir(feuille, valeurs):
                _sous_element(bloc, espace_noms, feuille.tag, valeurs.get(_cle(feuille)))

    return root


def _valider_xsd(instance_root, modele: Modele = None) -> list:
    modele = modele or MODELES[DEMARCHE_PAR_DEFAUT]
    with open(modele.chemin_xsd, "rb") as f:
        schema = etree.XMLSchema(etree.parse(f))
    valide = schema.validate(etree.ElementTree(instance_root))
    return [] if valide else [str(e) for e in schema.error_log]


#: Types d'image acceptés pour un tampon, par extension de fichier. Une
#: extension inconnue n'est pas devinée : le tampon est simplement absent.
_TYPES_TAMPON = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                 "webp": "image/webp"}


def tampon_de_la_commune(commune: dict) -> str | None:
    """
    Le tampon numérique de la commune, prêt à être posé sur le document.

    Rendu en `data:` URI plutôt qu'en lien : le PDF doit rester complet une
    fois enregistré ou imprimé. Une URL signée expire au bout d'une heure, et
    un document qui perd son tampon le lendemain a l'air trafiqué.

    `communes.tampon_numerique_url` n'est écrit QUE par
    `admin_repo.confirmer_tampon`, qui journalise d'abord la confirmation de
    l'administrateur dans `tampon_confirmations`. Un chemin présent ici
    signifie donc : un administrateur a confirmé son autorisation, et on sait
    qui et quand. Aucun tampon ne peut arriver sur un document autrement.
    """
    chemin = (commune or {}).get("tampon_numerique_url")
    if not chemin:
        return None
    type_mime = _TYPES_TAMPON.get(chemin.rsplit(".", 1)[-1].lower())
    if not type_mime:
        return None
    contenu = telecharger_tampon(chemin)
    if not contenu:
        # Le document sort SANS tampon plutôt que pas du tout : un consultant
        # qui attend un acte pour un citoyen au guichet ne doit pas être
        # bloqué par un stockage momentanément injoignable.
        return None
    return f"data:{type_mime};base64,{base64.b64encode(contenu).decode('ascii')}"


def _rendre_html(valeurs: dict, jugement_requis: bool, numero_suivi: str,
                 modele: Modele = None, tampon: str = None) -> str:
    # autoescape=True : les valeurs injectées viennent de saisies humaines
    # (dialogue vocal transcrit, saisie consultant) — jamais faire confiance
    # à du texte utilisateur non échappé dans un document HTML->PDF.
    modele = modele or MODELES[DEMARCHE_PAR_DEFAUT]
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    template = env.get_template(modele.fichier_html)
    contexte = dict(valeurs)
    contexte["jugement_requis"] = jugement_requis
    contexte.update(modele.contexte_html(valeurs))
    contexte["numero_suivi"] = numero_suivi or "—"
    contexte["tampon"] = tampon
    return template.render(**contexte)


def _convertir_pdf(html: str) -> bytes:
    # Import différé : voir avertissement en tête de fichier (dépendances
    # système absentes par défaut sous Windows, présentes sur le VPS cible).
    from weasyprint import HTML
    return HTML(string=html, base_url=TEMPLATES_DIR).write_pdf()


class DemarcheSansModele(ValueError):
    """La démarche du dossier n'a pas de modèle de document."""


def generer_document(dossier_id: str, rapport: dict | None = None) -> bytes:
    """
    Le PDF de l'acte. `rapport`, s'il est fourni, est REMPLI en place avec ce
    qui n'est pas visible dans les octets renvoyés — à commencer par le sort du
    tampon.

    Pourquoi un paramètre de sortie plutôt qu'un retour enrichi : la fonction
    renvoie des octets depuis le début et une bonne vingtaine de tests
    s'appuient dessus (`.startswith(b"%PDF-")`). Un tuple les casserait tous
    pour une information que seul l'endpoint consulte.

    Le rapport distingue deux situations que le document ne permet pas de
    séparer à l'œil :
      - aucun tampon n'est enregistré pour la commune ;
      - un tampon est enregistré mais n'a pas pu être récupéré (stockage
        momentanément injoignable). L'acte sort alors sans sceau alors que la
        commune en a un — c'est le cas qu'il faut absolument signaler.
    """
    dossier = get_dossier(dossier_id)
    if not dossier:
        raise ValueError(f"Dossier introuvable : {dossier_id}")

    type_demarche = dossier.get("type_demarche") or DEMARCHE_PAR_DEFAUT
    modele = modele_pour(type_demarche)
    if modele is None:
        raise DemarcheSansModele(
            f"Aucun modèle de document pour la démarche « {type_demarche} ». "
            f"Le dossier reste consultable ; le document devra être établi hors de "
            f"l'application tant que son modèle n'est pas fourni."
        )

    # Renseigné AVANT la validation : l'appelant archive le nom du gabarit qui
    # a réellement servi. `main.py` écrivait « extrait_naissance_v1 » en dur,
    # si bien qu'un acte de décès était rangé sous le nom d'un extrait de
    # naissance — invisible tant qu'une seule démarche avait un modèle.
    if rapport is not None:
        rapport["template"] = modele.nom
        rapport["type_demarche"] = type_demarche

    commune = get_commune(dossier.get("commune_id"))

    formulaires = list_document_formulaires(dossier_id)
    formulaire_acte = get_or_create_formulaire_acte(dossier_id)
    if formulaire_acte and not any(f["id"] == formulaire_acte["id"] for f in formulaires):
        formulaires.append(formulaire_acte)

    champs_formulaire = {}
    for formulaire in formulaires:
        for champ in (formulaire.get("champs") or []):
            if champ.get("valeur") is not None:
                champs_formulaire[champ["nom"]] = champ["valeur"]

    jugement_requis = dossier.get("cas_legal") == "jugement_requis"

    valeurs, erreurs = resoudre_template(dossier, commune, champs_formulaire, jugement_requis)
    if erreurs:
        # type_incident="champ_manquant" (taxonomie Flux §2.5, cf. Tâche E.3 —
        # corrigé ici : utilisait une valeur inventée avant la lecture de §2.5).
        create_cas_particulier(
            dossier_id, "champ_manquant",
            "Champs obligatoires non résolus pour la génération : " + ", ".join(erreurs),
            options_proposees=[
                "Compléter le(s) champ(s) manquant(s) dans le formulaire avant de relancer la génération",
                "Poursuivre en laissant le(s) champ(s) vide(s), à compléter manuellement dans le document",
                "Escalader vers l'administrateur de la commune",
            ],
        )
        raise ErreurGenerationDocument("Champs obligatoires manquants", erreurs)

    instance_xsd = _construire_instance_xsd(valeurs, jugement_requis, modele)
    erreurs_xsd = _valider_xsd(instance_xsd, modele)
    if erreurs_xsd:
        # type_incident="incoherence_non_resolue" : la valeur EXISTE mais ne
        # respecte pas le format attendu (distinct de "champ_manquant").
        create_cas_particulier(
            dossier_id, "incoherence_non_resolue",
            "Validation XSD échouée : " + " | ".join(erreurs_xsd),
            options_proposees=[
                "Corriger la valeur du champ concerné dans le formulaire avant de relancer la génération",
                "Escalader vers l'administrateur de la commune",
                "Vérifier le format attendu de ce champ auprès du service d'état civil "
                "(cf. hypothèse non confirmée dans extrait_naissance.xsd)",
            ],
        )
        raise ErreurGenerationDocument("Validation XSD échouée", erreurs_xsd)

    # Le tampon est cherché APRÈS la validation : un document qui ne serait
    # pas valide ne doit pas aller chercher le sceau de la commune.
    tampon = tampon_de_la_commune(commune)
    if rapport is not None:
        rapport["commune"] = (commune or {}).get("nom")
        rapport["tampon_enregistre"] = bool((commune or {}).get("tampon_numerique_url"))
        rapport["tampon_appose"] = tampon is not None

    html = _rendre_html(valeurs, jugement_requis, dossier.get("numero_suivi"), modele, tampon=tampon)
    return _convertir_pdf(html)
