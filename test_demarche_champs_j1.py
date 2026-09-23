"""
Test manuel — Sprint J, Tâche J.1 (migration 007 : demarche_champs / demarche_documents).

Critère de validation explicite (SUNU_MAIRIE_PROMPTS.md, Tâche J.1) : une requête
sur les deux tables triée par `ordre` retrouve exactement la séquence actuelle de
l'extrait de naissance (champs et documents entrelacés correctement).

Prérequis : les migrations `migrations/007_demarche_champs_documents.sql` ET
`migrations/008_regle_validation_dates_demarche.sql` ET
`migrations/009_cni_declarant_recto_verso.sql` doivent avoir été exécutées
dans le SQL Editor de Supabase (comme les migrations précédentes, cf.
006_tampon_confirmations.sql) — ce script ne fait que LIRE, jamais de DDL.

Mis à jour Tâche J.7 (adaptation demandée en marge) : "cni_declarant" (une
seule photo) est remplacé par "cni_declarant_recto" + "cni_declarant_verso"
(2 photos séquentielles, migration 009).
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from supabase_client import get_supabase_client
from dialogue_engine import SLOTS_REQUIS_RELECTURE, TYPES_DOCUMENT_EXTRAIT_NAISSANCE

client = get_supabase_client()

# Séquence attendue : les 7 slots existants + age_enfant, puis les documents
# entrelacés au bon endroit (cf. Exemple 2.1, "Points d'implémentation").
SEQUENCE_ATTENDUE = [
    ("champ", "age_enfant"),
    ("champ", "commune_naissance"),
    ("document", "certificat_naissance"),
    ("champ", "nom_enfant"),
    ("champ", "date_naissance_enfant"),
    ("champ", "nom_declarant"),
    ("document", "cni_declarant_recto"),  # Tâche J.7 : remplace l'ancien "cni_declarant" (1 photo -> 2)
    ("document", "cni_declarant_verso"),  # séquentiel (pas alternatif) : les deux sont obligatoires
    ("champ", "nom_mere"),
    ("champ", "date_naissance_mere"),
    ("champ", "parents_maries"),
    ("document", "livret_famille"),       # optionnel, condition_champ=parents_maries
    ("document", "certificat_mariage"),   # optionnel, condition_champ=parents_maries
]


def main_test():
    champs = (
        client.table("demarche_champs")
        .select("*")
        .eq("type_demarche", "extrait_naissance")
        .order("ordre")
        .execute()
        .data
    )
    documents = (
        client.table("demarche_documents")
        .select("*")
        .eq("type_demarche", "extrait_naissance")
        .order("ordre")
        .execute()
        .data
    )

    print(f"demarche_champs: {len(champs)} lignes")
    print(f"demarche_documents: {len(documents)} lignes")

    # 1. Couverture : les 7 slots de SLOTS_REQUIS_RELECTURE + age_enfant, rien
    #    de plus, rien de moins.
    noms_champs = {c["nom_champ"] for c in champs}
    attendu_champs = set(SLOTS_REQUIS_RELECTURE) | {"age_enfant"}
    assert noms_champs == attendu_champs, (
        f"Champs incohérents avec SLOTS_REQUIS_RELECTURE : "
        f"manquants={attendu_champs - noms_champs}, en_trop={noms_champs - attendu_champs}"
    )
    print("OK - les 8 champs (7 slots + age_enfant) sont tous présents, aucun en trop")

    # 2. Couverture documents : certificat_naissance/cni_declarant (obligatoires,
    #    cf. TYPES_DOCUMENT_EXTRAIT_NAISSANCE) + livret_famille/certificat_mariage
    #    (optionnels, RG6).
    noms_documents = {d["type_document"] for d in documents}
    for type_doc in TYPES_DOCUMENT_EXTRAIT_NAISSANCE:
        assert type_doc in noms_documents, f"Document manquant : {type_doc}"
    assert "certificat_mariage" in noms_documents, "certificat_mariage (alternative au livret) manquant"
    print(f"OK - documents présents : {sorted(noms_documents)}")

    # 3. Ordre entrelacé EXACT : fusionner les deux tables par `ordre`, comparer
    #    à la séquence attendue (issue de l'Exemple 2.1).
    fusion = [("champ", c["nom_champ"], c["ordre"]) for c in champs] + [
        ("document", d["type_document"], d["ordre"]) for d in documents
    ]
    fusion.sort(key=lambda t: t[2])
    sequence_obtenue = [(t[0], t[1]) for t in fusion]

    assert sequence_obtenue == SEQUENCE_ATTENDUE, (
        f"Séquence entrelacée incorrecte.\nAttendu : {SEQUENCE_ATTENDUE}\nObtenu  : {sequence_obtenue}"
    )
    print("OK - séquence entrelacée (champs + documents) EXACTEMENT dans le bon ordre :")
    for type_etape, nom in sequence_obtenue:
        print(f"    {type_etape:9s} -> {nom}")

    # 4. Contraintes métier attendues sur les documents optionnels.
    par_type = {d["type_document"]: d for d in documents}
    for type_doc in ("livret_famille", "certificat_mariage"):
        d = par_type[type_doc]
        assert d["obligatoire"] is False, f"{type_doc} devrait être optionnel (RG6)"
        assert d["condition_champ"] == "parents_maries", f"{type_doc}.condition_champ incorrect"
        assert d["apres_champ"] == "parents_maries", f"{type_doc}.apres_champ incorrect"
    for type_doc in ("certificat_naissance", "cni_declarant_recto", "cni_declarant_verso"):
        d = par_type[type_doc]
        assert d["obligatoire"] is True, f"{type_doc} devrait être obligatoire"
    print("OK - livret_famille/certificat_mariage optionnels et conditionnés à parents_maries")

    # 5. type_valeur cohérent (age_enfant -> 'age', dates -> 'date', booléen -> 'booleen').
    par_champ = {c["nom_champ"]: c for c in champs}
    assert par_champ["age_enfant"]["type_valeur"] == "age"
    assert par_champ["date_naissance_enfant"]["type_valeur"] == "date"
    assert par_champ["date_naissance_mere"]["type_valeur"] == "date"
    assert par_champ["parents_maries"]["type_valeur"] == "booleen"
    print("OK - type_valeur cohérent pour age_enfant/dates/parents_maries")

    print("\nTâche J.1 validée : migration 007 en place, séquence entrelacée correcte.")


if __name__ == "__main__":
    main_test()
