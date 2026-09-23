-- ============================================================================
-- Migration 020 — Toute phrase dite au citoyen est une donnée
-- Réf. : backend-agent/PLAN_MAITRE.md, étape 3
--
-- Le pulaar est incohérent parce que des phrases CONNUES D'AVANCE sont
-- retraduites par le modèle à chaque conversation, différemment à chaque fois.
-- L'étape 3 les fige : une phrase dont le pulaar est relu par un locuteur ne
-- repasse plus jamais par le modèle.
--
-- Encore faut-il que ces phrases existent quelque part. Les migrations 018 et
-- 019 ont sorti les questions et les demandes de pièce. Il restait deux
-- familles, toujours écrites dans le code :
--
--   1. Les RELANCES — ce que l'agent dit quand la réponse ne convient pas.
--      Elles étaient IMPROVISÉES par le modèle à chaque fois, donc traduites à
--      la volée. C'est le pire endroit pour du mauvais pulaar : le citoyen ne
--      comprenait déjà pas la question.
--   2. Les PHRASES SYSTÈME — confirmations, motifs de refus, messages de fin.
--      Une trentaine de phrases fixes, dispersées dans quatre fichiers.
--
-- Après cette migration, tout ce que l'agent dit d'avance prévisible est une
-- ligne de table, avec sa colonne pulaar et son drapeau de validation.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Relances par champ
--
-- Une LISTE, pas une phrase : deux relances consécutives identiques mot pour
-- mot donnent au citoyen l'impression de ne pas être entendu. Même principe
-- que `messages_rappel` pour les pièces (migration 018).
-- ----------------------------------------------------------------------------

alter table public.demarche_champs
    add column if not exists relances        text[] not null default '{}',
    add column if not exists relances_pulaar text[] not null default '{}';

comment on column public.demarche_champs.relances is
    'Ce que l''agent dit quand la réponse ne convient pas, à tour de rôle. Remplace une '
    'reformulation improvisée par le modèle, donc retraduite à chaque fois.';

-- Relances de départ, construites sur la question du champ. Volontairement
-- simples : à l'oral, la relance utile se résume à « ce n'est pas ce que je
-- demandais, voici ma question ». À affiner champ par champ si besoin.
update public.demarche_champs
set relances = array[
        'Je n''ai pas bien compris. ' || question,
        'Reprenons doucement. ' || question
    ]
where relances = '{}';

-- ----------------------------------------------------------------------------
-- 2. Phrases système
--
-- Tout ce que l'agent dit et qui n'appartient à aucun champ ni à aucune pièce.
-- `cle` est l'identifiant utilisé dans le code : il ne change jamais, c'est le
-- texte qui change.
-- ----------------------------------------------------------------------------

create table if not exists public.phrases_systeme (
    cle           text primary key,
    francais      text not null,
    pulaar        text,
    pulaar_valide boolean not null default false,
    audio         text,          -- clé du fichier pré-généré, remise à null quand le texte change
    contexte      text not null  -- où et quand cette phrase est dite, pour la relecture
);

comment on table public.phrases_systeme is
    'Phrases fixes dites au citoyen. `contexte` sert au relecteur : traduire « C''est noté » '
    'sans savoir quand la phrase est dite mène à un contresens.';
comment on column public.phrases_systeme.pulaar_valide is
    'false tant qu''un locuteur n''a pas relu. Une traduction non relue n''est JAMAIS dite : '
    'le français repart alors au traducteur, comme avant.';

insert into public.phrases_systeme (cle, francais, contexte) values
    -- Enchaînement normal
    ('confirmation_reponse', 'C''est noté.',
     'Après une réponse acceptée, juste avant la question suivante.'),
    ('confirmation_photo', 'Merci, photo bien reçue.',
     'Après réception d''une photo, juste avant l''étape suivante.'),

    -- Abandons et garde-fous
    ('champ_facultatif_abandonne', 'Ce n''est pas obligatoire, on continue.',
     'Le citoyen n''a pas su répondre à une question facultative ; on passe à la suite.'),
    ('document_facultatif_abandonne', 'Pas de problème, ce n''est pas obligatoire, on continue.',
     'Le citoyen n''a pas la pièce, et elle n''est pas obligatoire.'),
    ('document_obligatoire_abandonne',
     'D''accord, on continue sans cette photo pour l''instant — un agent de la mairie vous recontactera pour l''obtenir.',
     'Le citoyen n''a pas une pièce OBLIGATOIRE ; on avance quand même pour ne pas le bloquer.'),

    -- Incompréhension et fin de parcours
    ('repeter', 'Excusez-moi, je n''ai pas bien compris. Pouvez-vous répéter, s''il vous plaît ?',
     'Message vide ou inaudible : on redemande sans rien affirmer.'),
    ('blocage_relecture',
     'Je rencontre des difficultés à finaliser votre demande après plusieurs tentatives. Un agent de votre mairie va reprendre votre dossier directement — vous n''avez rien d''autre à faire pour l''instant.',
     'La relecture n''a jamais pu être confirmée ; le dossier passe à un agent.'),

    -- Motifs de refus d'une valeur (slot_controller.valider_valeur)
    ('refus_date_future', 'Cette date est dans le futur, ce qui n''est pas possible ici.',
     'Refus d''une date postérieure à aujourd''hui.'),
    ('refus_date_incomprise', 'Je n''ai pas compris cette date — précisez le jour, le mois et l''année.',
     'La date dite n''a pas pu être lue.'),
    ('refus_reponse_vide', 'Je n''ai rien entendu.',
     'Aucune parole reçue.'),
    ('refus_reponse_longue', 'La réponse est trop longue pour être un nom ou un lieu.',
     'Texte manifestement trop long pour le champ demandé.'),
    ('refus_oui_non', 'Dites-moi simplement oui, ou non.',
     'Réponse ambiguë à une question fermée.'),
    ('refus_nombre', 'Ce n''est pas un nombre que j''ai compris.',
     'La valeur dite n''est pas un nombre.')
on conflict (cle) do nothing;

-- Pas de RLS : table de configuration, lue par le backend (service role).
-- Le contenu est du texte public, jamais une donnée de citoyen.
