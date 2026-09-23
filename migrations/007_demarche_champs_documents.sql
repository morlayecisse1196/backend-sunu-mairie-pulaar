-- ============================================================================
-- Migration 007 — Définition en base des démarches (champs + documents)
-- Réf. : MEMOIR2/SUNU_MAIRIE_PROMPTS.md, Sprint J, Tâche J.1
--        backend-agent/PLAN_REFACTOR_DIALOGUE_CHAMPS.md §2 (schéma détaillé)
--
-- Aujourd'hui, la séquence de questions de l'extrait de naissance est codée en
-- dur (SLOTS_REQUIS_RELECTURE dans dialogue_engine.py + TYPES_DOCUMENT_EXTRAIT_
-- NAISSANCE), sans ordre explicite ni règle de validation par champ. Ces deux
-- tables déplacent cette définition en donnée : un contrôleur générique
-- (slot_controller.py, Tâche J.4) pourra piloter n'importe quelle démarche en
-- lisant ces lignes, sans modification de code pour une future démarche.
--
-- Les deux tables partagent le même espace d'`ordre` (entrelacé) pour une
-- démarche donnée : la séquence réelle du dialogue s'obtient en triant
-- l'union des deux tables par (type_demarche, ordre).
-- ============================================================================

create table if not exists public.demarche_champs (
    id                 uuid primary key default gen_random_uuid(),
    type_demarche      text not null,
    ordre              integer not null,
    nom_champ          text not null,          -- garde les noms actuels (nom_mere, date_naissance_mere, ...)
    type_valeur        text not null
        check (type_valeur in ('texte', 'date', 'nombre', 'booleen', 'age', 'enum')),
    question           text not null,          -- question par défaut posée au citoyen
    regle_validation   text,                   -- nom d'un validateur enregistré (ex. "date_iso_passee"), optionnel
    obligatoire        boolean not null default true,
    unique (type_demarche, nom_champ)
);

create table if not exists public.demarche_documents (
    id                 uuid primary key default gen_random_uuid(),
    type_demarche      text not null,
    ordre              integer not null,       -- même espace d'ordre que demarche_champs (entrelacés)
    type_document      text not null,          -- ex. "certificat_naissance" (cf. TYPES_DOCUMENT_VALIDES, dialogue_engine.py)
    obligatoire        boolean not null default true,
    condition_champ    text,                   -- ex. "parents_maries" — document non demandé si ce champ est faux
    apres_champ        text,                   -- nom_champ après lequel ce document doit être demandé
    unique (type_demarche, type_document)
);

create index if not exists idx_demarche_champs_type_ordre on public.demarche_champs(type_demarche, ordre);
create index if not exists idx_demarche_documents_type_ordre on public.demarche_documents(type_demarche, ordre);

-- Pas de RLS : lecture exclusivement via le backend (service role), même
-- principe que cas_particuliers/remarques/communes (cf. 001_dossiers.sql,
-- note finale) — ce sont des tables de configuration, pas de données
-- utilisateur.

-- ----------------------------------------------------------------------------
-- Seed — démarche "extrait_naissance"
--
-- Séquence reprise telle quelle des 7 slots de SLOTS_REQUIS_RELECTURE
-- (dialogue_engine.py) + age_enfant (précondition d'entrée en mode
-- administratif, déjà connue au moment de la bascule B.3, mais incluse ici
-- pour que la démarche reste décrivable de bout en bout par la donnée seule),
-- dans l'ordre de l'Exemple 2.1 (README-MISE-A-JOUR-APP/Exemples_Dialogues_
-- Agent_SUNU-MAIRIE.md, "Points d'implémentation" — machine à états suggérée :
-- commune_naissance → certificat_naissance → nom_enfant → date_naissance_
-- enfant → nom_declarant → cni_declarant → nom_mere/date_naissance_mere →
-- parents_maries → [livret_famille / certificat_mariage]).
--
-- `ordre` est espacé de 10 pour permettre l'insertion future d'un champ entre
-- deux existants sans renuméroter toute la séquence.
-- ----------------------------------------------------------------------------

insert into public.demarche_champs
    (type_demarche, ordre, nom_champ, type_valeur, question, regle_validation, obligatoire)
values
    ('extrait_naissance', 5,  'age_enfant',           'age',     'Quel âge a votre enfant ?', null, true),
    ('extrait_naissance', 10, 'commune_naissance',    'texte',   'Dans quelle commune votre enfant est-il né ?', null, true),
    ('extrait_naissance', 30, 'nom_enfant',           'texte',   'Quel est le nom complet de votre enfant ?', null, true),
    ('extrait_naissance', 40, 'date_naissance_enfant','date',    'Quelle est sa date de naissance exacte ?', 'date_iso_passee', true),
    ('extrait_naissance', 50, 'nom_declarant',        'texte',   'Pouvez-vous me donner votre nom complet, à vous, en tant que déclarant ?', null, true),
    ('extrait_naissance', 70, 'nom_mere',             'texte',   'Quel est le nom complet de la maman de l''enfant ?', null, true),
    ('extrait_naissance', 80, 'date_naissance_mere',  'date',    'Quelle est sa date de naissance, à elle ?', 'date_iso_passee', true),
    ('extrait_naissance', 90, 'parents_maries',       'booleen', 'Êtes-vous mariés, elle et vous ?', null, true)
on conflict (type_demarche, nom_champ) do nothing;

insert into public.demarche_documents
    (type_demarche, ordre, type_document, obligatoire, condition_champ, apres_champ)
values
    ('extrait_naissance', 20,  'certificat_naissance', true,  null,             'commune_naissance'),
    ('extrait_naissance', 60,  'cni_declarant',         true,  null,             'nom_declarant'),
    ('extrait_naissance', 100, 'livret_famille',        false, 'parents_maries', 'parents_maries'),
    ('extrait_naissance', 100, 'certificat_mariage',    false, 'parents_maries', 'parents_maries')
on conflict (type_demarche, type_document) do nothing;
