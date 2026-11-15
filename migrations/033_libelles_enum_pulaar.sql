-- ============================================================================
-- Migration 033 — Les valeurs d'énumération se disent aussi
--
-- LE PROBLÈME
--
-- `services/gabarits._valeur_pulaar` renvoyait `None` pour TOUT champ de type
-- `enum`, sans exception :
--
--     # « masculin », « polygamie »… sont des mots français : les dire tels
--     # quels en pulaar serait faux. Sans traduction relue, pas de pulaar.
--
-- Le raisonnement est juste, mais il n'existait nulle part où ranger cette
-- traduction relue. Les valeurs autorisées vivent dans
-- `demarche_champs.regle_validation` (« monogamie|polygamie_2|… »), une simple
-- liste de codes, sans colonne pour leur libellé.
--
-- Conséquence : tout gabarit contenant un champ `enum` ne pouvait JAMAIS
-- produire de pulaar. Le récapitulatif du mariage, qui porte
-- `option_matrimoniale` et `regime_matrimonial`, repartait au traducteur à
-- chaque conversation — même une fois relu et validé.
--
-- LA RÉPONSE
--
-- Chaque code devient une ligne de `phrases_systeme`. Cette table porte déjà
-- exactement ce qu'il faut — `francais`, `pulaar`, `pulaar_valide`, `audio`,
-- `contexte` — et `services/atelier.collecter` la parcourt EN ENTIER : ces
-- libellés deviennent donc relisibles, écoutables et pré-générables sans une
-- ligne de code de plus dans l'atelier.
--
-- La règle du projet est préservée telle quelle : `pulaar` reste NULL et
-- `pulaar_valide` à false. Tant qu'un locuteur n'a pas relu, aucun pulaar
-- n'est dit et le français repart au traducteur, comme avant.
--
-- POURQUOI LE PRÉFIXE « valeur_ »
--
-- `cle` est la clé primaire, partagée avec les phrases système existantes
-- (« repeter », « refus_oui_non »…). Le préfixe évite toute collision et
-- regroupe ces lignes dans l'atelier, qui trie par clé : le relecteur les
-- traite d'affilée au lieu de les rencontrer dispersées.
--
-- Le `contexte` dit à quel champ et à quelle démarche le code appartient :
-- traduire « autre » sans savoir qu'il s'agit du lieu d'un décès mènerait à
-- un contresens.
-- ============================================================================

insert into public.phrases_systeme (cle, francais, contexte) values
    -- Option matrimoniale (constatation de mariage) — Code de la famille.
    ('valeur_monogamie', 'Monogamie',
     'Option matrimoniale déclarée par le mari, dite dans le récapitulatif du mariage.'),
    ('valeur_polygamie_2', 'Polygamie limitée à deux épouses',
     'Option matrimoniale déclarée par le mari, dite dans le récapitulatif du mariage.'),
    ('valeur_polygamie_3', 'Polygamie limitée à trois épouses',
     'Option matrimoniale déclarée par le mari, dite dans le récapitulatif du mariage.'),
    ('valeur_polygamie_4', 'Polygamie limitée à quatre épouses',
     'Option matrimoniale déclarée par le mari, dite dans le récapitulatif du mariage.'),

    -- Régime des biens (constatation de mariage).
    ('valeur_separation_des_biens', 'Séparation des biens',
     'Régime des biens choisi par les époux, dit dans le récapitulatif du mariage.'),
    ('valeur_communaute', 'Communauté des biens',
     'Régime des biens choisi par les époux, dit dans le récapitulatif du mariage.'),
    ('valeur_dotal', 'Régime dotal',
     'Régime des biens choisi par les époux, dit dans le récapitulatif du mariage.'),

    -- Sexe (extrait de naissance : l'enfant ; déclaration de décès : le défunt).
    ('valeur_masculin', 'Masculin',
     'Sexe de l''enfant ou du défunt, dit dans le récapitulatif.'),
    ('valeur_feminin', 'Féminin',
     'Sexe de l''enfant ou du défunt, dit dans le récapitulatif.'),

    -- Situation matrimoniale du défunt (déclaration de décès).
    -- La forme masculine suffit ici : la phrase dite est « Situation
    -- matrimoniale : veuf », pas une phrase d'acte accordée.
    ('valeur_celibataire', 'Célibataire',
     'Situation matrimoniale du défunt, dite dans le récapitulatif du décès.'),
    ('valeur_marie', 'Marié',
     'Situation matrimoniale du défunt, dite dans le récapitulatif du décès.'),
    ('valeur_veuf', 'Veuf',
     'Situation matrimoniale du défunt, dite dans le récapitulatif du décès.'),
    ('valeur_divorce', 'Divorcé',
     'Situation matrimoniale du défunt, dite dans le récapitulatif du décès.'),

    -- Lieu du décès (déclaration de décès).
    ('valeur_domicile', 'À domicile',
     'Lieu du décès, dit dans le récapitulatif du décès.'),
    ('valeur_structure_sanitaire', 'En structure sanitaire',
     'Lieu du décès (hôpital, poste de santé), dit dans le récapitulatif du décès.'),
    ('valeur_voie_publique', 'Sur la voie publique',
     'Lieu du décès, dit dans le récapitulatif du décès.'),
    ('valeur_autre', 'Autre lieu',
     'Lieu du décès, quand aucune des autres réponses ne convient.')
on conflict (cle) do nothing;

-- Vérification :
--   select cle, francais, pulaar_valide from public.phrases_systeme
--    where cle like 'valeur_%' order by cle;
-- Les dix-sept lignes doivent exister, toutes avec pulaar_valide = false :
-- elles attendent l'atelier (`/admin/atelier`, onglet « Phrases générales »).
