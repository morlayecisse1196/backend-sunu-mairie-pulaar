-- ============================================================================
-- Migration 003 — Corrections découvertes en construisant la bascule
-- information → administratif (Sprint B, Tâche B.3)
-- Réf. : MEMOIR2/SUNU_MAIRIE_PROMPTS.md
--
-- 1. commune_id nullable : au moment où le citoyen accepte de déposer un
--    dossier, la commune de naissance (slot `commune_naissance`, UC2 étape 1)
--    n'est pas encore connue — le Dossier doit pouvoir exister avant elle.
--    Résolue et renseignée dès que le slot est rempli.
-- 2. statut 'en_cours' ajouté : représente le dossier pendant le dialogue de
--    remplissage des slots, AVANT la relecture RG7 et la confirmation
--    (Tâche B.4) qui le fait passer à 'recu'. Absent du cycle de vie initial
--    du §3.1, qui supposait à tort un dossier déjà complet dès sa création.
-- ============================================================================

alter table public.dossiers
    alter column commune_id drop not null;

alter table public.dossiers
    drop constraint if exists dossiers_statut_check;

alter table public.dossiers
    add constraint dossiers_statut_check
    check (statut in (
        'en_cours', 'recu', 'en_traitement', 'genere',
        'en_attente_validation_citoyen', 'finalise',
        'corrections_demandees'
    ));
