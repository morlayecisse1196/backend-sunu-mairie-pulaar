-- ============================================================================
-- Migration 030 — L'agent nomme la démarche avant de la commencer
-- Réf. : PLAN_MAITRE.md, étape 5 (correctifs de la bascule)
--
-- Jusqu'ici, la phrase qui propose de commencer une démarche était écrite
-- librement par le modèle, à chaque conversation. Trois conséquences :
--
--   * elle ne nommait pas forcément la démarche, au moment précis où le
--     citoyen s'engage et où un dossier réel va être créé ;
--   * elle repassait par le traducteur à chaque fois, donc jamais relue,
--     jamais pré-générée en audio ;
--   * rien ne permettait au citoyen de dire « non, ce n'est pas ça ».
--
-- Ces deux phrases sont fixes. Elles portent un trou `{demarche}` (ou
-- `{demarches}`) rempli par le code : le pulaar DOIT le garder tel quel,
-- sinon la phrase ne peut pas être dite et repart au traducteur.
--
-- Le pulaar ci-dessous est un BROUILLON, non validé (comme la migration 029).
-- ============================================================================

insert into public.phrases_systeme (cle, francais, pulaar, contexte) values
    ('bascule_confirmation',
     'Je vais vous aider pour : {demarche}. Voulez-vous que nous commencions maintenant ? Dites oui, ou non.',
     'Mi wallay ma e : {demarche}. Aɗa yiɗi en fuɗɗoo jooni? Wi''am eey, walla alaa.',
     'Dite juste avant de commencer une démarche, quand le citoyen s''engage et qu''un dossier va '
     'être créé. ⚠️ Gardez le trou {demarche} tel quel : il est remplacé par le nom de la démarche.'),
    ('bascule_demarche_inconnue',
     'Je n''ai pas compris quelle démarche vous voulez faire. Je peux vous aider pour : {demarches}. Laquelle voulez-vous ?',
     'Mi faamaani golle honɗe njiɗ-ɗaa waɗde. Mi waawi wallude ma e : {demarches}. Ko honnde njiɗ-ɗaa?',
     'Dite quand l''agent propose de commencer, mais qu''aucune démarche connue n''est reconnue. '
     '⚠️ Gardez le trou {demarches} tel quel : il est remplacé par la liste des démarches.')
on conflict (cle) do nothing;
