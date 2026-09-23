-- ============================================================================
-- Migration 026 — Le déclarant n'est pas toujours le père
-- Réf. : backend-agent/PLAN_MAITRE.md, étape 5.1 (option C)
--
-- Le dialogue supposait que le déclarant est le père : « Êtes-vous mariés,
-- elle et vous ? », puis un récapitulatif « enfant de <déclarant> et de
-- <mère> ». Quand une grand-mère déclare, la question n'a pas de sens et le
-- récapitulatif lui fait confirmer qu'elle est le parent.
--
--   * nouvelle question : « Êtes-vous le père de l'enfant ? » ;
--   * si non : le nom du père, FACULTATIF (père inconnu : l'acte l'admet) ;
--   * la question sur le mariage et le récapitulatif deviennent neutres.
--
-- Le français de ces deux phrases change : leur pulaar relu traduisait
-- l'ancien texte. Leur relecture est retirée (même règle que l'atelier) ;
-- l'ancienne traduction reste affichée dans l'atelier comme point de départ.
--
-- Tout ceci entre dans le BROUILLON : rien ne change pour les citoyens
-- avant publication depuis l'écran Démarches.
-- ============================================================================

insert into public.demarche_champs
    (type_demarche, ordre, nom_champ, type_valeur, question, obligatoire, condition, relances)
values
    ('extrait_naissance', 52, 'declarant_est_pere', 'booleen',
     'Êtes-vous le père de l''enfant ?',
     true, null,
     array['Je n''ai pas bien compris. Êtes-vous le père de l''enfant ?',
           'Reprenons doucement : êtes-vous le père de cet enfant, oui ou non ?']),
    ('extrait_naissance', 54, 'nom_pere', 'texte',
     'Quel est le nom complet du père de l''enfant ?',
     false, 'declarant_est_pere = non',
     array['Je n''ai pas bien compris. Comment s''appelle le père de l''enfant ?',
           'Reprenons doucement : quel est le nom complet du père ?'])
on conflict (type_demarche, nom_champ) do nothing;

update public.demarche_champs
set question = 'Le père et la mère de l''enfant sont-ils mariés ?',
    relances = array['Je n''ai pas bien compris. Les parents de l''enfant sont-ils mariés ?',
                     'Reprenons doucement : le père et la mère sont-ils mariés, oui ou non ?'],
    pulaar_valide = false,
    relances_pulaar_valide = '{}'
where type_demarche = 'extrait_naissance'
  and nom_champ = 'parents_maries'
  and question = 'Êtes-vous mariés, elle et vous ?';

update public.demarche_gabarits
set francais = 'Je vous relis maintenant tout ce que j''ai noté pour vérifier que c''est correct : '
            || '{nom_enfant}, né le {date_naissance_enfant} à {commune_naissance}. '
            || 'Sa mère est {nom_mere}, née le {date_naissance_mere}. '
            || 'La déclaration est faite par {nom_declarant}. Est-ce que tout est exact ?',
    pulaar_valide = false
where type_demarche = 'extrait_naissance'
  and cle = 'recapitulatif'
  and francais like '%enfant de {nom_declarant} et de {nom_mere}%';
