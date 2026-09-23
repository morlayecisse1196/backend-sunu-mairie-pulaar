-- ============================================================================
-- Migration 010 — Historique des conversations (mobile, "revoir mes anciennes
-- conversations" façon Claude web) + support du replay audio à la demande.
--
-- Contexte : jusqu'ici, `sessions`/`dossier_sessions` (main.py) ne vivent
-- QU'EN MÉMOIRE process — perdues au redémarrage du serveur, jamais
-- consultables après coup. Ces deux tables persistent réellement chaque tour
-- de dialogue (les deux modes, information ET administratif).
--
-- Choix : ne PAS stocker l'audio synthétisé lui-même (gros volume, redondant)
-- — seul le texte (FR + Pulaar) est conservé ; l'audio d'un message passé est
-- resynthétisé à la demande via le même tts_service que get_demarche_audio/
-- get_dossier_audio (déjà en place, même principe de cache disque).
-- ============================================================================

create table if not exists public.conversations (
    id           uuid primary key default gen_random_uuid(),
    citoyen_id   uuid not null references public.profiles(id) on delete cascade,
    session_id   text not null unique,
    mode         text not null check (mode in ('information', 'administratif')),
    dossier_id   uuid references public.dossiers(id) on delete set null,
    titre        text,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);

create index if not exists idx_conversations_citoyen on public.conversations(citoyen_id, updated_at desc);

create table if not exists public.messages (
    id               uuid primary key default gen_random_uuid(),
    conversation_id  uuid not null references public.conversations(id) on delete cascade,
    role             text not null check (role in ('user', 'assistant')),
    contenu_fr       text not null,
    contenu_pulaar   text,
    created_at       timestamptz not null default now()
);

create index if not exists idx_messages_conversation on public.messages(conversation_id, created_at);

-- Pas de RLS : accès exclusivement via le backend (service role) — même
-- principe que dossiers/documents/cas_particuliers (cf. 001_dossiers.sql,
-- note finale). Les endpoints REST vérifient eux-mêmes que
-- conversations.citoyen_id correspond à l'utilisateur connecté.
