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
import os
from datetime import datetime, timezone

import jinja2
from lxml import etree

from dossiers_repo import (
    get_dossier, get_commune, list_document_formulaires,
    get_or_create_formulaire_acte, create_cas_particulier,
)

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
XML_TEMPLATE_PATH = os.path.join(TEMPLATES_DIR, "extrait_naissance_v1.xml")
HTML_TEMPLATE_NAME = "extrait_naissance_v1.html"
XSD_PATH = os.path.join(TEMPLATES_DIR, "extrait_naissance.xsd")

#: Les démarches dont le document de sortie a un modèle. Tant qu'une démarche
#: n'y figure pas, on REFUSE de générer : sans son modèle, le moteur
#: fabriquerait l'acte d'une autre démarche avec ses données — un extrait de
#: naissance à partir d'un dossier de mariage (plan maître, étape 5.5).
DEMARCHES_AVEC_MODELE = ("extrait_naissance",)

XSD_NAMESPACE = "http://sunu-mairie.sn/schemas/extrait-naissance"
XSI_NAMESPACE = "http://www.w3.org/2001/XMLSchema-instance"

# Ordre EXACT des éléments par bloc, tel que déclaré dans extrait_naissance.xsd
# (xs:sequence — l'ordre compte pour la validation XSD). Champs optionnels du
# XSD (minOccurs="0") marqués ici ; absents de la sortie si non résolus,
# jamais un élément vide.
_ORDRE_ENTETE = [("region", True), ("departement", True), ("arrondissement", False),
                  ("collectiviteLocale", True), ("typeCentre", False), ("nomCentreEtatCivil", True)]
_ORDRE_REGISTRE = [("anneeRegistreLettres", True), ("anneeRegistreChiffres", True),
                    ("numeroRegistreLettres", True), ("numeroRegistreChiffres", True)]
_ORDRE_ACTE = [("dateNaissanceLettres", True), ("dateNaissance", True), ("heureNaissance", False),
                ("lieuNaissance", True), ("sexe", True), ("prenomEnfant", True), ("nomFamilleEnfant", True),
                ("prenomPere", False), ("prenomMere", True), ("nomFamilleMere", True),
                ("paysNaissanceEtranger", False)]
_ORDRE_JUGEMENT = [("tribunalOuJuge", True), ("dateJugementLettres", True), ("numeroJugementLettres", True),
                     ("numeroJugementChiffres", True), ("dateInscriptionRegistre", True), ("anneeJugement", True)]
_ORDRE_DELIVRANCE = [("centreDelivrance", True), ("lieuDelivrance", True), ("dateDelivrance", True),
                       ("officierEtatCivil", True), ("notesMentionsMarginales", False)]


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


def normaliser_sexe(valeur):
    """
    M ou F, quelle que soit la façon dont le consultant ou le dialogue l'a
    écrit. Une valeur non reconnue est rendue telle quelle : la validation
    XSD la refusera, plutôt que de deviner.
    """
    if valeur is None:
        return None
    return _SEXE.get(str(valeur).strip().lower(), valeur)


def resoudre_template(dossier: dict, commune: dict, champs_formulaire: dict, jugement_requis: bool):
    """
    Parcourt extrait_naissance_v1.xml, résout chaque source="..." et collecte
    les champs obligatoires non résolus. Le bloc jugementSupplement n'est ni
    résolu ni exigé si le dossier n'est pas en cas_legal="jugement_requis".
    """
    with open(XML_TEMPLATE_PATH, "rb") as f:
        template_root = etree.parse(f).getroot()

    valeurs = {}
    erreurs = []
    for element in template_root.iter():
        source = element.get("source")
        if source is None:
            continue
        dans_jugement = any(a.tag == "jugementSupplement" for a in element.iterancestors())
        if dans_jugement and not jugement_requis:
            continue

        valeur = _resoudre_valeur(source, dossier, commune, champs_formulaire)
        if element.tag == "sexe":
            valeur = normaliser_sexe(valeur)
        valeurs[element.tag] = valeur

        if element.get("obligatoire") == "true" and (valeur is None or valeur == ""):
            erreurs.append(f"{element.tag} (source={source})")

    return valeurs, erreurs


def construire_resume_document_genere(valeurs: dict) -> str:
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


def champs_obligatoires_pour(cas_legal: str) -> set:
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
    with open(XML_TEMPLATE_PATH, "rb") as f:
        template_root = etree.parse(f).getroot()
    jugement_requis = cas_legal == "jugement_requis"
    obligatoires = set()
    for element in template_root.iter():
        source = element.get("source")
        if source is None:
            continue
        dans_jugement = any(a.tag == "jugementSupplement" for a in element.iterancestors())
        if dans_jugement and not jugement_requis:
            continue
        if element.get("obligatoire") == "true":
            obligatoires.add(element.tag)
    return obligatoires


def _sous_element(parent, tag: str, valeur):
    el = etree.SubElement(parent, f"{{{XSD_NAMESPACE}}}{tag}")
    el.text = str(valeur) if valeur is not None else None
    return el


def _construire_instance_xsd(valeurs: dict, jugement_requis: bool):
    """
    Reconstruit une instance XML conforme à extrait_naissance.xsd à partir des
    valeurs résolues — c'est CETTE instance qui est validée (§5.5 étape 1),
    pas le template lui-même (qui ne peut pas l'être, cf. Tâche D.1).
    """
    root = etree.Element(f"{{{XSD_NAMESPACE}}}extraitNaissance", nsmap={None: XSD_NAMESPACE, "xsi": XSI_NAMESPACE})
    root.set(f"{{{XSI_NAMESPACE}}}schemaLocation", f"{XSD_NAMESPACE} extrait_naissance.xsd")
    root.set("typeActe", "supplétif" if jugement_requis else "ordinaire")

    _sous_element(root, "numeroActe", valeurs.get("numeroActe"))

    entete = etree.SubElement(root, f"{{{XSD_NAMESPACE}}}enTeteAdministratif")
    for nom, obligatoire in _ORDRE_ENTETE:
        if obligatoire or valeurs.get(nom):
            _sous_element(entete, nom, valeurs.get(nom))

    registre = etree.SubElement(root, f"{{{XSD_NAMESPACE}}}informationsRegistre")
    for nom, _ in _ORDRE_REGISTRE:
        _sous_element(registre, nom, valeurs.get(nom))

    acte = etree.SubElement(root, f"{{{XSD_NAMESPACE}}}acteNaissance")
    for nom, obligatoire in _ORDRE_ACTE:
        if obligatoire or valeurs.get(nom):
            _sous_element(acte, nom, valeurs.get(nom))

    if jugement_requis:
        jugement = etree.SubElement(root, f"{{{XSD_NAMESPACE}}}jugementSupplement")
        for nom, _ in _ORDRE_JUGEMENT:
            _sous_element(jugement, nom, valeurs.get(nom))

    delivrance = etree.SubElement(root, f"{{{XSD_NAMESPACE}}}delivrance")
    for nom, obligatoire in _ORDRE_DELIVRANCE:
        if obligatoire or valeurs.get(nom):
            _sous_element(delivrance, nom, valeurs.get(nom))

    return root


def _valider_xsd(instance_root) -> list:
    with open(XSD_PATH, "rb") as f:
        schema = etree.XMLSchema(etree.parse(f))
    valide = schema.validate(etree.ElementTree(instance_root))
    return [] if valide else [str(e) for e in schema.error_log]


def _rendre_html(valeurs: dict, jugement_requis: bool, numero_suivi: str) -> str:
    # autoescape=True : les valeurs injectées viennent de saisies humaines
    # (dialogue vocal transcrit, saisie consultant) — jamais faire confiance
    # à du texte utilisateur non échappé dans un document HTML->PDF.
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    template = env.get_template(HTML_TEMPLATE_NAME)
    contexte = dict(valeurs)
    contexte["jugement_requis"] = jugement_requis
    contexte["sexe_lettres"] = SEXE_EN_LETTRES.get(valeurs.get("sexe"), valeurs.get("sexe") or "")
    contexte["numero_suivi"] = numero_suivi or "—"
    return template.render(**contexte)


def _convertir_pdf(html: str) -> bytes:
    # Import différé : voir avertissement en tête de fichier (dépendances
    # système absentes par défaut sous Windows, présentes sur le VPS cible).
    from weasyprint import HTML
    return HTML(string=html, base_url=TEMPLATES_DIR).write_pdf()


class DemarcheSansModele(ValueError):
    """La démarche du dossier n'a pas de modèle de document."""


def generer_document(dossier_id: str) -> bytes:
    dossier = get_dossier(dossier_id)
    if not dossier:
        raise ValueError(f"Dossier introuvable : {dossier_id}")

    type_demarche = dossier.get("type_demarche") or "extrait_naissance"
    if type_demarche not in DEMARCHES_AVEC_MODELE:
        raise DemarcheSansModele(
            f"Aucun modèle de document pour la démarche « {type_demarche} ». "
            f"Le dossier reste consultable ; le document devra être établi hors de "
            f"l'application tant que son modèle n'est pas fourni."
        )

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

    instance_xsd = _construire_instance_xsd(valeurs, jugement_requis)
    erreurs_xsd = _valider_xsd(instance_xsd)
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

    html = _rendre_html(valeurs, jugement_requis, dossier.get("numero_suivi"))
    return _convertir_pdf(html)
