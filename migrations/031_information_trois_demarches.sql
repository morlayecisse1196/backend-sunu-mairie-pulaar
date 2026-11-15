-- ============================================================================
-- Migration 031 — Contenu du mode information pour les trois démarches
-- Réf. : PLAN_MAITRE.md, étape 5.6
--
-- Le mode information répond à partir de la table `demarches` (RAG). Elle ne
-- contenait rien sur deux des trois démarches que l'agent sait maintenant
-- mener : un citoyen qui demandait « comment faire constater mon mariage ? »
-- recevait une réponse approximative, et l'agent ne lui proposait pas de
-- commencer alors qu'il en est capable.
--
-- ⚠️ COÛT ET DÉLAI VOLONTAIREMENT VIDES sur les lignes ajoutées. Ils varient
-- d'une commune à l'autre et je n'ai aucune source fiable : l'agent dira donc
-- « je ne connais pas le montant, renseignez-vous à la mairie » au lieu
-- d'avancer un chiffre faux. À remplir par la mairie (écran Informations).
--
-- ⚠️ Les conditions reprennent les règles des migrations 027 et 028, toutes
-- issues de sources publiques et NON confirmées par un officier d'état civil.
-- C'est dit dans les alertes, que l'agent lit au citoyen.
--
-- APRÈS CETTE MIGRATION : régénérer les vecteurs de recherche, sinon les
-- nouvelles lignes resteront introuvables par le mode information :
--     python seed_embeddings.py
-- ============================================================================

insert into public.demarches
    (commune, categorie, nom_demarche, documents_requis, conditions, cout, delai, lieu, alertes, regles_speciales)
values
    ('National', 'État Civil', 'Extrait de naissance',
     array[
        'Le numéro de l''acte de naissance, ou une copie d''un extrait déjà délivré',
        'La pièce d''identité du déclarant',
        'Le livret de famille s''il existe'
     ],
     array[
        'Se demande au centre d''état civil où la naissance a été déclarée',
        'L''agent peut constituer le dossier par téléphone : questions, puis photos des pièces',
        'Si l''enfant n''a jamais été déclaré, c''est une déclaration de naissance qu''il faut, pas un extrait'
     ],
     null, null,
     'Centre d''état civil du lieu de naissance',
     array['Si la naissance n''a jamais été déclarée et que l''enfant a plus d''un an, un jugement du tribunal devient nécessaire'],
     'Demande de copie d''un acte déjà inscrit au registre — à ne pas confondre avec la déclaration de naissance.'),

    ('National', 'État Civil', 'Constatation de mariage',
     array[
        'Cartes d''identité des deux époux',
        'Actes de naissance des deux époux',
        'Cartes d''identité des deux témoins présents à la cérémonie',
        'Dispense du tribunal si l''un des époux était mineur'
     ],
     array[
        'La cérémonie coutumière ou religieuse doit avoir eu lieu il y a moins de six mois',
        'Deux témoins majeurs présents à la cérémonie sont obligatoires',
        'L''option (monogamie ou polygamie) et le régime des biens sont déclarés à ce moment-là',
        'L''agent peut constituer le dossier par téléphone : questions, puis photos des pièces'
     ],
     null, null,
     'Centre d''état civil du lieu de la cérémonie',
     array[
        'Passé six mois, la mairie n''est plus compétente : il faut saisir le tribunal départemental',
        'Règles issues de sources publiques, à confirmer auprès de votre mairie'
     ],
     'La communauté des biens est incompatible avec une option polygamique : séparation des biens ou régime dotal.')
on conflict do nothing;

-- ----------------------------------------------------------------------------
-- Le décès a déjà sa ligne. On complète ce qui manque pour correspondre à ce
-- que l'agent sait faire, sans écraser le contenu existant : les conditions et
-- alertes sont AJOUTÉES si elles n'y sont pas déjà.
-- ----------------------------------------------------------------------------

update public.demarches
set conditions = conditions || array[
        'Sans certificat médical, deux témoins majeurs sont obligatoires',
        'L''agent peut constituer le dossier par téléphone : questions, puis photos des pièces'
    ]
where categorie = 'État Civil'
  and nom_demarche ilike '%décès%'
  and not (conditions @> array['L''agent peut constituer le dossier par téléphone : questions, puis photos des pièces']);

update public.demarches
set alertes = alertes || array[
        'Au-delà d''un an, un jugement d''autorisation d''inscription tardive devient obligatoire',
        'Le certificat du médecin se détache en deux : seule la partie haute est demandée, la partie basse est confidentielle'
    ]
where categorie = 'État Civil'
  and nom_demarche ilike '%décès%'
  and not (alertes @> array['Au-delà d''un an, un jugement d''autorisation d''inscription tardive devient obligatoire']);
