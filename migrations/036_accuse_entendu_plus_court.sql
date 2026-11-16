-- ============================================================================
-- Migration 036 — L'accusé de réception faisait doublon
--
-- La migration 035 a introduit « Je vous ai bien entendu, mais j'ai d'abord
-- besoin de la photo. » Cette phrase précède IMMÉDIATEMENT le rappel de la
-- pièce, qui dit déjà ce qu'il faut envoyer. Entendu à voix haute, cela
-- donnait :
--
--     « Je vous ai bien entendu, mais j'ai d'abord besoin de la photo.
--       Je n'ai pas encore reçu la photo du certificat de naissance.
--       Dès que vous êtes prêt, appuyez sur le bouton photo… »
--
-- Trois fois la photo. L'accusé n'a qu'un seul travail : dire qu'on a écouté.
-- Le rappel qui suit s'occupe du reste.
--
-- Correction dans une NOUVELLE migration, jamais en modifiant la 035 : un
-- fichier déjà appliqué qui change fait diverger la base du dépôt en silence
-- (cf. l'en-tête de scripts/migrer.py).
-- ============================================================================

update public.phrases_systeme
   set francais = 'Je vous ai bien entendu.',
       -- Le pulaar éventuellement saisi portait sur l'ancienne phrase : il ne
       -- vaut plus. On le retire plutôt que de laisser dire autre chose que
       -- ce que le français annonce.
       pulaar = null,
       pulaar_valide = false
 where cle = 'document_message_entendu';

-- Vérification :
--   select cle, francais, pulaar_valide from public.phrases_systeme
--    where cle = 'document_message_entendu';
