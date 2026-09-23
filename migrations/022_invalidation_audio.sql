-- ============================================================================
-- Migration 022 — L'audio pré-généré ne survit jamais au texte qu'il dit
-- Réf. : backend-agent/PLAN_MAITRE.md, étape 3.4
--
-- CE QUI SERT LE CITOYEN
--
-- Le fichier audio est retrouvé par l'EMPREINTE du texte pulaar
-- (`services/catalogue_audio.cle_phrase`), pas par ces colonnes. Corriger une
-- lettre change l'empreinte : l'ancien fichier n'est plus jamais trouvé, et la
-- phrase repart à la synthèse. L'invalidation est donc acquise par
-- construction, sans rien à effacer et sans course possible.
--
-- À QUOI SERVENT CES COLONNES, ALORS
--
-- À l'atelier de relecture (étape 4.2) : « cette phrase a-t-elle déjà son
-- audio, ou le prochain citoyen attendra-t-il la synthèse ? ». Une colonne qui
-- garderait la clé d'un texte corrigé répondrait « oui » à tort, et personne
-- ne saurait qu'il reste du travail. Les déclencheurs ci-dessous les remettent
-- à NULL dès que le texte pulaar change — ce que promettait déjà le
-- commentaire de la migration 018.
--
-- Le texte FRANÇAIS ne déclenche rien : ce n'est pas lui qui est synthétisé.
-- Un français retouché sans toucher au pulaar ne change pas ce qui est dit.
-- ============================================================================

create or replace function public.oublier_audio_perime()
returns trigger
language plpgsql
as $$
begin
    if tg_argv[0] = 'phrases_systeme' then
        if new.pulaar is distinct from old.pulaar then
            new.audio := null;
        end if;
    elsif tg_argv[0] = 'demarche_champs' then
        if new.question_pulaar is distinct from old.question_pulaar then
            new.question_audio := null;
        end if;
    elsif tg_argv[0] = 'demarche_documents' then
        if new.message_demande_pulaar is distinct from old.message_demande_pulaar then
            new.message_audio := null;
        end if;
    end if;
    return new;
end;
$$;

comment on function public.oublier_audio_perime() is
    'Remet à NULL la clé d''audio quand le texte pulaar change. Indicateur de relecture : '
    'ce qui est réellement servi au citoyen est retrouvé par empreinte du texte.';

drop trigger if exists audio_perime on public.phrases_systeme;
create trigger audio_perime
    before update on public.phrases_systeme
    for each row execute function public.oublier_audio_perime('phrases_systeme');

drop trigger if exists audio_perime on public.demarche_champs;
create trigger audio_perime
    before update on public.demarche_champs
    for each row execute function public.oublier_audio_perime('demarche_champs');

drop trigger if exists audio_perime on public.demarche_documents;
create trigger audio_perime
    before update on public.demarche_documents
    for each row execute function public.oublier_audio_perime('demarche_documents');

-- Les RELANCES (`demarche_champs.relances_pulaar`, tableau) n'ont pas de
-- colonne d'audio et n'en ont pas besoin : une clé par empreinte se calcule
-- pour chaque variante sans rien stocker. C'est un avantage de ce choix, pas
-- un oubli — une colonne `relances_audio text[]` obligerait à maintenir
-- l'alignement des deux tableaux à chaque ajout de variante.

-- Les GABARITS (migration 021) n'ont jamais d'audio : leur texte final dépend
-- du dossier du citoyen, il ne peut pas être pré-généré.
