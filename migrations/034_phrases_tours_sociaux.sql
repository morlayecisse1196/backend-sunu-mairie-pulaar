-- ============================================================================
-- Migration 034 — L'agent sait répondre à « bonjour »
--
-- LE PROBLÈME
--
-- En mode administratif, TOUT message partait au modèle ciblé sur le champ en
-- cours. Ce qui n'y répondait pas était compté comme un échec. Mesuré sur le
-- vrai modèle, quatre messages sur quatre :
--
--     « Bonjour »            -> « Je n'ai pas compris. Quel âge a votre enfant ? »
--     « Salaam alaikum »     -> « Je n'ai pas compris. … »
--     « Merci »              -> « Je n'ai pas compris. … »
--     « Attends un instant » -> « Je n'ai pas compris. … »
--
-- Et chaque échec incrémente un compteur : au troisième, le champ est
-- abandonné et un cas particulier s'ouvre. Dire « bonjour, merci, attends »
-- suffisait à saboter sa propre demande.
--
-- LA RÉPONSE
--
-- Un tri déterministe (services/tours_sociaux.py) reconnaît ces tours AVANT
-- le modèle. Ils reçoivent leur propre phrase, la question est reposée, et
-- aucun compteur ne bouge.
--
-- Ces phrases sont fixes, donc relisibles en pulaar une fois pour toutes,
-- comme les relances. Elles sont dites À VOIX HAUTE juste avant la question :
-- d'où leur brièveté, qui n'est pas de la sécheresse mais du respect du temps
-- de quelqu'un qui écoute.
--
-- `pulaar` reste NULL et `pulaar_valide` à false : tant qu'un locuteur n'a pas
-- relu, le français repart au traducteur, comme pour toute phrase du projet.
-- ============================================================================

insert into public.phrases_systeme (cle, francais, contexte) values
    ('social_salutation', 'Bonjour !',
     'Dite quand le citoyen salue au milieu de la collecte. La question du champ est reposée juste après : garder très court.'),
    ('social_remerciement', 'Je vous en prie.',
     'Dite quand le citoyen remercie au milieu de la collecte. La question du champ est reposée juste après : garder très court.'),
    ('social_patience', 'D''accord, prenez votre temps. Je vous écoute.',
     'Dite quand le citoyen demande d''attendre. La question n''est PAS reposée : il a demandé une pause.')
on conflict (cle) do nothing;

-- Vérification :
--   select cle, francais, pulaar_valide from public.phrases_systeme
--    where cle like 'social_%' order by cle;
