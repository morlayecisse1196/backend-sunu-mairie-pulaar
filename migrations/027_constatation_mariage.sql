-- ============================================================================
-- Migration 027 — Constatation de mariage (plan maître, étape 5.2)
--
-- Deuxième démarche menée entièrement par la parole. Résultat : un certificat
-- de mariage constaté, délivré par la mairie.
--
-- ⚠️ TOUTES les règles ci-dessous viennent de sources publiques
-- (`TODO_DEMARCHES.md`, section « Sources ») et sont marquées `hypothese` :
-- aucune n'a encore été confirmée par un officier d'état civil. Une règle
-- fausse ici produit un acte invalide. À faire relire avant mise en service.
--
-- Le pulaar n'est pas écrit ici : il se saisit et s'écoute dans l'atelier.
-- Rien n'est entendu par un citoyen avant publication de la démarche.
-- ============================================================================

insert into public.demarche_definitions (type_demarche, libelle, mots_cles, traitable, champ_age)
values ('constatation_mariage', 'Constatation de mariage',
        array['constatation de mariage', 'certificat de mariage', 'constater mon mariage',
              'mariage coutumier', 'mariage religieux', 'mariage'],
        true, null)
on conflict (type_demarche) do nothing;

-- ----------------------------------------------------------------------------
-- Les questions. Les deux époux d'abord, puis le mariage, puis les témoins.
-- ----------------------------------------------------------------------------

insert into public.demarche_champs
    (type_demarche, ordre, nom_champ, type_valeur, question, regle_validation, obligatoire, condition, relances)
values
    ('constatation_mariage', 10, 'prenoms_epoux', 'texte',
     'Quels sont les prénoms du mari ?', null, true, null,
     array['Je n''ai pas bien compris. Quels sont les prénoms du mari ?',
           'Reprenons doucement : dites-moi les prénoms du mari.']),
    ('constatation_mariage', 20, 'nom_epoux', 'texte',
     'Quel est le nom de famille du mari ?', null, true, null,
     array['Je n''ai pas bien compris. Quel est le nom de famille du mari ?',
           'Reprenons doucement : le nom de famille du mari ?']),
    ('constatation_mariage', 30, 'date_naissance_epoux', 'date',
     'Quelle est la date de naissance du mari ?', 'passee', true, null,
     array['Je n''ai pas bien compris la date. Quel jour, quel mois, quelle année le mari est-il né ?',
           'Reprenons doucement : la date de naissance du mari ?']),
    ('constatation_mariage', 40, 'lieu_naissance_epoux', 'texte',
     'Où le mari est-il né ?', null, true, null,
     array['Je n''ai pas bien compris. Dans quelle commune le mari est-il né ?',
           'Reprenons doucement : le lieu de naissance du mari ?']),
    ('constatation_mariage', 50, 'profession_epoux', 'texte',
     'Quel est le métier du mari ?', null, true, null,
     array['Je n''ai pas bien compris. Quel métier fait le mari ?',
           'Reprenons doucement : le métier du mari ?']),
    ('constatation_mariage', 60, 'domicile_epoux', 'texte',
     'Où habite le mari ?', null, true, null,
     array['Je n''ai pas bien compris. Dans quel quartier ou village habite le mari ?',
           'Reprenons doucement : où habite le mari ?']),
    ('constatation_mariage', 70, 'nom_pere_epoux', 'texte',
     'Comment s''appelle le père du mari ?', null, true, null,
     array['Je n''ai pas bien compris. Le nom complet du père du mari ?',
           'Reprenons doucement : comment s''appelle le père du mari ?']),
    ('constatation_mariage', 80, 'nom_mere_epoux', 'texte',
     'Comment s''appelle la mère du mari ?', null, true, null,
     array['Je n''ai pas bien compris. Le nom complet de la mère du mari ?',
           'Reprenons doucement : comment s''appelle la mère du mari ?']),

    ('constatation_mariage', 90, 'prenoms_epouse', 'texte',
     'Quels sont les prénoms de l''épouse ?', null, true, null,
     array['Je n''ai pas bien compris. Quels sont les prénoms de l''épouse ?',
           'Reprenons doucement : dites-moi les prénoms de l''épouse.']),
    ('constatation_mariage', 100, 'nom_epouse', 'texte',
     'Quel est le nom de famille de l''épouse ?', null, true, null,
     array['Je n''ai pas bien compris. Quel est le nom de famille de l''épouse ?',
           'Reprenons doucement : le nom de famille de l''épouse ?']),
    ('constatation_mariage', 110, 'date_naissance_epouse', 'date',
     'Quelle est la date de naissance de l''épouse ?', 'passee', true, null,
     array['Je n''ai pas bien compris la date. Quel jour, quel mois, quelle année l''épouse est-elle née ?',
           'Reprenons doucement : la date de naissance de l''épouse ?']),
    ('constatation_mariage', 120, 'lieu_naissance_epouse', 'texte',
     'Où l''épouse est-elle née ?', null, true, null,
     array['Je n''ai pas bien compris. Dans quelle commune l''épouse est-elle née ?',
           'Reprenons doucement : le lieu de naissance de l''épouse ?']),
    ('constatation_mariage', 130, 'profession_epouse', 'texte',
     'Quel est le métier de l''épouse ?', null, true, null,
     array['Je n''ai pas bien compris. Quel métier fait l''épouse ?',
           'Reprenons doucement : le métier de l''épouse ?']),
    ('constatation_mariage', 140, 'domicile_epouse', 'texte',
     'Où habite l''épouse ?', null, true, null,
     array['Je n''ai pas bien compris. Dans quel quartier ou village habite l''épouse ?',
           'Reprenons doucement : où habite l''épouse ?']),
    ('constatation_mariage', 150, 'nom_pere_epouse', 'texte',
     'Comment s''appelle le père de l''épouse ?', null, true, null,
     array['Je n''ai pas bien compris. Le nom complet du père de l''épouse ?',
           'Reprenons doucement : comment s''appelle le père de l''épouse ?']),
    ('constatation_mariage', 160, 'nom_mere_epouse', 'texte',
     'Comment s''appelle la mère de l''épouse ?', null, true, null,
     array['Je n''ai pas bien compris. Le nom complet de la mère de l''épouse ?',
           'Reprenons doucement : comment s''appelle la mère de l''épouse ?']),

    ('constatation_mariage', 170, 'date_celebration', 'date',
     'Quel jour la cérémonie de mariage a-t-elle eu lieu ?', 'passee', true, null,
     array['Je n''ai pas bien compris la date. Quel jour, quel mois, quelle année la cérémonie a-t-elle eu lieu ?',
           'Reprenons doucement : la date de la cérémonie ?']),
    ('constatation_mariage', 180, 'lieu_celebration', 'texte',
     'Où la cérémonie a-t-elle eu lieu ?', null, true, null,
     array['Je n''ai pas bien compris. Dans quel village ou quelle commune la cérémonie a-t-elle eu lieu ?',
           'Reprenons doucement : le lieu de la cérémonie ?']),
    ('constatation_mariage', 190, 'option_matrimoniale', 'enum',
     'Quelle option de mariage le mari a-t-il déclarée : la monogamie, ou la polygamie limitée à deux, trois ou quatre épouses ?',
     'monogamie|polygamie_2|polygamie_3|polygamie_4', true, null,
     array['Je n''ai pas bien compris. Est-ce la monogamie, ou la polygamie limitée à deux, trois ou quatre épouses ?',
           'Reprenons doucement : le mari a-t-il déclaré la monogamie, ou la polygamie ? Si c''est la polygamie, jusqu''à combien d''épouses ?']),
    ('constatation_mariage', 200, 'regime_matrimonial', 'enum',
     'Quel régime de biens avez-vous choisi : la séparation des biens, la communauté des biens, ou le régime dotal ?',
     'separation_des_biens|communaute|dotal', true, null,
     array['Je n''ai pas bien compris. Séparation des biens, communauté des biens, ou régime dotal ?',
           'Reprenons doucement : comment les biens sont-ils partagés — séparés, en commun, ou régime dotal ?']),

    ('constatation_mariage', 210, 'nom_temoin_1', 'texte',
     'Comment s''appelle le premier témoin présent à la cérémonie ?', null, true, null,
     array['Je n''ai pas bien compris. Le nom complet du premier témoin ?',
           'Reprenons doucement : comment s''appelle le premier témoin ?']),
    ('constatation_mariage', 220, 'piece_temoin_1', 'texte',
     'Quel est le numéro de la carte d''identité du premier témoin ?', null, true, null,
     array['Je n''ai pas bien compris. Le numéro de la carte d''identité du premier témoin ?',
           'Reprenons doucement : lisez-moi le numéro de la carte du premier témoin.']),
    ('constatation_mariage', 230, 'nom_temoin_2', 'texte',
     'Comment s''appelle le deuxième témoin présent à la cérémonie ?', null, true, null,
     array['Je n''ai pas bien compris. Le nom complet du deuxième témoin ?',
           'Reprenons doucement : comment s''appelle le deuxième témoin ?']),
    ('constatation_mariage', 240, 'piece_temoin_2', 'texte',
     'Quel est le numéro de la carte d''identité du deuxième témoin ?', null, true, null,
     array['Je n''ai pas bien compris. Le numéro de la carte d''identité du deuxième témoin ?',
           'Reprenons doucement : lisez-moi le numéro de la carte du deuxième témoin.'])
on conflict (type_demarche, nom_champ) do nothing;

-- ----------------------------------------------------------------------------
-- Les pièces à photographier.
-- ----------------------------------------------------------------------------

insert into public.types_document_acceptes (type_document, libelle) values
    ('cni_epoux',                'Carte d''identité du mari'),
    ('cni_epouse',               'Carte d''identité de l''épouse'),
    ('acte_naissance_epoux',     'Acte de naissance du mari'),
    ('acte_naissance_epouse',    'Acte de naissance de l''épouse'),
    ('cni_temoin_1',             'Carte d''identité du premier témoin'),
    ('cni_temoin_2',             'Carte d''identité du deuxième témoin'),
    ('dispense_age',             'Dispense d''âge du président du tribunal')
on conflict (type_document) do nothing;

insert into public.demarche_documents
    (type_demarche, ordre, type_document, obligatoire, condition, apres_champ, message_demande, messages_rappel)
values
    ('constatation_mariage', 250, 'cni_epoux', true, null, 'piece_temoin_2',
     'Envoyez-moi une photo de la carte d''identité du mari.',
     array['Je n''ai pas encore reçu la photo de la carte d''identité du mari.',
           'Il me manque toujours la carte d''identité du mari.']),
    ('constatation_mariage', 260, 'cni_epouse', true, null, 'piece_temoin_2',
     'Envoyez-moi une photo de la carte d''identité de l''épouse.',
     array['Je n''ai pas encore reçu la photo de la carte d''identité de l''épouse.',
           'Il me manque toujours la carte d''identité de l''épouse.']),
    ('constatation_mariage', 270, 'acte_naissance_epoux', true, null, 'piece_temoin_2',
     'Envoyez-moi une photo de l''acte de naissance du mari.',
     array['Je n''ai pas encore reçu l''acte de naissance du mari.',
           'Il me manque toujours l''acte de naissance du mari.']),
    ('constatation_mariage', 280, 'acte_naissance_epouse', true, null, 'piece_temoin_2',
     'Envoyez-moi une photo de l''acte de naissance de l''épouse.',
     array['Je n''ai pas encore reçu l''acte de naissance de l''épouse.',
           'Il me manque toujours l''acte de naissance de l''épouse.']),
    ('constatation_mariage', 290, 'cni_temoin_1', true, null, 'piece_temoin_2',
     'Envoyez-moi une photo de la carte d''identité du premier témoin.',
     array['Je n''ai pas encore reçu la carte d''identité du premier témoin.',
           'Il me manque toujours la carte d''identité du premier témoin.']),
    ('constatation_mariage', 300, 'cni_temoin_2', true, null, 'piece_temoin_2',
     'Envoyez-moi une photo de la carte d''identité du deuxième témoin.',
     array['Je n''ai pas encore reçu la carte d''identité du deuxième témoin.',
           'Il me manque toujours la carte d''identité du deuxième témoin.']),
    -- Demandée seulement si l'un des deux était mineur le jour de la cérémonie.
    ('constatation_mariage', 310, 'dispense_age', true,
     'annees_depuis(date_naissance_epouse) < 16 ou annees_depuis(date_naissance_epoux) < 18',
     'piece_temoin_2',
     'Envoyez-moi une photo de la dispense d''âge délivrée par le président du tribunal.',
     array['Je n''ai pas encore reçu la dispense d''âge.',
           'Il me manque toujours la dispense d''âge du président du tribunal.'])
on conflict (type_demarche, type_document) do nothing;

-- ----------------------------------------------------------------------------
-- Cas légal. Un seul pour l'instant : la constatation recevable en mairie.
-- Le mariage de plus de six mois n'est pas un cas, c'est un blocage (règle
-- ci-dessous) : le dossier ne doit pas exister.
-- ----------------------------------------------------------------------------

insert into public.demarche_cas (type_demarche, code, ordre, condition, libelle)
values ('constatation_mariage', 'constatation_en_mairie', 10, null,
        'Constatation recevable en mairie')
on conflict (type_demarche, code) do nothing;

-- ----------------------------------------------------------------------------
-- Règles transverses. Toutes à confirmer par un officier d'état civil.
-- ----------------------------------------------------------------------------

insert into public.demarche_regles
    (type_demarche, code, ordre, condition, effet, champ_concerne, message, source, hypothese)
values
    ('constatation_mariage', 'delai_six_mois', 10,
     'mois_depuis(date_celebration) > 6', 'bloquer', null,
     'Votre mariage a été célébré il y a plus de six mois. La mairie ne peut plus le constater '
     'elle-même : il faut demander une inscription au tribunal départemental. Je ne peux pas '
     'poursuivre cette démarche ici, mais on peut vous expliquer comment faire au tribunal.',
     'Code de la famille du Sénégal ; fbavocat-sn.com, « L''inscription du mariage au Sénégal : '
     'délais légaux et procédure judiciaire en cas d''omission » (2025)', true),
    ('constatation_mariage', 'polygamie_sans_communaute', 20,
     'option_matrimoniale != "monogamie" et regime_matrimonial = "communaute"', 'interdire',
     'regime_matrimonial',
     'La communauté des biens n''est pas possible avec une option polygamique. Le régime doit être '
     'la séparation des biens ou le régime dotal. Lequel choisissez-vous ?',
     'Code de la famille du Sénégal, régimes matrimoniaux ; fbavocat-sn.com, « La constatation du '
     'mariage dans le droit sénégalais » (2025)', true)
on conflict (type_demarche, code) do nothing;

-- ----------------------------------------------------------------------------
-- Récapitulatif lu avant confirmation (RG7). Il ne relit pas les trente
-- réponses : il relit ce qui identifie le mariage et ce qui l'engage.
-- ----------------------------------------------------------------------------

insert into public.demarche_gabarits (type_demarche, cle, francais, contexte)
values ('constatation_mariage', 'recapitulatif',
        'Je vous relis maintenant ce que j''ai noté pour vérifier que c''est correct : '
        'le mariage de {prenoms_epoux} {nom_epoux} et de {prenoms_epouse} {nom_epouse}, '
        'célébré le {date_celebration} à {lieu_celebration}. '
        'Option déclarée : {option_matrimoniale}. Régime des biens : {regime_matrimonial}. '
        'Les témoins sont {nom_temoin_1} et {nom_temoin_2}. Est-ce que tout est exact ?',
        'Relecture avant confirmation (RG7) de la constatation de mariage')
on conflict (type_demarche, cle) do nothing;
