-- ============================================================================
-- 012 — Espace web v3 + historique des dossiers
--
--   * profiles : identité et préférences (web consultant/admin, mobile citoyen),
--     drapeau « mot de passe temporaire à changer ».
--   * dossiers.motif_blocage : origine d'un blocage (supervision admin).
--   * templates : actif / date de mise à jour.
--   * notes_internes : notes entre agents, jamais visibles par le citoyen.
--   * dossier_evenements : historique du cycle de vie (qui, quoi, quand).
--   * proteger_profil() étendu : un utilisateur ne peut pas lever lui-même
--     l'obligation de changer son mot de passe temporaire.
-- Toutes les tables sont en RLS sans politique : accès exclusif via le backend.
-- ============================================================================

alter table public.profiles
    add column if not exists nom_complet               text,
    add column if not exists telephone                 text,
    add column if not exists fonction                  text,
    add column if not exists langue_preferee           text,
    add column if not exists preferences               jsonb   not null default '{}'::jsonb,
    add column if not exists doit_changer_mot_de_passe boolean not null default false,
    add column if not exists derniere_connexion_vue    timestamptz;

alter table public.profiles drop constraint if exists profiles_langue_preferee_check;
alter table public.profiles
    add constraint profiles_langue_preferee_check
    check (langue_preferee is null or langue_preferee in ('pulaar', 'francais'));

alter table public.dossiers
    add column if not exists motif_blocage text;
alter table public.dossiers drop constraint if exists dossiers_motif_blocage_check;
alter table public.dossiers
    add constraint dossiers_motif_blocage_check
    check (motif_blocage is null or motif_blocage in ('relecture_rg7', 'corrections_post_generation'));

alter table public.templates
    add column if not exists actif         boolean     not null default true,
    add column if not exists mis_a_jour_le timestamptz not null default now();

create table if not exists public.notes_internes (
    id          uuid primary key default gen_random_uuid(),
    dossier_id  uuid not null references public.dossiers(id) on delete cascade,
    auteur_id   uuid not null references public.profiles(id),
    texte       text not null check (char_length(texte) between 1 and 2000),
    cree_le     timestamptz not null default now()
);
create index if not exists idx_notes_internes_dossier on public.notes_internes(dossier_id, cree_le desc);
alter table public.notes_internes enable row level security;

create table if not exists public.dossier_evenements (
    id           uuid primary key default gen_random_uuid(),
    dossier_id   uuid not null references public.dossiers(id) on delete cascade,
    type         text not null,
    libelle      text not null,
    acteur_type  text not null check (acteur_type in ('citoyen', 'consultant', 'admin', 'systeme')),
    acteur_id    uuid references public.profiles(id) on delete set null,
    statut_avant text,
    statut_apres text,
    details      jsonb,
    cree_le      timestamptz not null default now()
);
create index if not exists idx_dossier_evenements_dossier on public.dossier_evenements(dossier_id, cree_le);
create index if not exists idx_dossier_evenements_date on public.dossier_evenements(cree_le);
alter table public.dossier_evenements enable row level security;

-- Trigger de protection (reprend 011 et ajoute doit_changer_mot_de_passe).
create or replace function public.proteger_profil()
returns trigger
language plpgsql
as $$
declare
    appel_serveur boolean :=
        coalesce(auth.role(), '') = 'service_role'
        or current_user in ('postgres', 'supabase_admin', 'service_role', 'supabase_auth_admin');
begin
    if appel_serveur then
        return new;
    end if;

    if tg_op = 'INSERT' then
        new.role := 'citoyen';
        new.doit_changer_mot_de_passe := false;
        return new;
    end if;

    if new.role is distinct from old.role then
        raise exception 'Le rôle d''un profil ne peut être modifié que par l''administration.'
            using errcode = '42501';
    end if;

    if old.role in ('consultant', 'admin') and new.commune is distinct from old.commune then
        raise exception 'La commune d''un agent ne peut être modifiée que par l''administration.'
            using errcode = '42501';
    end if;

    if new.doit_changer_mot_de_passe is distinct from old.doit_changer_mot_de_passe then
        raise exception 'Ce drapeau est géré par le serveur après un vrai changement de mot de passe.'
            using errcode = '42501';
    end if;

    return new;
end;
$$;
