-- ============================================================================
-- 015 — Coordonnées des communes (inscription sans lecture)
--
-- Un citoyen qui ne lit pas ne peut pas retrouver sa commune dans une liste
-- déroulante. Avec les coordonnées, l'application propose les communes les
-- plus proches de sa position (GET /communes/proche), qu'il n'a plus qu'à
-- confirmer à l'oral.
--
-- Les coordonnées sont à renseigner commune par commune (aucune valeur
-- inventée ici : une commune sans coordonnées n'est simplement jamais
-- proposée par la recherche de proximité).
-- ============================================================================

alter table public.communes
    add column if not exists latitude  double precision,
    add column if not exists longitude double precision;

alter table public.communes drop constraint if exists communes_latitude_check;
alter table public.communes
    add constraint communes_latitude_check
    check (latitude is null or (latitude between -90 and 90));

alter table public.communes drop constraint if exists communes_longitude_check;
alter table public.communes
    add constraint communes_longitude_check
    check (longitude is null or (longitude between -180 and 180));

-- Exemple de renseignement (à compléter avec les vraies coordonnées) :
--   update public.communes set latitude = 16.2761, longitude = -16.1372 where nom = 'Ross-Béthio';
