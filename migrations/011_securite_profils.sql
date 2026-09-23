-- ============================================================================
-- 011 — Protection de la table `profiles` (revue de sécurité du 2026-09-14)
--
-- Problème : le rôle (citoyen | consultant | admin) est lu dans `profiles`
-- par le backend (auth.py), et l'application mobile écrivait directement dans
-- cette table avec le jeton du citoyen (upsert de la commune à l'inscription).
-- Sans restriction, un citoyen pouvait s'attribuer role='admin', et un
-- consultant changer sa propre commune pour lire les dossiers d'une autre
-- mairie.
--
-- Correctif :
--   1. RLS « propriétaire » : chacun ne lit/écrit que sa propre ligne.
--   2. Trigger : hors service_role (backend), le rôle n'est jamais modifiable,
--      une insertion directe est toujours forcée à 'citoyen', et la commune
--      d'un agent (consultant/admin) n'est modifiable que par le backend.
-- Le backend (clé service_role) n'est pas concerné par RLS ni par le trigger.
-- ============================================================================

alter table public.profiles enable row level security;

drop policy if exists profiles_lecture_proprietaire on public.profiles;
create policy profiles_lecture_proprietaire on public.profiles
    for select using (id = auth.uid());

drop policy if exists profiles_insertion_proprietaire on public.profiles;
create policy profiles_insertion_proprietaire on public.profiles
    for insert with check (id = auth.uid());

drop policy if exists profiles_maj_proprietaire on public.profiles;
create policy profiles_maj_proprietaire on public.profiles
    for update using (id = auth.uid()) with check (id = auth.uid());

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

    return new;
end;
$$;

drop trigger if exists trg_proteger_profil on public.profiles;
create trigger trg_proteger_profil
    before insert or update on public.profiles
    for each row execute function public.proteger_profil();

-- Vérification après application (doit renvoyer une erreur 42501 si exécuté
-- avec le jeton d'un citoyen via l'API REST Supabase) :
--   update profiles set role = 'admin' where id = auth.uid();
