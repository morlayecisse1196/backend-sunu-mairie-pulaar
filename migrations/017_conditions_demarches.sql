-- ============================================================================
-- Migration 017 — Les quatre formes de conditions d'une démarche
-- Réf. : backend-agent/PLAN_MAITRE.md, étape 2.1
--
-- Le modèle des migrations 007/008/009 ne sait exprimer qu'une seule forme de
-- condition : `demarche_documents.condition_champ`, un nom de champ dont la
-- valeur doit être vraie. Les règles réelles de l'état civil sénégalais en
-- demandent quatre :
--
--   1. CHAMP OBLIGATOIRE — colonne `obligatoire`, déjà présente mais jamais
--      lue par le moteur jusqu'ici (un champ facultatif bloquait la collecte
--      aussi sûrement qu'un champ obligatoire).
--   2. DÉLAI QUI INTERROMPT LA DÉMARCHE — six mois pour la constatation de
--      mariage, un an pour l'inscription d'un décès. Ni l'un ni l'autre ne se
--      rattache à une étape : c'est la démarche entière qui s'arrête.
--      -> table `demarche_regles`, effet `bloquer`.
--   3. CONDITION CROISÉE ENTRE DEUX CHAMPS — l'option polygamique interdit le
--      régime de la communauté de biens.
--      -> table `demarche_regles`, effet `interdire`.
--   4. ALTERNATIVE ENTRE DEUX PIÈCES — certificat médical OU deux témoins.
--      -> colonne `groupe` sur `demarche_documents`.
--
-- La forme 4 fonctionnait déjà, mais par une CONVENTION IMPLICITE : deux
-- documents partageant le même `ordre` formaient un groupe alternatif. Rien ne
-- le disait dans le schéma, et renuméroter un ordre cassait silencieusement
-- l'alternative. La colonne `groupe` rend l'intention explicite ; le code
-- continue de comprendre l'ancienne convention pour les lignes non migrées.
--
-- COMPATIBILITÉ : le moteur lit `condition` en priorité et retombe sur
-- `condition_champ`, lit `groupe` et retombe sur l'`ordre` partagé. Il
-- fonctionne donc avant comme après cette migration.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Conditions calculées sur les champs et les documents
-- ----------------------------------------------------------------------------

alter table public.demarche_champs
    add column if not exists condition text;

comment on column public.demarche_champs.condition is
    'Condition d''affichage (services/conditions.py). Question posée seulement si vraie. '
    'Ex. "option_matrimoniale = polygamie". Vide = toujours posée.';

alter table public.demarche_documents
    add column if not exists condition text,
    add column if not exists groupe text;

comment on column public.demarche_documents.condition is
    'Condition de demande (services/conditions.py). Remplace condition_champ, qui reste lu en repli.';
comment on column public.demarche_documents.groupe is
    'Nom du groupe alternatif : une seule pièce du groupe suffit. Remplace la convention implicite '
    'de l''ordre partagé.';

-- `condition_champ` disait « demander ce document si ce champ est vrai ».
update public.demarche_documents
set condition = condition_champ || ' = oui'
where condition_champ is not null and condition is null;

-- Le seul groupe alternatif existant : livret de famille OU certificat de
-- mariage (même ordre 100, cf. seed de la migration 007).
update public.demarche_documents
set groupe = 'preuve_mariage'
where type_demarche = 'extrait_naissance'
  and type_document in ('livret_famille', 'certificat_mariage')
  and groupe is null;

-- ----------------------------------------------------------------------------
-- Règles transverses : délai bloquant (forme 2) et combinaison interdite (forme 3)
-- ----------------------------------------------------------------------------

create table if not exists public.demarche_regles (
    id             uuid primary key default gen_random_uuid(),
    type_demarche  text not null,
    code           text not null,            -- identifiant stable, cité dans les messages d'erreur et les tests
    ordre          integer not null default 0,
    condition      text not null,            -- services/conditions.py
    effet          text not null check (effet in ('bloquer', 'interdire')),
    champ_concerne text,                     -- effet `interdire` : le champ à vider et redemander
    message        text not null,            -- ce qui est dit au citoyen, en français (traduit ensuite)
    source         text,                     -- référence juridique — obligatoire en pratique, cf. règle 3 du plan maître
    hypothese      boolean not null default false,  -- règle non confirmée par un officier d'état civil
    unique (type_demarche, code)
);

create index if not exists idx_demarche_regles_type_ordre
    on public.demarche_regles(type_demarche, ordre);

comment on table public.demarche_regles is
    'Règles portant sur la démarche entière, pas sur une étape : délais qui interrompent la démarche '
    '(effet bloquer) et combinaisons de champs interdites (effet interdire).';
comment on column public.demarche_regles.hypothese is
    'true tant qu''un officier d''état civil n''a pas confirmé la règle. À afficher comme telle côté admin.';

-- Pas de RLS : table de configuration, lue exclusivement par le backend
-- (service role), même principe que demarche_champs/demarche_documents.

-- ----------------------------------------------------------------------------
-- Aucun seed ici.
--
-- Les règles réelles de délai et d'incompatibilité appartiennent à la
-- constatation de mariage et à la déclaration de décès, qui n'existent pas
-- encore (étape 5 du plan maître) — les semer maintenant reviendrait à figer
-- des règles de droit avant leur relecture par un officier d'état civil.
-- L'extrait de naissance n'a aujourd'hui aucune règle transverse : son seul
-- seuil (le cas légal selon l'âge) reste dans `dialogue_engine.determiner_
-- cas_legal` jusqu'à l'étape 2.3, qui le sortira du code.
-- ----------------------------------------------------------------------------
