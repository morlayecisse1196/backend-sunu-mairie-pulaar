-- ============================================================================
-- Migration 004 — Ajout du statut 'bloque' (dossiers)
-- Réf. : MEMOIR2/SUNU_MAIRIE_PROMPTS.md §1, décision Q3/Q5 (3 itérations
-- citoyen<->consultant sans résolution -> dossier bloqué, signalé à l'admin
-- via /admin/supervision, Sprint C Tâche C.4).
--
-- Absent du cycle de vie initial posé en 001_dossiers.sql (§3.1), qui ne
-- listait pas ce cas — trouvé en construisant l'endpoint de supervision qui
-- doit pouvoir le lire. Note : cette migration ne fait qu'AUTORISER la
-- valeur ; rien dans le code actuel ne la déclenche encore (la boucle de
-- correction à 3 itérations est Sprint D/E, pas construite à ce stade).
-- ============================================================================

alter table public.dossiers
    drop constraint if exists dossiers_statut_check;

alter table public.dossiers
    add constraint dossiers_statut_check
    check (statut in (
        'en_cours', 'recu', 'en_traitement', 'genere',
        'en_attente_validation_citoyen', 'finalise',
        'corrections_demandees', 'bloque'
    ));
