-- ============================================================================
-- Migration 006 — Journal des confirmations de tampon numérique
-- Réf. : MEMOIR2/SUNU_MAIRIE_PROMPTS.md §5.4, Sprint G, Tâche G.1
--
-- `communes.tampon_numerique_url` (déjà présent depuis 001_dossiers.sql) ne
-- garde que le tampon ACTUELLEMENT actif d'une commune. Cette table journalise
-- CHAQUE confirmation d'enregistrement (append-only, jamais mis à jour ni
-- supprimé) : qui a confirmé être autorisé, pour quelle commune, quand — la
-- traçabilité explicitement demandée par le critère de validation de G.1,
-- même mécanique que cas_particuliers/remarques (journal, pas juste un champ
-- écrasé à chaque upload).
-- ============================================================================

create table if not exists public.tampon_confirmations (
    id            uuid primary key default gen_random_uuid(),
    commune_id    uuid not null references public.communes(id) on delete cascade,
    admin_id      uuid not null references public.profiles(id),
    fichier_url   text not null,
    confirme_le   timestamptz not null default now()
);

create index if not exists idx_tampon_confirmations_commune_id on public.tampon_confirmations(commune_id);

-- Pas de RLS : accès exclusivement via le backend (service role, get_current_admin),
-- même principe que cas_particuliers/remarques/communes (cf. 001_dossiers.sql, note finale).
