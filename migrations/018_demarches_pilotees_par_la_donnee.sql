-- ============================================================================
-- Migration 018 — Ce qui restait figé dans le code passe en base
-- Réf. : backend-agent/PLAN_MAITRE.md, étapes 2.2 et 2.3
--
-- Après la migration 017, une démarche décrit ses champs, ses pièces et ses
-- règles. Il restait cinq choses écrites en dur dans le code, qui obligeaient
-- à modifier Python pour ajouter une démarche :
--
--   1. Les MESSAGES de demande de pièce (slot_controller.MESSAGES_DOCUMENT).
--   2. Les TYPES de documents acceptés (dialogue_engine.TYPES_DOCUMENT_VALIDES).
--   3. Les SLOTS INITIAUX (temps_reel.etat.SLOTS_VIDES_EXTRAIT_NAISSANCE).
--   4. La BASCULE en mode administratif (main.est_demarche_extrait_naissance,
--      qui cherchait littéralement le mot « naissance » dans le nom).
--   5. La règle des CAS LÉGAUX (dialogue_engine.determiner_cas_legal, seuils
--      de 30 et 365 jours codés en dur).
--
-- S'y ajoute (étape 2.2) ce qu'il faut pour le pulaar validé de l'étape 3 :
-- une colonne de texte pulaar et une clé d'audio pré-généré, partout où une
-- phrase est dite au citoyen.
--
-- COMPATIBILITÉ : le code garde un repli sur ses anciennes constantes quand la
-- base est injoignable, pour qu'une panne réseau ne rende pas le dialogue
-- impossible. Ce repli est un filet de sécurité, plus la source de vérité.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 2.2 — Pulaar validé et audio pré-généré
--
-- `*_pulaar` : la traduction relue par un locuteur, qui dispense d'appeler le
-- modèle (étape 3.3). `pulaar_valide` distingue une traduction relue d'une
-- traduction automatique déposée là en attendant.
-- `audio_*` : la clé du fichier pré-généré (services/catalogue_audio.py).
-- Remise à NULL dès que le texte change — sinon le citoyen entendrait
-- l'ancienne phrase.
-- ----------------------------------------------------------------------------

alter table public.demarche_champs
    add column if not exists question_pulaar text,
    add column if not exists question_audio  text,
    add column if not exists pulaar_valide   boolean not null default false;

alter table public.demarche_documents
    add column if not exists message_demande         text,
    add column if not exists messages_rappel         text[] not null default '{}',
    add column if not exists message_demande_pulaar  text,
    add column if not exists messages_rappel_pulaar  text[] not null default '{}',
    add column if not exists message_audio           text,
    add column if not exists pulaar_valide           boolean not null default false;

comment on column public.demarche_documents.messages_rappel is
    'Variantes de relance, utilisées à tour de rôle. Au moins deux : deux rappels consécutifs '
    'mot pour mot identiques donnent au citoyen l''impression de ne pas être entendu.';

-- ----------------------------------------------------------------------------
-- 1. Messages de demande de pièce — repris mot pour mot de
--    slot_controller.MESSAGES_DOCUMENT (vocabulaire volontairement concret :
--    « le côté avec votre photo dessus », pas « recto »).
-- ----------------------------------------------------------------------------

update public.demarche_documents set
    message_demande = 'Il me faut maintenant une photo du certificat de naissance ou d''accouchement qu''on vous a remis à l''hôpital ou à la maternité. Posez-le bien à plat, sans ombre dessus, et appuyez sur le bouton photo pour me l''envoyer.',
    messages_rappel = array[
        'Je n''ai pas encore reçu la photo du certificat de naissance. Dès que vous êtes prêt, appuyez sur le bouton photo, posez le papier bien à plat et envoyez-le.',
        'Toujours pas de certificat de naissance reçu de mon côté. Vous pouvez me l''envoyer en photo quand vous voulez, ou me dire simplement que vous ne l''avez pas.'
    ]
where type_document = 'certificat_naissance' and message_demande is null;

update public.demarche_documents set
    message_demande = 'Avez-vous votre carte d''identité sur vous ? Prenez d''abord une photo du côté avec VOTRE PHOTO dessus. Posez la carte bien à plat, sans ombre, et envoyez-la avec le bouton photo.',
    messages_rappel = array[
        'Je n''ai pas encore reçu la photo du côté de votre carte d''identité avec votre photo dessus. Envoyez-la dès que vous pouvez, avec le bouton photo.',
        'Toujours pas reçu le côté avec votre photo sur la carte d''identité. Prenez-la bien à plat, sans ombre, et envoyez-la-moi quand vous êtes prêt.'
    ]
where type_document = 'cni_declarant_recto' and message_demande is null;

update public.demarche_documents set
    message_demande = 'Merci. Maintenant, retournez la carte et envoyez-moi une photo de l''AUTRE côté, celui SANS photo dessus — toujours bien à plat, sans ombre.',
    messages_rappel = array[
        'Je n''ai pas encore reçu la photo de l''autre côté de la carte, celui sans photo. Envoyez-la dès que vous pouvez.',
        'Toujours pas reçu le deuxième côté de la carte d''identité (celui sans photo dessus). Prenez-le bien à plat et envoyez-le-moi.'
    ]
where type_document = 'cni_declarant_verso' and message_demande is null;

update public.demarche_documents set
    message_demande = 'Avez-vous le livret de famille ou le certificat de mariage ? Vous pouvez m''en envoyer une photo, ou simplement me dire que vous ne l''avez pas sous la main.',
    messages_rappel = array[
        'Je n''ai pas encore reçu la photo du livret de famille ou du certificat de mariage. Envoyez-la, ou dites-moi simplement que vous ne l''avez pas — ce n''est pas grave.',
        'Toujours rien reçu pour le livret de famille ou le certificat de mariage. Si vous ne l''avez pas sous la main, dites-le-moi simplement, ce n''est pas un problème.'
    ]
where type_document in ('livret_famille', 'certificat_mariage') and message_demande is null;

-- ----------------------------------------------------------------------------
-- 2 à 4. Définition de la démarche elle-même
--
-- `traitable` remplace le « ce système ne sait traiter que l'extrait de
-- naissance » écrit dans le prompt ET dans le code.
-- `mots_cles` remplace `est_demarche_extrait_naissance`, qui cherchait le mot
-- « naissance » dans le nom de la démarche : « certificat de naissance » ou
-- « déclaration de naissance » déclenchaient donc la mauvaise démarche.
-- `champ_age` dit quel champ porte l'âge servant aux cas légaux — l'extrait
-- de naissance est la seule démarche à en avoir un.
-- ----------------------------------------------------------------------------

create table if not exists public.demarche_definitions (
    type_demarche text primary key,
    libelle       text not null,
    mots_cles     text[] not null default '{}',
    traitable     boolean not null default false,
    champ_age     text,
    actif         boolean not null default true,
    version       integer not null default 1   -- incrémenté à chaque publication (étape 2.4)
);

comment on column public.demarche_definitions.traitable is
    'true = le dialogue guidé sait mener cette démarche de bout en bout. false = mode information seulement.';
comment on column public.demarche_definitions.version is
    'Version publiée. Un dialogue déjà commencé garde la version sous laquelle il a démarré (étape 2.4).';

insert into public.demarche_definitions (type_demarche, libelle, mots_cles, traitable, champ_age)
values ('extrait_naissance', 'Extrait de naissance',
        array['extrait de naissance', 'acte de naissance', 'extrait naissance'],
        true, 'age_enfant')
on conflict (type_demarche) do nothing;

-- Types de documents acceptés à l'upload, au-delà de ceux qu'une démarche
-- demande aujourd'hui : d'anciens dossiers en portent encore.
create table if not exists public.types_document_acceptes (
    type_document text primary key,
    libelle       text not null,
    obsolete      boolean not null default false  -- accepté en lecture, plus jamais demandé
);

insert into public.types_document_acceptes (type_document, libelle, obsolete) values
    ('certificat_naissance',  'Certificat de naissance',              false),
    ('cni_declarant_recto',   'Carte d''identité du déclarant, recto', false),
    ('cni_declarant_verso',   'Carte d''identité du déclarant, verso', false),
    ('livret_famille',        'Livret de famille',                     false),
    ('certificat_mariage',    'Certificat de mariage',                 false),
    ('cni_declarant',         'Carte d''identité du déclarant (ancienne pièce unique)', true),
    ('cni_conjoint',          'Carte d''identité du conjoint',         true)
on conflict (type_document) do nothing;

-- ----------------------------------------------------------------------------
-- 5. Cas légaux — les seuils sortent du code
--
-- `determiner_cas_legal` codait 30 et 365 jours en dur, avec une réserve
-- explicite dans sa docstring : le DSF dit « 1 mois, jusqu'à 45 jours en zone
-- rurale éloignée selon les sources ». Ce désaccord doit pouvoir se corriger
-- sans redéployer.
--
-- Le PREMIER cas dont la condition est vraie, dans l'ordre, gagne. Une
-- condition vide est le cas par défaut : il doit y en avoir exactement un,
-- en dernier.
-- ----------------------------------------------------------------------------

create table if not exists public.demarche_cas (
    id            uuid primary key default gen_random_uuid(),
    type_demarche text not null,
    code          text not null,
    ordre         integer not null,
    condition     text,                -- null = cas par défaut (le dernier)
    libelle       text not null,
    source        text,
    hypothese     boolean not null default false,
    unique (type_demarche, code)
);

create index if not exists idx_demarche_cas_type_ordre on public.demarche_cas(type_demarche, ordre);

comment on column public.demarche_cas.hypothese is
    'true tant qu''un officier d''état civil n''a pas confirmé le seuil.';

insert into public.demarche_cas (type_demarche, code, ordre, condition, libelle, source, hypothese) values
    ('extrait_naissance', 'dans_les_delais', 10, 'age_jours(age_enfant) <= 30',
     'Déclaration dans les délais',
     'DSF §5, RG1 — « 1 mois après la naissance ». Le seuil de 30 jours est la convention retenue par les exemples de dialogue.',
     true),
    ('extrait_naissance', 'tardif', 20, 'age_jours(age_enfant) <= 365',
     'Déclaration tardive',
     'DSF §5, RG2 — entre un mois et un an.',
     true),
    ('extrait_naissance', 'jugement_requis', 30, null,
     'Jugement d''autorisation d''inscription tardive requis',
     'DSF §5, RG3 — au-delà d''un an.',
     true)
on conflict (type_demarche, code) do nothing;

-- Note pour la relecture par un officier d'état civil : les trois cas
-- ci-dessus sont marqués `hypothese = true`. Le DSF signale lui-même son
-- incertitude (« jusqu'à 45 jours en zone rurale éloignée selon les
-- sources ») et rien, dans la table `communes`, ne permet aujourd'hui de
-- reconnaître une commune rurale éloignée. La règle des 45 jours n'est donc
-- pas implémentée : il faudra une colonne sur `communes` et une condition
-- supplémentaire ici, pas du code.

-- Pas de RLS sur ces tables : configuration lue par le backend (service role),
-- même principe que demarche_champs / demarche_documents / demarche_regles.
