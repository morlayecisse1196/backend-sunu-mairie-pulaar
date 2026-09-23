-- ============================================================================
-- Migration 008 — Règles de validation de date (DSL slot_controller.py)
-- Réf. : MEMOIR2/SUNU_MAIRIE_PROMPTS.md, Sprint J, Tâche J.2
--
-- La migration 007 a semé `regle_validation='date_iso_passee'` comme simple
-- placeholder pour les deux champs de type `date`. Tâche J.2 fixe le mini-DSL
-- réellement interprété par `slot_controller.valider_valeur()` :
--   - "passee"        -> la date ne doit pas être dans le futur
--   - "avant:<champ>" -> la date doit être strictement antérieure à celle du
--                        champ nommé (cohérence croisée, valeurs_connues)
-- (plusieurs règles combinables, séparées par "|" — cf. slot_controller.py).
--
-- Corrige ici la valeur de départ pour refléter ce DSL, notamment la
-- cohérence explicitement demandée par le critère de validation de J.2 :
-- la date de naissance de la mère doit être antérieure à celle de l'enfant.
-- ============================================================================

update public.demarche_champs
set regle_validation = 'passee'
where type_demarche = 'extrait_naissance' and nom_champ = 'date_naissance_enfant';

update public.demarche_champs
set regle_validation = 'passee|avant:date_naissance_enfant'
where type_demarche = 'extrait_naissance' and nom_champ = 'date_naissance_mere';
