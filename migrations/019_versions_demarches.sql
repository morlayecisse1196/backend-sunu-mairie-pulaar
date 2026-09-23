-- ============================================================================
-- Migration 019 — Une démarche modifiée ne change pas sous les pieds du citoyen
-- Réf. : backend-agent/PLAN_MAITRE.md, étape 2.4
--
-- Depuis les migrations 017 et 018, une démarche se modifie en base. À partir
-- de l'étape 4, elle se modifiera depuis l'interface admin, en pleine journée,
-- pendant que des citoyens y répondent. Sans cette migration, la modification
-- prend effet AU TOUR SUIVANT pour tout le monde :
--
--   * une question ajoutée au milieu du parcours ressurgit après le
--     récapitulatif, alors que le citoyen venait de tout confirmer ;
--   * une question retirée laisse une valeur orpheline dans le dossier ;
--   * un seuil de cas légal modifié reclasse un dossier déjà déposé ;
--   * une pièce rendue obligatoire bloque un dossier presque terminé.
--
-- Une démarche est donc PUBLIÉE : chaque publication fige un instantané complet
-- (définition, champs, pièces, règles, cas). Un dialogue retient le numéro de
-- version sous lequel il a commencé et le garde jusqu'au bout. La publication
-- suivante ne concerne que les dialogues commencés après elle.
-- ============================================================================

create table if not exists public.demarche_versions (
    type_demarche text    not null,
    version       integer not null,
    publiee_le    timestamptz not null default now(),
    publiee_par   text,                 -- e-mail de l'agent, ou 'migration' / 'script'
    contenu       jsonb   not null,     -- instantané complet, voir plus bas
    primary key (type_demarche, version)
);

comment on table public.demarche_versions is
    'Instantané figé d''une démarche à sa publication. Jamais modifié après coup : un dossier '
    'doit pouvoir être relu des mois plus tard avec les règles qui lui ont été appliquées.';
comment on column public.demarche_versions.contenu is
    'jsonb {definition, champs[], documents[], regles[], cas[]} — la démarche entière telle '
    'qu''elle était au moment de la publication.';

-- Une version publiée ne se modifie pas : autoriser une mise à jour, ce serait
-- réécrire l'histoire d'un dossier déjà déposé.
revoke update, delete on public.demarche_versions from public;

-- Version sous laquelle le dossier a été constitué : sans elle, impossible de
-- relire un dossier ancien avec les bonnes règles.
alter table public.dossiers
    add column if not exists demarche_version integer;

comment on column public.dossiers.demarche_version is
    'Version de la démarche en vigueur au moment du dépôt. Null pour les dossiers antérieurs '
    'à la migration 019 (avant tout versionnement).';

-- ----------------------------------------------------------------------------
-- Publication initiale : l'état actuel devient la version 1.
--
-- Sans cet instantané, les dialogues en cours demanderaient une version qui
-- n'existe pas, et retomberaient sur la définition vivante — donc exactement
-- le problème qu'on corrige.
-- ----------------------------------------------------------------------------

insert into public.demarche_versions (type_demarche, version, publiee_par, contenu)
select
    d.type_demarche,
    d.version,
    'migration_019',
    jsonb_build_object(
        'definition', to_jsonb(d),
        'champs', coalesce((
            select jsonb_agg(to_jsonb(c) order by c.ordre)
            from public.demarche_champs c where c.type_demarche = d.type_demarche), '[]'::jsonb),
        'documents', coalesce((
            select jsonb_agg(to_jsonb(x) order by x.ordre)
            from public.demarche_documents x where x.type_demarche = d.type_demarche), '[]'::jsonb),
        'regles', coalesce((
            select jsonb_agg(to_jsonb(r) order by r.ordre)
            from public.demarche_regles r where r.type_demarche = d.type_demarche), '[]'::jsonb),
        'cas', coalesce((
            select jsonb_agg(to_jsonb(k) order by k.ordre)
            from public.demarche_cas k where k.type_demarche = d.type_demarche), '[]'::jsonb)
    )
from public.demarche_definitions d
on conflict (type_demarche, version) do nothing;

-- Les dossiers déjà déposés gardent `demarche_version` à null : prétendre
-- qu'ils relèvent de la version 1 serait une affirmation fausse, puisqu'ils
-- ont été constitués avant tout versionnement.

-- Pas de RLS : table de configuration, lue par le backend (service role).
