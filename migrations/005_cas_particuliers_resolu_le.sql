-- ============================================================================
-- Migration 005 — cas_particuliers.resolu_le
-- Réf. : MEMOIR2/SUNU_MAIRIE_PROMPTS.md, Sprint E, Tâche E.3.
--
-- `horodatage` (posé en 001_dossiers.sql, default now()) capture la création
-- du cas particulier. Le critère de validation de E.3 demande explicitement
-- de vérifier la traçabilité par horodatage de la RÉSOLUTION (DSF §6,
-- exigence non-fonctionnelle) — un cas peut être créé puis résolu bien plus
-- tard, les deux instants comptent pour l'audit. Colonne nullable : NULL tant
-- que non résolu.
-- ============================================================================

alter table public.cas_particuliers
    add column if not exists resolu_le timestamptz;
