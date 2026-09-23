-- ============================================================================
-- Migration 024 — Une relecture par phrase, pas par ligne
-- Réf. : backend-agent/PLAN_MAITRE.md, étape 4.2
--
-- CE QUI NE VA PAS
--
-- `pulaar_valide` est UN booléen par ligne. Or une ligne de `demarche_champs`
-- porte plusieurs phrases : la question, et ses relances. Valider la question
-- marque donc les relances comme relues, et réciproquement.
--
-- Tant que la relecture se faisait par fichier entier, ça ne se voyait pas :
-- tout était validé d'un coup. Dès que l'atelier web permet de valider une
-- phrase à la fois, le bouton fait plus que ce qu'il annonce — et une relance
-- jamais lue par personne se met à être DITE au citoyen, ce que toute
-- l'étape 3 existe pour empêcher.
--
-- LA RÉPONSE
--
-- Un drapeau par rang, en face de chaque tableau de traductions. Même forme
-- que `relances_pulaar` : le rang N du texte a le rang N du drapeau.
--
-- REPLI
--
-- Un tableau VIDE signifie « rien de décidé par phrase » et laisse
-- `pulaar_valide` décider, comme avant. Les lignes existantes gardent donc
-- exactement le comportement d'aujourd'hui, et la granularité n'apparaît
-- qu'au fur et à mesure des relectures. Aucune phrase ne devient dite du seul
-- fait de cette migration.
-- ============================================================================

alter table public.demarche_champs
    add column if not exists relances_pulaar_valide boolean[] not null default '{}';

alter table public.demarche_documents
    add column if not exists messages_rappel_pulaar_valide boolean[] not null default '{}';

comment on column public.demarche_champs.relances_pulaar_valide is
    'Relecture rang par rang, en face de `relances_pulaar`. Tableau vide = rien de decide '
    'par phrase, `pulaar_valide` decide alors pour toute la ligne (comportement d''avant).';
comment on column public.demarche_documents.messages_rappel_pulaar_valide is
    'Relecture rang par rang, en face de `messages_rappel_pulaar`. Tableau vide = repli sur '
    '`pulaar_valide`.';

-- Volontairement AUCUN remplissage initial. Pré-remplir avec la valeur de
-- `pulaar_valide` reviendrait à affirmer que chaque relance a été relue
-- individuellement, ce que personne n'a fait. Le tableau vide dit la vérité :
-- on ne sait pas encore, au rang près.
