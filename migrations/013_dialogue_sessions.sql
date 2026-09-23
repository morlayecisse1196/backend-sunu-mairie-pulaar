-- ============================================================================
-- 013 — Sessions de dialogue persistées (temps réel mobile)
--
-- Avant : l'état du dialogue (mode, phase RG7, slots, documents demandés,
-- compteurs…) vivait uniquement dans la mémoire du processus (dict
-- `dossier_sessions` de main.py) :
--   * perdu à chaque redémarrage du serveur, en plein dialogue ;
--   * jamais purgé (fuite mémoire) ;
--   * aucune propriété : n'importe quel utilisateur connecté pouvait rejoindre
--     la session d'un autre en connaissant son identifiant ;
--   * une démarche terminée bloquait la session pour toujours (« votre
--     demande a déjà été envoyée »), l'app gardant le même identifiant.
--
-- Modèle :
--   * `cle_client` : identifiant fourni par l'app (WS v1) — plusieurs sessions
--     successives peuvent partager la même clé, mais UNE SEULE active à la fois.
--   * une session appartient à UN citoyen ; une clé déjà utilisée par un autre
--     citoyen est refusée par le backend.
--   * `etat` : état complet du moteur (JSON), `mode/phase/dossier_id` en
--     colonnes pour les requêtes (relance après upload, supervision).
--   * `conversations.session_id` = `dialogue_sessions.id` pour les nouvelles
--     conversations.
-- ============================================================================

create table if not exists public.dialogue_sessions (
    id               uuid primary key default gen_random_uuid(),
    cle_client       text not null,
    citoyen_id       uuid not null references public.profiles(id) on delete cascade,
    conversation_id  uuid references public.conversations(id) on delete set null,
    dossier_id       uuid references public.dossiers(id) on delete set null,
    type_demarche    text not null default 'extrait_naissance',
    mode             text not null default 'information'
        check (mode in ('information', 'administratif')),
    phase            text not null default 'collecte'
        check (phase in ('collecte', 'relecture_en_cours', 'termine', 'bloque')),
    statut           text not null default 'active'
        check (statut in ('active', 'close')),
    etat             jsonb not null default '{}'::jsonb,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    close_le         timestamptz
);

create unique index if not exists uniq_dialogue_sessions_cle_active
    on public.dialogue_sessions(cle_client) where statut = 'active';
create index if not exists idx_dialogue_sessions_citoyen
    on public.dialogue_sessions(citoyen_id, updated_at desc);
create index if not exists idx_dialogue_sessions_dossier
    on public.dialogue_sessions(dossier_id) where dossier_id is not null;
create index if not exists idx_dialogue_sessions_cle
    on public.dialogue_sessions(cle_client);

alter table public.dialogue_sessions enable row level security;
