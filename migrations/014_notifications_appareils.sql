-- ============================================================================
-- 014 — Notifications (web + mobile) et appareils (jetons FCM)
--
-- Avant : l'agent vocal promettait « Je vous préviendrai dès que votre extrait
-- sera prêt », mais aucun mécanisme n'existait ; les consultants découvraient
-- les nouveaux dossiers en rafraîchissant leur liste.
--
--   * notifications : une ligne par destinataire, créée à chaque transition de
--     statut significative (services/notifications.py).
--   * appareils : jetons Firebase Cloud Messaging des téléphones, pour les
--     notifications push quand l'application est fermée. Un jeton appartient à
--     un seul utilisateur à la fois (réattribué si un autre compte se connecte
--     sur le même téléphone).
-- Accès exclusif via le backend (RLS sans politique).
-- ============================================================================

create table if not exists public.notifications (
    id               uuid primary key default gen_random_uuid(),
    destinataire_id  uuid not null references public.profiles(id) on delete cascade,
    type             text not null,
    titre            text not null,
    message          text,
    lien             text,
    dossier_id       uuid references public.dossiers(id) on delete cascade,
    lu               boolean not null default false,
    cree_le          timestamptz not null default now()
);
create index if not exists idx_notifications_destinataire
    on public.notifications(destinataire_id, lu, cree_le desc);
alter table public.notifications enable row level security;

create table if not exists public.appareils (
    id                     uuid primary key default gen_random_uuid(),
    utilisateur_id         uuid not null references public.profiles(id) on delete cascade,
    jeton_fcm              text not null unique,
    plateforme             text not null check (plateforme in ('android', 'ios', 'web')),
    langue                 text,
    cree_le                timestamptz not null default now(),
    derniere_utilisation   timestamptz not null default now()
);
create index if not exists idx_appareils_utilisateur on public.appareils(utilisateur_id);
alter table public.appareils enable row level security;
