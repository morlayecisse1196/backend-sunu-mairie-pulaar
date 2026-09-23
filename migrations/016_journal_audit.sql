-- ============================================================================
-- 016 — Journal d'audit (traçabilité des actions sensibles)
--
-- Comptes consultants, communes, tampons numériques, modèles de documents,
-- reprises de dossiers bloqués, consultations administratives de dossiers :
-- qui a fait quoi, quand, sur quoi.
--
-- Journal en AJOUT SEUL : aucune route ne modifie ni ne supprime une entrée,
-- et les droits de modification/suppression sont révoqués côté base.
-- ============================================================================

create table if not exists public.journal_audit (
    id             uuid primary key default gen_random_uuid(),
    acteur_id      uuid references public.profiles(id) on delete set null,
    acteur_email   text,
    acteur_role    text,
    action         text not null,
    cible_type     text check (cible_type is null or cible_type in ('dossier', 'commune', 'consultant', 'template', 'compte')),
    cible_id       uuid,
    cible_libelle  text,
    details        jsonb,
    ip             text,
    agent          text,
    cree_le        timestamptz not null default now()
);

create index if not exists idx_journal_audit_date on public.journal_audit(cree_le desc);
create index if not exists idx_journal_audit_action on public.journal_audit(action, cree_le desc);
create index if not exists idx_journal_audit_acteur on public.journal_audit(acteur_id, cree_le desc);

alter table public.journal_audit enable row level security;
revoke update, delete on public.journal_audit from anon, authenticated;
