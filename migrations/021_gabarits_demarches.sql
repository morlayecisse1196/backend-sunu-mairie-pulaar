-- ============================================================================
-- Migration 021 — Gabarits à trous : le récapitulatif sort du traducteur
-- Réf. : backend-agent/PLAN_MAITRE.md, étape 3.2
--
-- Le récapitulatif est le moment décisif du dialogue : le citoyen y confirme
-- des informations qui finiront sur un acte d'état civil. Il ne peut pas être
-- une phrase figée, puisqu'il contient ses réponses. Il partait donc EN ENTIER
-- au traducteur — valeurs comprises — et revenait différent à chaque
-- conversation, avec les dates lues comme des suites de chiffres.
--
-- On sépare la PHRASE des VALEURS. La phrase est un gabarit, relu une fois
-- pour toutes ; les valeurs sont insérées par le code, qui sait énoncer une
-- date ou un âge en pulaar (`services/pulaar_nombres.py`). Plus aucun modèle
-- n'intervient sur le récapitulatif une fois le gabarit validé.
--
-- Les trous s'écrivent `{nom_champ}` et doivent nommer des champs existants de
-- la démarche. Une valeur manquante empêche le rendu plutôt que d'écrire
-- « non renseigné » : faire confirmer au citoyen une information qu'il n'a
-- jamais donnée est exactement ce qu'un récapitulatif doit empêcher.
-- ============================================================================

create table if not exists public.demarche_gabarits (
    type_demarche text not null,
    cle           text not null,
    francais      text not null,
    pulaar        text,
    pulaar_valide boolean not null default false,
    audio         text,          -- jamais utilisé ici : le texte change à chaque dossier
    contexte      text not null,
    primary key (type_demarche, cle)
);

comment on table public.demarche_gabarits is
    'Phrases à trous. `{nom_champ}` est remplacé par la valeur donnée par le citoyen, énoncée '
    'en pulaar par le code (dates, âges, nombres) — jamais par le modèle.';
comment on column public.demarche_gabarits.audio is
    'Sans objet pour un gabarit : le texte final dépend du dossier, il ne peut pas être '
    'pré-généré. Colonne gardée pour que la table ait la même forme que les autres.';

insert into public.demarche_gabarits (type_demarche, cle, francais, contexte) values
    ('extrait_naissance', 'recapitulatif',
     'Je vous relis maintenant tout ce que j''ai noté pour vérifier que c''est correct : '
     '{nom_enfant}, né le {date_naissance_enfant} à {commune_naissance}, enfant de '
     '{nom_declarant} et de {nom_mere}, née le {date_naissance_mere}. Est-ce que tout est exact ?',
     'Relecture obligatoire avant envoi du dossier (RG7). Le citoyen confirme ou corrige. '
     'C''est la dernière occasion de rattraper une erreur avant l''acte.')
on conflict (type_demarche, cle) do nothing;

-- Note sur `parents_maries` : volontairement absent du gabarit. Le
-- récapitulatif historique disait « parents mariés » ou « parents non
-- mariés », une formule qui ne s''insère pas dans un trou (ce n'est pas une
-- valeur, c'est une tournure). À rajouter quand le gabarit sera relu, si
-- l'officier d'état civil juge l'information nécessaire à la confirmation.

-- Pas de RLS : table de configuration, lue par le backend (service role).
