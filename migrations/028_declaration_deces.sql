-- ============================================================================
-- Migration 028 — Déclaration de décès (plan maître, étapes 5.3 et 5.4)
--
-- Troisième démarche menée par la parole. Résultat : un acte / extrait de
-- décès délivré par la mairie.
--
-- ⚠️ AUCUN CHAMP DE CAUSE DU DÉCÈS. La cause figure sur la partie basse du
-- certificat médical, « renseignements confidentiels et anonymes », qui ne
-- peut être ni communiquée ni copiée. L'application ne la demande pas, ne la
-- stocke pas et refuse la photo qui la montre (services/partie_confidentielle).
-- Ce qui déclenche l'exigence du procès-verbal de police n'est donc pas une
-- question au citoyen sur les circonstances, mais la case « obstacle
-- médico-légal » que le MÉDECIN a cochée sur la partie haute.
--
-- ⚠️ Règles issues de sources publiques (`TODO_DEMARCHES.md`), toutes marquées
-- `hypothese` : à confirmer par un officier d'état civil avant mise en service.
--
-- Le pulaar se saisit et s'écoute dans l'atelier. Rien n'est entendu par un
-- citoyen avant publication de la démarche.
-- ============================================================================

insert into public.demarche_definitions (type_demarche, libelle, mots_cles, traitable, champ_age)
values ('declaration_deces', 'Déclaration de décès',
        array['declaration de deces', 'déclaration de décès', 'acte de deces', 'acte de décès',
              'extrait de deces', 'extrait de décès', 'deces', 'décès'],
        true, null)
on conflict (type_demarche) do nothing;

-- ----------------------------------------------------------------------------
-- Les questions : le défunt, le décès, le déclarant, puis les témoins quand
-- il n'y a pas de certificat médical.
-- ----------------------------------------------------------------------------

insert into public.demarche_champs
    (type_demarche, ordre, nom_champ, type_valeur, question, regle_validation, obligatoire, condition, relances)
values
    ('declaration_deces', 10, 'prenoms_defunt', 'texte',
     'Quels sont les prénoms de la personne décédée ?', null, true, null,
     array['Je n''ai pas bien compris. Quels sont ses prénoms ?',
           'Reprenons doucement : dites-moi les prénoms de la personne décédée.']),
    ('declaration_deces', 20, 'nom_defunt', 'texte',
     'Quel est son nom de famille ?', null, true, null,
     array['Je n''ai pas bien compris. Quel est son nom de famille ?',
           'Reprenons doucement : le nom de famille de la personne décédée ?']),
    ('declaration_deces', 30, 'sexe_defunt', 'enum',
     'Était-ce un homme ou une femme ?', 'masculin|feminin', true, null,
     array['Je n''ai pas bien compris. Un homme ou une femme ?',
           'Reprenons doucement : la personne décédée était-elle un homme ou une femme ?']),
    ('declaration_deces', 40, 'date_naissance_defunt', 'date',
     'Quelle est sa date de naissance ?', 'passee', true, null,
     array['Je n''ai pas bien compris la date. Quel jour, quel mois, quelle année est-elle née ?',
           'Reprenons doucement : sa date de naissance ?']),
    ('declaration_deces', 50, 'lieu_naissance_defunt', 'texte',
     'Où est-elle née ?', null, true, null,
     array['Je n''ai pas bien compris. Dans quelle commune est-elle née ?',
           'Reprenons doucement : son lieu de naissance ?']),
    ('declaration_deces', 60, 'profession_defunt', 'texte',
     'Quel métier faisait-elle ?', null, false, null,
     array['Je n''ai pas bien compris. Quel était son métier ?',
           'Reprenons doucement : quel métier faisait-elle ?']),
    ('declaration_deces', 70, 'domicile_defunt', 'texte',
     'Où habitait-elle ?', null, true, null,
     array['Je n''ai pas bien compris. Dans quel quartier ou village habitait-elle ?',
           'Reprenons doucement : où habitait-elle ?']),
    ('declaration_deces', 80, 'nationalite_defunt', 'texte',
     'Quelle était sa nationalité ?', null, true, null,
     array['Je n''ai pas bien compris. De quel pays était-elle ?',
           'Reprenons doucement : sa nationalité ?']),
    ('declaration_deces', 90, 'situation_matrimoniale_defunt', 'enum',
     'Était-elle célibataire, mariée, veuve ou divorcée ?',
     'celibataire|marie|veuf|divorce', true, null,
     array['Je n''ai pas bien compris. Célibataire, mariée, veuve ou divorcée ?',
           'Reprenons doucement : quelle était sa situation — célibataire, mariée, veuve ou divorcée ?']),
    ('declaration_deces', 100, 'nom_pere_defunt', 'texte',
     'Comment s''appelle son père ?', null, false, null,
     array['Je n''ai pas bien compris. Le nom complet de son père ?',
           'Reprenons doucement : comment s''appelle son père ?']),
    ('declaration_deces', 110, 'nom_mere_defunt', 'texte',
     'Comment s''appelle sa mère ?', null, false, null,
     array['Je n''ai pas bien compris. Le nom complet de sa mère ?',
           'Reprenons doucement : comment s''appelle sa mère ?']),

    -- Le décès lui-même. Aucune question sur la cause : elle appartient au
    -- document confidentiel du médecin.
    ('declaration_deces', 120, 'date_deces', 'date',
     'Quel jour la personne est-elle décédée ?', 'passee|apres:date_naissance_defunt', true, null,
     array['Je n''ai pas bien compris la date. Quel jour, quel mois, quelle année ?',
           'Reprenons doucement : quel jour est-elle décédée ?']),
    ('declaration_deces', 130, 'heure_deces', 'texte',
     'À quelle heure, à peu près ?', null, false, null,
     array['Je n''ai pas bien compris. Vers quelle heure est-elle décédée ?',
           'Reprenons doucement : le matin, l''après-midi, la nuit ? Vers quelle heure ?']),
    ('declaration_deces', 140, 'lieu_deces', 'enum',
     'Où est-elle décédée : à la maison, dans un hôpital ou un poste de santé, sur la voie publique, ou ailleurs ?',
     'domicile|structure_sanitaire|voie_publique|autre', true, null,
     array['Je n''ai pas bien compris. À la maison, dans un hôpital, sur la voie publique, ou ailleurs ?',
           'Reprenons doucement : dans quel endroit est-elle décédée ?']),
    ('declaration_deces', 150, 'commune_deces', 'texte',
     'Dans quelle commune est-elle décédée ?', null, true, null,
     array['Je n''ai pas bien compris. Dans quelle commune ?',
           'Reprenons doucement : le nom de la commune où elle est décédée ?']),
    -- Ce que le MÉDECIN a coché sur la partie haute du certificat, lu par le
    -- déclarant. Jamais une question sur les circonstances de la mort.
    ('declaration_deces', 160, 'certificat_medical_existe', 'booleen',
     'Avez-vous un certificat de décès signé par un médecin ou un agent de santé ?', null, true, null,
     array['Je n''ai pas bien compris. Avez-vous un papier signé par un médecin ou un agent de santé ?',
           'Reprenons doucement : un médecin ou un agent de santé a-t-il signé un certificat, oui ou non ?']),
    ('declaration_deces', 170, 'obstacle_medico_legal', 'booleen',
     'Sur ce certificat, la case « existence d''un obstacle médico-légal » est-elle cochée « oui » ?',
     null, true, 'certificat_medical_existe = oui',
     array['Je n''ai pas bien compris. Sur le papier du médecin, la case « obstacle médico-légal » est-elle cochée « oui » ?',
           'Reprenons doucement : cherchez la ligne « obstacle médico-légal ». Est-ce coché oui, ou non ?']),

    -- Le déclarant.
    ('declaration_deces', 180, 'nom_declarant', 'texte',
     'Pouvez-vous me donner votre nom complet, à vous, en tant que déclarant ?', null, true, null,
     array['Je n''ai pas bien compris. Quel est votre nom complet ?',
           'Reprenons doucement : dites-moi vos prénoms et votre nom de famille.']),
    ('declaration_deces', 190, 'piece_declarant', 'texte',
     'Quel est le numéro de votre carte d''identité ?', null, true, null,
     array['Je n''ai pas bien compris. Le numéro de votre carte d''identité ?',
           'Reprenons doucement : lisez-moi le numéro inscrit sur votre carte.']),
    ('declaration_deces', 200, 'lien_avec_defunt', 'texte',
     'Quel était votre lien avec la personne décédée ?', null, true, null,
     array['Je n''ai pas bien compris. Étiez-vous son enfant, son conjoint, un voisin ?',
           'Reprenons doucement : quel lien aviez-vous avec elle ?']),
    ('declaration_deces', 210, 'domicile_declarant', 'texte',
     'Où habitez-vous ?', null, true, null,
     array['Je n''ai pas bien compris. Dans quel quartier ou village habitez-vous ?',
           'Reprenons doucement : où habitez-vous ?']),

    -- Sans certificat médical, deux témoins majeurs sont exigés.
    ('declaration_deces', 220, 'nom_temoin_1', 'texte',
     'Comment s''appelle le premier témoin majeur qui confirme le décès ?', null, true,
     'certificat_medical_existe = non',
     array['Je n''ai pas bien compris. Le nom complet du premier témoin ?',
           'Reprenons doucement : comment s''appelle le premier témoin ?']),
    ('declaration_deces', 230, 'piece_temoin_1', 'texte',
     'Quel est le numéro de sa carte d''identité ?', null, true,
     'certificat_medical_existe = non',
     array['Je n''ai pas bien compris. Le numéro de la carte du premier témoin ?',
           'Reprenons doucement : lisez-moi le numéro de sa carte d''identité.']),
    ('declaration_deces', 240, 'nom_temoin_2', 'texte',
     'Comment s''appelle le deuxième témoin majeur ?', null, true,
     'certificat_medical_existe = non',
     array['Je n''ai pas bien compris. Le nom complet du deuxième témoin ?',
           'Reprenons doucement : comment s''appelle le deuxième témoin ?']),
    ('declaration_deces', 250, 'piece_temoin_2', 'texte',
     'Quel est le numéro de sa carte d''identité ?', null, true,
     'certificat_medical_existe = non',
     array['Je n''ai pas bien compris. Le numéro de la carte du deuxième témoin ?',
           'Reprenons doucement : lisez-moi le numéro de sa carte d''identité.'])
on conflict (type_demarche, nom_champ) do nothing;

-- ----------------------------------------------------------------------------
-- Les pièces. La consigne du certificat dit explicitement de n'envoyer que la
-- partie haute : c'est la seule protection que le citoyen entend avant de
-- photographier (le refus après coup, lui, est dans le code).
-- ----------------------------------------------------------------------------

insert into public.types_document_acceptes (type_document, libelle) values
    ('certificat_deces',   'Certificat de décès, partie haute uniquement'),
    ('cni_defunt',         'Carte d''identité de la personne décédée'),
    ('pv_police',          'Procès-verbal de constat de la police ou de la gendarmerie')
on conflict (type_document) do nothing;

insert into public.demarche_documents
    (type_demarche, ordre, type_document, obligatoire, condition, apres_champ, message_demande, messages_rappel)
values
    ('declaration_deces', 260, 'certificat_deces', true, 'certificat_medical_existe = oui', 'domicile_declarant',
     'Envoyez-moi une photo du certificat signé par le médecin. Attention : le formulaire se détache en deux. '
     'Photographiez seulement la partie du haut, celle qui s''appelle « certificat de décès ». La partie du bas '
     'indique la cause du décès : elle est confidentielle, gardez-la, je ne peux pas l''enregistrer.',
     array['Je n''ai pas encore reçu le certificat du médecin. Rappelez-vous : seulement la partie du haut.',
           'Il me manque toujours la partie haute du certificat de décès, celle à détacher.']),
    ('declaration_deces', 270, 'cni_declarant_recto', true, null, 'domicile_declarant',
     'Envoyez-moi une photo du recto de votre carte d''identité.',
     array['Je n''ai pas encore reçu le recto de votre carte d''identité.',
           'Il me manque toujours le recto de votre carte d''identité.']),
    ('declaration_deces', 280, 'cni_declarant_verso', true, null, 'domicile_declarant',
     'Retournez votre carte d''identité et envoyez-moi une photo du verso.',
     array['Je n''ai pas encore reçu le verso de votre carte d''identité.',
           'Il me manque toujours le verso de votre carte d''identité.']),
    ('declaration_deces', 290, 'cni_defunt', false, null, 'domicile_declarant',
     'Si vous l''avez, envoyez-moi une photo de la carte d''identité de la personne décédée.',
     array['Je n''ai pas encore reçu la carte d''identité de la personne décédée.',
           'Si vous n''avez pas sa carte d''identité, dites-le-moi et nous continuerons.']),
    ('declaration_deces', 300, 'livret_famille', false, null, 'domicile_declarant',
     'Si la famille a un livret de famille, envoyez-moi une photo de la page qui la concerne.',
     array['Je n''ai pas encore reçu le livret de famille.',
           'Si vous n''avez pas de livret de famille, dites-le-moi et nous continuerons.']),
    -- Mort violente : c'est la case cochée par le médecin qui l'établit.
    ('declaration_deces', 310, 'pv_police', true, 'obstacle_medico_legal = oui', 'domicile_declarant',
     'Le médecin a signalé un obstacle médico-légal. Envoyez-moi une photo du procès-verbal établi par la police '
     'ou la gendarmerie.',
     array['Je n''ai pas encore reçu le procès-verbal de la police.',
           'Il me manque toujours le procès-verbal de la police ou de la gendarmerie.']),
    ('declaration_deces', 320, 'cni_temoin_1', true, 'certificat_medical_existe = non', 'domicile_declarant',
     'Envoyez-moi une photo de la carte d''identité du premier témoin.',
     array['Je n''ai pas encore reçu la carte d''identité du premier témoin.',
           'Il me manque toujours la carte d''identité du premier témoin.']),
    ('declaration_deces', 330, 'cni_temoin_2', true, 'certificat_medical_existe = non', 'domicile_declarant',
     'Envoyez-moi une photo de la carte d''identité du deuxième témoin.',
     array['Je n''ai pas encore reçu la carte d''identité du deuxième témoin.',
           'Il me manque toujours la carte d''identité du deuxième témoin.'])
on conflict (type_demarche, type_document) do nothing;

-- ----------------------------------------------------------------------------
-- Cas légaux : dans les 24 heures, ou déclaration tardive encore recevable en
-- mairie. Au-delà d'un an, ce n'est plus un cas mais un blocage (voir règle).
-- ----------------------------------------------------------------------------

insert into public.demarche_cas (type_demarche, code, ordre, condition, libelle)
values
    ('declaration_deces', 'dans_les_delais', 10, 'jours_depuis(date_deces) <= 1',
     'Déclaration dans les vingt-quatre heures'),
    ('declaration_deces', 'tardive', 20, null,
     'Déclaration tardive, encore recevable en mairie')
on conflict (type_demarche, code) do nothing;

-- ----------------------------------------------------------------------------
-- Règles transverses. À confirmer par un officier d'état civil.
-- ----------------------------------------------------------------------------

insert into public.demarche_regles
    (type_demarche, code, ordre, condition, effet, champ_concerne, message, source, hypothese)
values
    ('declaration_deces', 'plus_d_un_an', 10,
     'annees_depuis(date_deces) >= 1', 'bloquer', null,
     'Le décès remonte à plus d''un an. La mairie ne peut plus l''inscrire directement : il faut un jugement '
     'd''autorisation d''inscription tardive, demandé au président du tribunal départemental. Je ne peux pas '
     'poursuivre cette démarche ici, mais on peut vous expliquer comment faire au tribunal.',
     'Code de la famille du Sénégal ; rufisqueouest.org, « Demander un jugement d''autorisation d''inscription '
     'tardive de décès » ; senegalservices.sn, « Déclarer un décès »', true)
on conflict (type_demarche, code) do nothing;

-- ----------------------------------------------------------------------------
-- Récapitulatif lu avant confirmation (RG7). Il ne dit RIEN de la cause du
-- décès : l'application ne la connaît pas, et ne doit pas la connaître.
-- ----------------------------------------------------------------------------

insert into public.demarche_gabarits (type_demarche, cle, francais, contexte)
values ('declaration_deces', 'recapitulatif',
        'Je vous relis maintenant ce que j''ai noté pour vérifier que c''est correct : '
        'le décès de {prenoms_defunt} {nom_defunt}, né le {date_naissance_defunt} à {lieu_naissance_defunt}, '
        'survenu le {date_deces} à {commune_deces}. '
        'La déclaration est faite par {nom_declarant}, {lien_avec_defunt}. Est-ce que tout est exact ?',
        'Relecture avant confirmation (RG7) de la déclaration de décès')
on conflict (type_demarche, cle) do nothing;
