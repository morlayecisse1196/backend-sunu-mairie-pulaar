-- ============================================================================
-- Migration 009 — CNI du déclarant : recto ET verso (2 photos), pas une seule
-- Réf. : MEMOIR2/SUNU_MAIRIE_PROMPTS.md, Sprint J, Tâche J.7 (adaptation
--        demandée en marge de J.7 — retour terrain du 2026-08-24) :
--        un consultant a besoin des DEUX faces de la carte d'identité du
--        déclarant pour la vérifier, pas d'une seule photo.
--
-- Remplace le document unique "cni_declarant" (une photo) par deux documents
-- SÉQUENTIELS (pas un groupe alternatif comme livret_famille/certificat_
-- mariage — ordres DIFFÉRENTS ici, donc bien demandés l'un après l'autre,
-- tous les deux obligatoires) : "cni_declarant_recto" (le côté avec la photo)
-- puis "cni_declarant_verso" (le côté sans photo).
--
-- "cni_declarant" (le type) reste une valeur valide ailleurs dans le code
-- (TYPES_DOCUMENT_VALIDES, documents déjà uploadés lors des tests précédents,
-- test_document_generator.py) — seule sa présence dans demarche_documents
-- pour l'extrait de naissance est retirée ici, remplacée par les deux
-- nouveaux types.
-- ============================================================================

delete from public.demarche_documents
where type_demarche = 'extrait_naissance' and type_document = 'cni_declarant';

insert into public.demarche_documents
    (type_demarche, ordre, type_document, obligatoire, condition_champ, apres_champ)
values
    ('extrait_naissance', 60, 'cni_declarant_recto', true, null, 'nom_declarant'),
    ('extrait_naissance', 61, 'cni_declarant_verso', true, null, 'nom_declarant')
on conflict (type_demarche, type_document) do nothing;
