-- ============================================================================
-- Migration 002 — documents.type en texte libre (retrait du CHECK)
-- Réf. : MEMOIR2/SUNU_MAIRIE_PROMPTS.md, discussion post-Sprint A / avant B.2
--
-- Contexte : le CHECK posé dans 001_dossiers.sql sur documents.type ne
-- listait que les 5 types de pièces nécessaires à l'extrait de naissance
-- (démarche pilote). Décision : garder l'architecture ouverte à une future
-- démarche sans migration à chaque fois — la validation des valeurs
-- attendues se fait désormais côté FastAPI (Sprint B/D), pas en base.
-- Périmètre du projet lui-même inchangé : on reste sur l'extrait de
-- naissance comme seule démarche réellement construite pour l'instant.
-- ============================================================================

alter table public.documents
    drop constraint if exists documents_type_check;
