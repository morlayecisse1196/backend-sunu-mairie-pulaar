-- ============================================================================
-- Migration 035 — « Je vous ai entendu, mais j'ai d'abord besoin de la photo »
--
-- LE PROBLÈME
--
-- Pendant l'attente d'une pièce, TOUT ce que disait le citoyen était écarté en
-- silence. Observé en jouant le dialogue de bout en bout : à la question d'une
-- photo, le citoyen répond « Ibrahima Diallo » — et l'agent se contente de
-- redemander la photo. Aucun accusé, aucun signe qu'on l'a écouté. Le nom est
-- tombé dans le vide, et le citoyen croit avoir été entendu.
--
-- CE QU'ON NE FAIT PAS
--
-- Extraire une valeur de ce message. Le dialogue traite une information à la
-- fois (tâche J.3 : le modèle ne voit qu'un seul champ), et deviner à quel
-- champ ce message répondrait reviendrait sur cette discipline — au risque
-- d'écrire un nom d'enfant dans la case du déclarant.
--
-- On dit seulement qu'on a entendu, et que la photo vient d'abord.
--
-- `pulaar` reste NULL et `pulaar_valide` à false : tant qu'un locuteur n'a pas
-- relu, le français repart au traducteur, comme pour toute phrase du projet.
-- ============================================================================

insert into public.phrases_systeme (cle, francais, contexte) values
    ('document_message_entendu',
     'Je vous ai bien entendu, mais j''ai d''abord besoin de la photo.',
     'Dite quand le citoyen parle alors qu''une pièce est attendue. La demande de photo suit immédiatement : garder très court.')
on conflict (cle) do nothing;

-- Vérification :
--   select cle, francais, pulaar_valide from public.phrases_systeme
--    where cle = 'document_message_entendu';
