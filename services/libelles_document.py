"""
Libellés français des champs des documents générés, pour la lecture du
document par le citoyen (champ par champ, à l'oral) et pour désigner un champ
dans une remarque.

Mêmes clés que les templates XML (`templates/*_v1.xml`) et que le front web
(`src/lib/champLabels.ts`) — à garder synchronisés.

Étape 5.5 : le certificat de mariage constaté a ses propres champs, et surtout
son propre ORDRE de lecture. Sans ça, un citoyen qui demandait à relire son
certificat de mariage n'entendait RIEN : aucune clé du mariage ne figurait
dans la liste, qui ne connaissait que l'extrait de naissance.
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

    # --- Certificat de mariage constaté (étape 5.5) ---
    "epouxPrenoms": "Prénoms du mari",
    "epouxNomFamille": "Nom de famille du mari",
    "epouxProfession": "Métier du mari",
    "epouxDomicile": "Domicile du mari",
    "epouxDateNaissance": "Date de naissance du mari",
    "epouxDateNaissanceLettres": "Date de naissance du mari en lettres",
    "epouxLieuNaissance": "Lieu de naissance du mari",
    "epouxNomPere": "Père du mari",
    "epouxNomMere": "Mère du mari",
    "epousePrenoms": "Prénoms de l'épouse",
    "epouseNomFamille": "Nom de famille de l'épouse",
    "epouseProfession": "Métier de l'épouse",
    "epouseDomicile": "Domicile de l'épouse",
    "epouseDateNaissance": "Date de naissance de l'épouse",
    "epouseDateNaissanceLettres": "Date de naissance de l'épouse en lettres",
    "epouseLieuNaissance": "Lieu de naissance de l'épouse",
    "epouseNomPere": "Père de l'épouse",
    "epouseNomMere": "Mère de l'épouse",
    "dateCelebration": "Date du mariage",
    "dateCelebrationLettres": "Date du mariage en lettres",
    "lieuCelebration": "Lieu du mariage",
    "optionMatrimoniale": "Option souscrite",
    "regimeMatrimonial": "Régime des biens",
    "numeroRegistreChiffres": "Numéro du registre",

    # --- Acte de décès (étape 5.5) ---
    "defuntPrenoms": "Prénoms du défunt",
    "defuntNomFamille": "Nom de famille du défunt",
    "defuntSexe": "Sexe",
    "defuntDateNaissance": "Date de naissance",
    "defuntDateNaissanceLettres": "Date de naissance en lettres",
    "defuntLieuNaissance": "Lieu de naissance",
    "defuntProfession": "Métier",
    "defuntDomicile": "Domicile",
    "defuntNationalite": "Nationalité",
    "defuntSituationMatrimoniale": "Situation matrimoniale",
    "defuntConjoint": "Conjoint",
    "defuntNomPere": "Père",
    "defuntNomMere": "Mère",
    "dateDeces": "Date du décès",
    "dateDecesLettres": "Date du décès en lettres",
    "heureDecesLettres": "Heure du décès",
    "lieuDeces": "Lieu du décès",
    "communeDeces": "Commune du décès",
    "dateDressageLettres": "Date de l'acte en lettres",
    "nomDeclarant": "Nom du déclarant",
    "lienAvecDefunt": "Lien avec le défunt",
    "ageDeclarant": "Âge du déclarant",
    "professionDeclarant": "Métier du déclarant",
    "domicileDeclarant": "Domicile du déclarant",
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

#: L'ordre de lecture dépend du document : celui du mariage suit le certificat
#: réel — le mari, puis l'épouse, puis le mariage lui-même.
ORDRE_LECTURE_MARIAGE = [
    "epouxPrenoms",
    "epouxNomFamille",
    "epouxDateNaissance",
    "epouxLieuNaissance",
    "epouxNomPere",
    "epouxNomMere",
    "epousePrenoms",
    "epouseNomFamille",
    "epouseDateNaissance",
    "epouseLieuNaissance",
    "epouseNomPere",
    "epouseNomMere",
    "dateCelebration",
    "lieuCelebration",
    "optionMatrimoniale",
    "regimeMatrimonial",
]

#: L'acte de décès est relu à un proche, souvent endeuillé : on va droit à ce
#: qui peut être FAUX sur le document — l'identité, la date et le lieu — sans
#: dérouler les mentions administratives.
ORDRE_LECTURE_DECES = [
    "defuntPrenoms",
    "defuntNomFamille",
    "defuntDateNaissance",
    "defuntLieuNaissance",
    "defuntNomPere",
    "defuntNomMere",
    "dateDeces",
    "heureDecesLettres",
    "lieuDeces",
    "communeDeces",
    "nomDeclarant",
    "lienAvecDefunt",
]

ORDRES_PAR_DEMARCHE = {
    "extrait_naissance": ORDRE_LECTURE,
    "constatation_mariage": ORDRE_LECTURE_MARIAGE,
    "declaration_deces": ORDRE_LECTURE_DECES,
}


def ordre_lecture(type_demarche: str | None) -> list:
    """
    Les champs à relire au citoyen, pour SA démarche.

    Une démarche sans document (le décès aujourd'hui) renvoie une liste vide :
    rien à relire, plutôt que la liste d'un autre document.
    """
    return ORDRES_PAR_DEMARCHE.get(type_demarche or "extrait_naissance", [])


#: Codes du Code de la famille -> ce qui est imprimé et ce qui est DIT. Source
#: unique : `document_generator` les importe d'ici pour le PDF, et la lecture
#: au citoyen s'en sert pour ne pas lui réciter « separation_des_biens ».
OPTIONS_EN_LETTRES = {
    "monogamie": "Monogamie",
    "polygamie_2": "Polygamie limitée à deux épouses",
    "polygamie_3": "Polygamie limitée à trois épouses",
    "polygamie_4": "Polygamie limitée à quatre épouses",
}

REGIMES_EN_LETTRES = {
    "separation_des_biens": "Séparation des biens",
    "communaute": "Communauté des biens",
    "dotal": "Régime dotal",
}

#: Situation matrimoniale du défunt : (masculin, féminin). Un acte d'état
#: civil qui dit « veuf » d'une femme se trompe sur la personne, pas sur
#: l'orthographe.
SITUATIONS_EN_LETTRES = {
    "celibataire": ("célibataire", "célibataire"),
    "marie": ("époux", "épouse"),
    "veuf": ("veuf", "veuve"),
    "divorce": ("divorcé", "divorcée"),
}

#: Lieu du décès. Les quatre codes manquaient ici : ils ressortaient donc tels
#: quels — « Lieu du décès : structure_sanitaire », tiret bas compris, sur un
#: acte et à voix haute. Les libellés reprennent la question posée au citoyen
#: (« à la maison, dans un hôpital ou un poste de santé, sur la voie publique,
#: ou ailleurs ») pour qu'il reconnaisse sa propre réponse.
LIEUX_DECES_EN_LETTRES = {
    "domicile": "À domicile",
    "structure_sanitaire": "En structure sanitaire",
    "voie_publique": "Sur la voie publique",
    "autre": "Autre lieu",
}

VALEURS_EN_LETTRES = {
    **OPTIONS_EN_LETTRES,
    **REGIMES_EN_LETTRES,
    **LIEUX_DECES_EN_LETTRES,
    # Pour la relecture à voix haute, la forme masculine suffit : la phrase
    # lue est « Situation matrimoniale : veuf », pas une phrase d'acte.
    **{code: accords[0] for code, accords in SITUATIONS_EN_LETTRES.items()},
    "masculin": "Masculin",
    "feminin": "Féminin",
}


def libelle(cle: str) -> str:
    return LIBELLES.get(cle, cle)


def phrase_lecture(cle: str, valeur) -> str:
    """Phrase courte à dire au citoyen pour vérifier UN champ."""
    if valeur is None or valeur == "":
        return f"{libelle(cle)} : non renseigné."
    # Un code technique lu à voix haute ne veut rien dire pour le citoyen :
    # « Option souscrite : polygamie_2 » devient « Polygamie limitée à deux
    # épouses ». Une valeur non codée passe telle quelle.
    return f"{libelle(cle)} : {VALEURS_EN_LETTRES.get(valeur, valeur)}."
