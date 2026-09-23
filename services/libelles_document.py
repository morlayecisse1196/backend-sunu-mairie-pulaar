"""
Libellés français des champs de l'extrait de naissance (schéma XSD), pour la
lecture du document par le citoyen (champ par champ, à l'oral) et pour
désigner un champ dans une remarque.

Mêmes clés que `templates/extrait_naissance.xsd` et que le front web
(`src/lib/champLabels.ts`) — à garder synchronisés.
"""
from __future__ import annotations

LIBELLES = {
    "prenomEnfant": "Prénom de l'enfant",
    "nomFamilleEnfant": "Nom de famille de l'enfant",
    "dateNaissance": "Date de naissance",
    "dateNaissanceLettres": "Date de naissance en lettres",
    "heureNaissance": "Heure de naissance",
    "lieuNaissance": "Lieu de naissance",
    "sexe": "Sexe",
    "prenomPere": "Prénom du père",
    "prenomMere": "Prénom de la mère",
    "nomFamilleMere": "Nom de famille de la mère",
    "paysNaissanceEtranger": "Pays de naissance",
    "region": "Région",
    "departement": "Département",
    "arrondissement": "Arrondissement",
    "collectiviteLocale": "Commune",
    "nomCentreEtatCivil": "Centre d'état civil",
    "numeroActe": "Numéro de l'acte",
    "officierEtatCivil": "Officier d'état civil",
    "dateDelivrance": "Date de délivrance",
}

# Champs lus au citoyen pour vérification (dans cet ordre) : ceux qui le
# concernent vraiment, pas les références administratives du registre.
ORDRE_LECTURE = [
    "prenomEnfant",
    "nomFamilleEnfant",
    "sexe",
    "dateNaissance",
    "heureNaissance",
    "lieuNaissance",
    "prenomPere",
    "prenomMere",
    "nomFamilleMere",
]


def libelle(cle: str) -> str:
    return LIBELLES.get(cle, cle)


def phrase_lecture(cle: str, valeur) -> str:
    """Phrase courte à dire au citoyen pour vérifier UN champ."""
    if valeur is None or valeur == "":
        return f"{libelle(cle)} : non renseigné."
    return f"{libelle(cle)} : {valeur}."
