-- ============================================================================
-- Migration 032 — Un seul vecteur par fiche d'information
--
-- `demarches_embeddings` n'avait qu'une clé primaire technique (`id`) : rien
-- n'empêchait deux vecteurs pour la même fiche, et le script de génération
-- (`seed_embeddings.py`) échouait sur « there is no unique or exclusion
-- constraint matching the ON CONFLICT specification » — donc AUCUN vecteur
-- n'était écrit, et la recherche sémantique ne trouvait jamais rien.
--
-- Les doublons éventuels sont retirés d'abord : on garde le plus récent.
-- ============================================================================

delete from public.demarches_embeddings e
using public.demarches_embeddings plus_recent
where e.demarche_id = plus_recent.demarche_id
  and e.created_at < plus_recent.created_at;

alter table public.demarches_embeddings
    drop constraint if exists demarches_embeddings_demarche_id_key;

alter table public.demarches_embeddings
    add constraint demarches_embeddings_demarche_id_key unique (demarche_id);
