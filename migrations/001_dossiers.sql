-- ============================================================================
-- Migration 001 — Modèle « dossier » (extension SUNU-MAIRIE)
-- Réf. : MEMOIR2/SUNU_MAIRIE_PROMPTS.md §3 (Sprint A, Tâche A.1)
--
-- À exécuter manuellement dans l'éditeur SQL Supabase (Dashboard > SQL Editor).
-- Pas d'outil de migration/ORM introduit ici : cohérent avec l'usage actuel du
-- client Supabase REST brut (supabase_client.py) dans le reste du backend.
--
-- Convention : `type_demarche` (dans `dossiers` et `templates`) est un slug
-- snake_case (ex. "extrait_naissance"), distinct de `demarches.nom_demarche`
-- qui est un libellé d'affichage (ex. "Extrait de naissance") utilisé par le
-- RAG informationnel existant (UC1, table `demarches` inchangée).
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 0. Extension nécessaire pour gen_random_uuid() (activée par défaut sur
--    Supabase, présente ici par prudence si jamais absente).
-- ----------------------------------------------------------------------------
create extension if not exists pgcrypto;

-- ----------------------------------------------------------------------------
-- 1. profiles.role — nouveau rôle (citoyen | consultant | admin)
--    Le champ `commune` existe déjà sur profiles et est réutilisé tel quel
--    pour scoper un consultant à sa commune (cf. §5.6) — pas de nouvelle
--    colonne pour ça ici.
-- ----------------------------------------------------------------------------
alter table public.profiles
    add column if not exists role text not null default 'citoyen';

alter table public.profiles
    drop constraint if exists profiles_role_check;

alter table public.profiles
    add constraint profiles_role_check
    check (role in ('citoyen', 'consultant', 'admin'));

-- ----------------------------------------------------------------------------
-- 2. communes — découpage administratif + tampon numérique (§5.4, V2)
-- ----------------------------------------------------------------------------
create table if not exists public.communes (
    id                    uuid primary key default gen_random_uuid(),
    nom                   text not null unique,
    region                text,
    departement           text,
    arrondissement        text,
    tampon_numerique_url  text,
    created_at            timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- 3. dossiers — pièce centrale du modèle « mode administratif »
-- ----------------------------------------------------------------------------
create table if not exists public.dossiers (
    id                        uuid primary key default gen_random_uuid(),
    citoyen_id                uuid not null references public.profiles(id) on delete cascade,
    commune_id                uuid not null references public.communes(id),
    type_demarche             text not null,
    cas_legal                 text
        check (cas_legal in ('dans_les_delais', 'tardif', 'jugement_requis')),
    statut                    text not null default 'recu'
        check (statut in (
            'recu', 'en_traitement', 'genere',
            'en_attente_validation_citoyen', 'finalise',
            'corrections_demandees'
        )),
    numero_suivi              text unique,
    slots                     jsonb not null default '{}'::jsonb,
    nb_iterations_correction  integer not null default 0,
    created_at                timestamptz not null default now(),
    updated_at                timestamptz not null default now()
);

create index if not exists idx_dossiers_citoyen_id on public.dossiers(citoyen_id);
create index if not exists idx_dossiers_commune_id on public.dossiers(commune_id);
create index if not exists idx_dossiers_statut on public.dossiers(statut);

-- ----------------------------------------------------------------------------
-- 4. documents — fichiers déposés (photo/dicté/différé) par type de pièce
--    Note : les valeurs autorisées pour `statut` ne sont pas encore figées au
--    moment de cette migration (précisées au fil du Sprint B) ; laissé en
--    texte libre pour éviter une migration ALTER supplémentaire plus tard.
--    Le CHECK ci-dessous sur `type` est volontairement retiré par la
--    migration 002_documents_type_texte_libre.sql (même raison, validation
--    déplacée côté FastAPI) — gardé ici tel qu'exécuté initialement, pour
--    l'historique.
-- ----------------------------------------------------------------------------
create table if not exists public.documents (
    id            uuid primary key default gen_random_uuid(),
    dossier_id    uuid not null references public.dossiers(id) on delete cascade,
    type          text not null
        check (type in (
            'certificat_naissance', 'cni_declarant', 'cni_conjoint',
            'livret_famille', 'certificat_mariage'
        )),
    fichier_url   text,
    mode          text
        check (mode in ('photo', 'dicte', 'differe')),
    statut        text not null default 'attendu',
    created_at    timestamptz not null default now()
);

create index if not exists idx_documents_dossier_id on public.documents(dossier_id);

-- ----------------------------------------------------------------------------
-- 5. document_formulaires — champs structurés extraits/saisis par document
--    document_id nullable : un formulaire peut exister avant qu'un fichier
--    physique ne soit rattaché (mode "dicté", ou saisie manuelle consultant).
-- ----------------------------------------------------------------------------
create table if not exists public.document_formulaires (
    id              uuid primary key default gen_random_uuid(),
    dossier_id      uuid not null references public.dossiers(id) on delete cascade,
    document_id     uuid references public.documents(id) on delete set null,
    type_document   text not null,
    champs          jsonb not null default '[]'::jsonb,
    statut          text not null default 'a_remplir'
        check (statut in ('a_remplir', 'rempli', 'verifie')),
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

create index if not exists idx_document_formulaires_dossier_id on public.document_formulaires(dossier_id);

-- ----------------------------------------------------------------------------
-- 6. documents_generes — PDF produits (versionnés) à partir du template
-- ----------------------------------------------------------------------------
create table if not exists public.documents_generes (
    id                uuid primary key default gen_random_uuid(),
    dossier_id        uuid not null references public.dossiers(id) on delete cascade,
    template_utilise  text not null,
    version           integer not null default 1,
    contenu_url       text,
    statut            text not null default 'genere'
        check (statut in (
            'genere', 'en_attente_validation_citoyen',
            'valide', 'corrections_demandees'
        )),
    date_generation   timestamptz not null default now()
);

create index if not exists idx_documents_generes_dossier_id on public.documents_generes(dossier_id);

-- ----------------------------------------------------------------------------
-- 7. remarques — retours citoyen/consultant sur un document généré
-- ----------------------------------------------------------------------------
create table if not exists public.remarques (
    id                   uuid primary key default gen_random_uuid(),
    dossier_id           uuid not null references public.dossiers(id) on delete cascade,
    document_genere_id   uuid references public.documents_generes(id) on delete cascade,
    champ_concerne       text,
    texte                text not null,
    source               text not null
        check (source in ('citoyen', 'consultant')),
    horodatage           timestamptz not null default now()
);

create index if not exists idx_remarques_dossier_id on public.remarques(dossier_id);

-- ----------------------------------------------------------------------------
-- 8. cas_particuliers — incidents remontés à l'assistant LLM du consultant
-- ----------------------------------------------------------------------------
create table if not exists public.cas_particuliers (
    id                   uuid primary key default gen_random_uuid(),
    dossier_id           uuid not null references public.dossiers(id) on delete cascade,
    type_incident        text not null,
    description_llm      text,
    options_proposees    jsonb not null default '[]'::jsonb,
    decision_consultant  text,
    horodatage           timestamptz not null default now()
);

create index if not exists idx_cas_particuliers_dossier_id on public.cas_particuliers(dossier_id);

-- ----------------------------------------------------------------------------
-- 9. templates — registre extensible des couples XSD/XML/HTML par démarche
-- ----------------------------------------------------------------------------
create table if not exists public.templates (
    type_demarche     text primary key,
    nom_fichier_xml   text not null,
    nom_fichier_html  text not null,
    version           integer not null default 1
);

-- ============================================================================
-- 10. Row Level Security — isolation citoyen uniquement.
--     Le filtrage consultant/commune reste applicatif (FastAPI), comme pour
--     `demarches` aujourd'hui — cf. §5.6. Le backend utilise la clé service
--     role (contourne RLS) ; ces policies protègent tout accès direct
--     Supabase fait avec le JWT d'un citoyen (web/mobile), si un jour introduit.
-- ============================================================================

alter table public.dossiers enable row level security;
alter table public.documents enable row level security;
alter table public.document_formulaires enable row level security;
alter table public.documents_generes enable row level security;

drop policy if exists dossiers_citoyen_own on public.dossiers;
create policy dossiers_citoyen_own on public.dossiers
    for all
    using (citoyen_id = auth.uid())
    with check (citoyen_id = auth.uid());

drop policy if exists documents_citoyen_own on public.documents;
create policy documents_citoyen_own on public.documents
    for all
    using (
        exists (
            select 1 from public.dossiers d
            where d.id = documents.dossier_id
            and d.citoyen_id = auth.uid()
        )
    )
    with check (
        exists (
            select 1 from public.dossiers d
            where d.id = documents.dossier_id
            and d.citoyen_id = auth.uid()
        )
    );

drop policy if exists document_formulaires_citoyen_own on public.document_formulaires;
create policy document_formulaires_citoyen_own on public.document_formulaires
    for all
    using (
        exists (
            select 1 from public.dossiers d
            where d.id = document_formulaires.dossier_id
            and d.citoyen_id = auth.uid()
        )
    )
    with check (
        exists (
            select 1 from public.dossiers d
            where d.id = document_formulaires.dossier_id
            and d.citoyen_id = auth.uid()
        )
    );

drop policy if exists documents_generes_citoyen_own on public.documents_generes;
create policy documents_generes_citoyen_own on public.documents_generes
    for all
    using (
        exists (
            select 1 from public.dossiers d
            where d.id = documents_generes.dossier_id
            and d.citoyen_id = auth.uid()
        )
    )
    with check (
        exists (
            select 1 from public.dossiers d
            where d.id = documents_generes.dossier_id
            and d.citoyen_id = auth.uid()
        )
    );

-- Pas de RLS sur `remarques`, `cas_particuliers`, `communes`, `templates` :
-- accès exclusivement via le backend (service role) dans tous les sprints
-- prévus — cf. §5.6. À revoir si un accès direct citoyen/consultant à ces
-- tables est introduit plus tard.
