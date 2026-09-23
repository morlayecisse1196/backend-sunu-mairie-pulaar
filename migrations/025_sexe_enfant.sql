-- ============================================================================
-- Migration 025 — Le dialogue demande le sexe de l'enfant
-- Réf. : backend-agent/PLAN_MAITRE.md, étape 5.1
--
-- L'acte l'exige (case « Enfant de sexe »), et le consultant devait jusqu'ici
-- le deviner d'après le prénom ou rappeler la famille. La réponse pré-remplit
-- le champ « sexe » de son formulaire ; il la vérifie comme les autres.
--
-- La question entre dans le BROUILLON de la démarche : les citoyens ne
-- l'entendent qu'après publication, depuis l'écran Démarches.
-- Pas de pulaar ici : il se saisit et s'écoute dans l'atelier.
-- ============================================================================

insert into public.demarche_champs
    (type_demarche, ordre, nom_champ, type_valeur, question, regle_validation, obligatoire, relances)
values (
    'extrait_naissance', 35, 'sexe_enfant', 'enum',
    'Votre enfant est-il un garçon ou une fille ?',
    'masculin|feminin',
    true,
    array[
        'Je n''ai pas bien compris. C''est un garçon ou une fille ?',
        'Reprenons doucement : votre enfant est-il un garçon ou une fille ?'
    ]
)
on conflict (type_demarche, nom_champ) do nothing;
