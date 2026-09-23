"""
Test manuel — Sprint D, Tâche D.2 (document_generator.py).

weasyprint est bloqué en local (bibliothèques système Pango/GObject/Cairo
absentes sous Windows, cf. avertissement en tête de document_generator.py) —
ce test valide donc tout le pipeline JUSQU'À la conversion PDF (résolution,
validation XSD, rendu HTML), et confirme explicitement que generer_document()
échoue précisément à l'étape weasyprint (pas avant) pour un dossier complet.

  1. Dossier complet (tous les slots + tous les formulaires remplis, cas
     "dans_les_delais") -> résolution + validation XSD + rendu HTML réussissent,
     le HTML contient bien les valeurs attendues ET le bandeau "brouillon
     officiel" (critère de validation, en substitut du PDF pour l'instant).
  2. Dossier incomplet (champs obligatoires manquants) -> échec explicite
     (ErreurGenerationDocument) + CasParticulier créé.
  3. Dossier complet mais numeroActe malformé (pas 19 chiffres) -> échec
     explicite à l'étape XSD spécifiquement (pas à l'étape "champs manquants").
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

import main  # noqa: E402
from dossiers_repo import get_document_formulaire, update_champ_formulaire, get_supabase_client
from test_bascule_administratif import TEST_CITOYEN_ID
import document_generator as dg


def _remplir_formulaire(dossier_id: str, type_document: str, valeurs: dict, document_id=None):
    """Crée/complète un document_formulaires directement (sans passer par l'upload B.5)."""
    supabase = get_supabase_client()
    from dialogue_engine import construire_champs_formulaire
    champs = construire_champs_formulaire(type_document, {})
    payload = {
        "dossier_id": dossier_id, "document_id": document_id, "type_document": type_document,
        "champs": champs, "statut": "a_remplir",
    }
    response = supabase.table("document_formulaires").insert(payload).execute()
    formulaire = response.data[0]
    for nom, valeur in valeurs.items():
        formulaire = update_champ_formulaire(formulaire, nom, valeur=str(valeur))
    return formulaire


def creer_dossier_complet(numero_acte="0000000000000000194"):
    commune_id = main.resoudre_commune_id("Ross-Béthio")
    slots = dict(main.SLOTS_VIDES_EXTRAIT_NAISSANCE)
    slots.update({
        "age_enfant": {"valeur": 3, "unite": "mois"},
        "commune_naissance": "Ross-Béthio", "nom_enfant": "Marya Ndoye",
        "date_naissance_enfant": "1967-10-14", "nom_declarant": "Babacar Diop",
        "nom_mere": "Salimata Diop", "date_naissance_mere": "1940-01-01", "parents_maries": True,
    })
    dossier = main.create_dossier(
        citoyen_id=TEST_CITOYEN_ID, type_demarche="extrait_naissance",
        slots=slots, cas_legal="tardif", commune_id=commune_id, statut="en_traitement",
    )
    assert dossier

    _remplir_formulaire(dossier["id"], "certificat_naissance", {
        "prenomEnfant": "Marya", "nomFamilleEnfant": "Ndoye",
        "dateNaissanceLettres": "quatorze octobre mille neuf cent soixante sept",
        "heureNaissance": "", "sexe": "F", "prenomPere": "Babacar",
        "prenomMere": "Salimata", "nomFamilleMere": "Diop", "paysNaissanceEtranger": "",
    })
    _remplir_formulaire(dossier["id"], "cni_declarant", {"nomDeclarant": "Babacar Diop", "numeroCNI": "1234567890123"})

    from dossiers_repo import get_or_create_formulaire_acte
    get_or_create_formulaire_acte(dossier["id"])
    formulaire_acte = [
        f for f in dg.list_document_formulaires(dossier["id"])
        if f["type_document"] == "extrait_naissance"
    ][0]
    for nom, valeur in {
        "numeroActe": numero_acte, "anneeRegistreLettres": "Mille neuf cent soixante sept",
        "anneeRegistreChiffres": "1967", "numeroRegistreLettres": "Cent quatre vingt quatorze",
        "numeroRegistreChiffres": "194", "officierEtatCivil": "Gorgui Mbodji",
    }.items():
        formulaire_acte = update_champ_formulaire(formulaire_acte, nom, valeur=valeur)

    return dossier


def test_dossier_complet():
    print("=== 1. Dossier complet : résolution + XSD + HTML ===")
    dossier = creer_dossier_complet()

    from dossiers_repo import get_commune, list_document_formulaires
    commune_obj = get_commune(dossier["commune_id"])
    formulaires = list_document_formulaires(dossier["id"])
    champs_formulaire = {}
    for f in formulaires:
        for champ in f["champs"]:
            if champ["valeur"] is not None:
                champs_formulaire[champ["nom"]] = champ["valeur"]

    jugement_requis = dossier["cas_legal"] == "jugement_requis"
    valeurs, erreurs = dg._resoudre_template(dossier, commune_obj, champs_formulaire, jugement_requis)
    print("Erreurs de résolution :", erreurs)
    assert not erreurs, f"Champs obligatoires manquants inattendus : {erreurs}"

    instance = dg._construire_instance_xsd(valeurs, jugement_requis)
    erreurs_xsd = dg._valider_xsd(instance)
    print("Erreurs XSD :", erreurs_xsd)
    assert not erreurs_xsd, f"Validation XSD inattendue en échec : {erreurs_xsd}"
    print("✅ Résolution + validation XSD réussies.")

    html = dg._rendre_html(valeurs, jugement_requis, dossier["numero_suivi"])
    assert "BROUILLON OFFICIEL" in html, "Bandeau légal absent du HTML rendu !"
    assert "Marya" in html and "Ndoye" in html and "Ross-Béthio" in html and "Salimata" in html
    print("✅ HTML rendu contient le bandeau + les valeurs attendues (critère de validation, version texte).")

    try:
        pdf_bytes = dg.generer_document(dossier["id"])
    except (ModuleNotFoundError, OSError) as e:
        print(f"\n⚠️ weasyprint indisponible dans cet environnement ({e}) — pipeline validé jusque-là seulement.")
        return

    assert pdf_bytes.startswith(b"%PDF"), "Le résultat ne ressemble pas à un PDF valide"
    with open("test_extrait_naissance.pdf", "wb") as f:
        f.write(pdf_bytes)
    print(f"\n✅ PDF généré et sauvegardé : test_extrait_naissance.pdf ({len(pdf_bytes)} octets)")

    from pypdf import PdfReader
    import io
    texte = "".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf_bytes)).pages)
    for attendu in ["BROUILLON OFFICIEL", "Marya", "Ndoye", "Ross-Béthio", "Salimata", "Diop", "Gorgui Mbodji"]:
        assert attendu in texte, f"'{attendu}' absent du texte extrait du PDF !"
    print("✅ Bandeau + toutes les valeurs attendues retrouvées dans le texte extrait du PDF.")


def test_champs_manquants():
    print("\n=== 2. Dossier incomplet : échec explicite + CasParticulier ===")
    commune_id = main.resoudre_commune_id("Ross-Béthio")
    dossier = main.create_dossier(
        citoyen_id=TEST_CITOYEN_ID, type_demarche="extrait_naissance",
        slots=dict(main.SLOTS_VIDES_EXTRAIT_NAISSANCE), cas_legal="tardif",
        commune_id=commune_id, statut="en_traitement",
    )
    assert dossier
    try:
        dg.generer_document(dossier["id"])
        assert False, "generer_document() aurait dû échouer sur un dossier vide !"
    except dg.ErreurGenerationDocument as e:
        print(f"✅ Échec explicite : {e}")
        assert len(e.erreurs) > 0

    supabase = get_supabase_client()
    cas = supabase.table("cas_particuliers").select("*").eq("dossier_id", dossier["id"]).execute().data
    assert cas and cas[0]["type_incident"] == "champs_obligatoires_manquants"
    print("✅ CasParticulier créé en base :", cas[0]["type_incident"])


def test_numero_acte_malforme():
    print("\n=== 3. Dossier complet mais numeroActe malformé : échec XSD spécifique ===")
    dossier = creer_dossier_complet(numero_acte="123")  # pas 19 chiffres -> pattern XSD violé
    try:
        dg.generer_document(dossier["id"])
        assert False, "generer_document() aurait dû échouer sur un numeroActe invalide !"
    except dg.ErreurGenerationDocument as e:
        print(f"✅ Échec explicite (validation XSD, pas 'champs manquants') : {e}")

    supabase = get_supabase_client()
    cas = supabase.table("cas_particuliers").select("*").eq("dossier_id", dossier["id"]).execute().data
    assert cas and cas[0]["type_incident"] == "validation_xsd_echouee"
    print("✅ CasParticulier créé avec le bon type_incident :", cas[0]["type_incident"])


if __name__ == "__main__":
    test_dossier_complet()
    test_champs_manquants()
    test_numero_acte_malforme()
    print("\n✅ Tâche D.2 : pipeline de génération validé jusqu'à l'étape PDF (bloquée localement par l'environnement Windows, pas par le code)")
