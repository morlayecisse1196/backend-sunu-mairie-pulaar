-- ============================================================================
-- Migration 023 — Historique de la relecture pulaar
-- Réf. : backend-agent/PLAN_MAITRE.md, étape 4.2
--
-- `pulaar_valide` dit qu'une phrase a été relue. Il ne dit ni PAR QUI, ni
-- QUAND, ni ce qu'elle disait avant. Trois mois plus tard, devant une
-- formulation contestée par un usager ou par un officier d'état civil, plus
-- personne ne peut répondre : est-ce qu'un locuteur l'a vraiment lue, ou
-- est-ce une traduction automatique validée à la hâte un soir de démonstration ?
--
-- Cette table répond. Une ligne par relecture, avec le texte d'avant. C'est
-- aussi ce qui permet de revenir en arrière quand une correction s'avère
-- moins bonne que ce qu'elle remplaçait.
-- ============================================================================

create table if not exists public.atelier_historique (
    id            bigserial primary key,
    identifiant   text not null,   -- ex. 'champ:nom_mere:question' — stable
    type_demarche text not null,
    pulaar_avant  text,            -- null : première traduction
    pulaar_apres  text not null,
    valide        boolean not null default false,
    par           text not null,
    le            timestamptz not null default now()
);

create index if not exists atelier_historique_phrase
    on public.atelier_historique (type_demarche, identifiant, le desc);

comment on table public.atelier_historique is
    'Qui a relu quoi, quand, et ce que la phrase disait avant. `pulaar_valide` seul ne '
    'distingue pas un locuteur d''une traduction automatique validée à la hâte.';
comment on column public.atelier_historique.identifiant is
    'Identifiant d''atelier (services/atelier.py), pas une clé étrangère : une phrase peut '
    'être supprimée d''une démarche sans que son historique doive disparaître avec elle.';
comment on column public.atelier_historique.pulaar_avant is
    'null quand c''est la première traduction de cette phrase.';

-- Pas de RLS : table d'administration, lue et écrite par le backend
-- (service role) derrière `get_current_admin`. Aucune donnée de citoyen n'y
-- figure — ce sont les phrases de l'agent, pas leurs réponses.
