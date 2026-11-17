-- ============================================================================
-- 037 — Brouillons pulaar pour les 20 phrases encore vides de l'atelier
--
-- But : qu'un locuteur CORRIGE au lieu d'ÉCRIRE. Rien ici n'est relu, donc
-- `pulaar_valide` reste false et AUCUNE de ces phrases ne sera dite : le
-- français repart au traducteur, exactement comme avant cette migration.
-- L'invariant du projet est intact.
--
-- D'OÙ VIENNENT CES BROUILLONS, ET CE QUE ÇA VAUT
--
-- Trois sources, et la provenance de chacune est écrite dans `contexte` pour
-- que le relecteur sache où regarder en priorité :
--
--   [glossaire]  services/pulaar.py, termes de statut VALIDE, issus du corpus.
--                C'est la source la plus sûre du projet.
--   [modèle]     Le NLLB-200 affiné du projet (francais-pulaar-bf16), sur une
--                PHRASE. Mesuré le 2026-11-17 sur les onze questions réelles
--                de l'extrait de naissance : 0/11 de français résiduel,
--                0/11 de phrase ajoutée. C'est son point fort.
--   [modèle, terme isolé]  Le même modèle sur une ÉTIQUETTE de deux mots.
--                C'est son point FAIBLE, mesuré aussi : 4 % seulement des 78
--                termes du glossaire rendus correctement, avec des répétitions
--                caractéristiques. Il a par exemple rendu « Marié » par
--                « Marié marié » et « Féminin » par « Femmein » — ces deux-là
--                sont donc repris du glossaire, pas du modèle.
--   [français conservé]  Aucun terme pulaar connu. Le corpus du projet garde
--                déjà le français dans ce cas (« permis de construire »,
--                « original », « budget »). À trancher par le relecteur.
--
-- Les clauses `where` ne touchent que les lignes ENCORE VIDES : une phrase
-- déjà relue, ou déjà corrigée depuis, n'est jamais écrasée. Rejouer cette
-- migration ne refait rien.
-- ============================================================================

-- --- Phrases complètes : le modèle sur son point fort -----------------------

update public.phrases_systeme set
    pulaar = 'Mi nanaama ma.', pulaar_valide = false,
    contexte = contexte || ' [brouillon 2026-11-17, source : modèle]'
where cle = 'document_message_entendu' and coalesce(pulaar, '') = '';

update public.phrases_systeme set
    pulaar = 'Ɗum noon, ƴettu waktu maa. Miɗo nana ma.', pulaar_valide = false,
    contexte = contexte || ' [brouillon 2026-11-17, source : modèle]'
where cle = 'social_patience' and coalesce(pulaar, '') = '';

-- « Je vous en prie » est une FORMULE, pas une phrase à traduire mot à mot.
-- Le modèle a rendu le sens littéral (« je t'ai prié »), ce qui est très
-- probablement un contresens : c'est la réponse à un merci qu'il faut ici.
update public.phrases_systeme set
    pulaar = 'Mi ñaagii ma.', pulaar_valide = false,
    contexte = contexte || ' [brouillon 2026-11-17, source : modèle — ⚠️ FORMULE '
               || 'traduite littéralement, probable contresens : il faut la réponse '
               || 'à un remerciement, à revoir en priorité]'
where cle = 'social_remerciement' and coalesce(pulaar, '') = '';

-- Le modèle a laissé « Bonjour ! » tel quel. On reprend la salutation que le
-- projet reconnaît déjà en entrée (services/tours_sociaux.py).
update public.phrases_systeme set
    pulaar = 'Jam tan!', pulaar_valide = false,
    contexte = contexte || ' [brouillon 2026-11-17, source : salutations reconnues '
               || 'par le projet — le modèle avait laissé « Bonjour ! » en français]'
where cle = 'social_salutation' and coalesce(pulaar, '') = '';

-- --- Sexe et situation : le glossaire tranche -------------------------------

update public.phrases_systeme set
    pulaar = 'Gorko', pulaar_valide = false,
    contexte = contexte || ' [brouillon 2026-11-17, source : glossaire — le même mot '
               || 'que la question relue « Ɓiɗɗo maa ko gorko walla ko debbo? »]'
where cle = 'valeur_masculin' and coalesce(pulaar, '') = '';

update public.phrases_systeme set
    pulaar = 'Debbo', pulaar_valide = false,
    contexte = contexte || ' [brouillon 2026-11-17, source : glossaire — le même mot '
               || 'que la question relue « Ɓiɗɗo maa ko gorko walla ko debbo? »]'
where cle = 'valeur_feminin' and coalesce(pulaar, '') = '';

update public.phrases_systeme set
    pulaar = 'Resii', pulaar_valide = false,
    contexte = contexte || ' [brouillon 2026-11-17, source : glossaire]'
where cle = 'valeur_marie' and coalesce(pulaar, '') = '';

update public.phrases_systeme set
    pulaar = 'Ceertiiɗo', pulaar_valide = false,
    contexte = contexte || ' [brouillon 2026-11-17, source : modèle, terme isolé — '
               || 'cohérent avec « ceergal » (divorce) du glossaire]'
where cle = 'valeur_divorce' and coalesce(pulaar, '') = '';

-- Le modèle a produit une DESCRIPTION (« le vieux dont la femme est morte »)
-- là où il faut une étiquette d'une ligne, affichée dans un formulaire.
update public.phrases_systeme set
    pulaar = 'Mawɗo debbo on maayi', pulaar_valide = false,
    contexte = contexte || ' [brouillon 2026-11-17, source : modèle, terme isolé — '
               || '⚠️ le modèle a décrit au lieu de nommer ; il faut une étiquette '
               || 'courte, à réécrire]'
where cle = 'valeur_veuf' and coalesce(pulaar, '') = '';

-- --- Lieux de l'événement ---------------------------------------------------

update public.phrases_systeme set
    pulaar = 'To galle', pulaar_valide = false,
    contexte = contexte || ' [brouillon 2026-11-17, source : glossaire (galle = maison) — '
               || '⚠️ composé pour cette migration, jamais vu tel quel dans le corpus ; '
               || 'le modèle avait laissé « To domicile »]'
where cle = 'valeur_domicile' and coalesce(pulaar, '') = '';

update public.phrases_systeme set
    pulaar = 'E nder suudu cellal', pulaar_valide = false,
    contexte = contexte || ' [brouillon 2026-11-17, source : modèle, terme isolé — '
               || 'le glossaire propose « opitaal » (hôpital) si une structure de soins '
               || 'suffit à le dire]'
where cle = 'valeur_structure_sanitaire' and coalesce(pulaar, '') = '';

update public.phrases_systeme set
    pulaar = 'E laawol laamu', pulaar_valide = false,
    contexte = contexte || ' [brouillon 2026-11-17, source : modèle, terme isolé]'
where cle = 'valeur_voie_publique' and coalesce(pulaar, '') = '';

update public.phrases_systeme set
    pulaar = 'Ko nokku goɗɗo', pulaar_valide = false,
    contexte = contexte || ' [brouillon 2026-11-17, source : modèle, terme isolé]'
where cle = 'valeur_autre' and coalesce(pulaar, '') = '';

-- --- Régimes matrimoniaux : vocabulaire juridique ---------------------------
--
-- C'est le groupe le plus incertain de la migration. Ces notions viennent du
-- Code de la famille et n'ont pas d'équivalent dans le glossaire. Le relecteur
-- décidera s'il faut traduire ou garder le terme français, comme le corpus le
-- fait déjà pour « permis de construire ».

update public.phrases_systeme set
    pulaar = 'Kominɗe jawdi ɗen', pulaar_valide = false,
    contexte = contexte || ' [brouillon 2026-11-17, source : modèle, terme isolé — '
               || '⚠️ « kominɗe » ressemble à « communes » (komin) : probable faux ami, '
               || 'à vérifier]'
where cle = 'valeur_communaute' and coalesce(pulaar, '') = '';

update public.phrases_systeme set
    pulaar = 'Seertiiɗe jawdi ɗen', pulaar_valide = false,
    contexte = contexte || ' [brouillon 2026-11-17, source : modèle, terme isolé — '
               || '« jawdi » (les biens) est rendu pareil que dans « communauté des biens », '
               || 'ce qui est au moins cohérent]'
where cle = 'valeur_separation_des_biens' and coalesce(pulaar, '') = '';

update public.phrases_systeme set
    pulaar = 'Régime dotal', pulaar_valide = false,
    contexte = contexte || ' [brouillon 2026-11-17, français conservé — le modèle n''a '
               || 'rien traduit ; à trancher par le relecteur]'
where cle = 'valeur_dotal' and coalesce(pulaar, '') = '';

update public.phrases_systeme set
    pulaar = 'Monogamie', pulaar_valide = false,
    contexte = contexte || ' [brouillon 2026-11-17, français conservé — le modèle n''a '
               || 'rien traduit ; à trancher par le relecteur]'
where cle = 'valeur_monogamie' and coalesce(pulaar, '') = '';

-- Les nombres, eux, sont sûrs : ils viennent de services/pulaar_nombres.py,
-- qui produit déjà les âges et les dates dites au citoyen. Le modèle avait
-- écrit « nayo » pour quatre ; c'est « nayi » dans le projet.
update public.phrases_systeme set
    pulaar = 'Polygamie ɓeydooɗo e rewɓe ɗiɗi', pulaar_valide = false,
    contexte = contexte || ' [brouillon 2026-11-17, source : modèle ; « ɗiɗi » (deux) '
               || 'confirmé par pulaar_nombres]'
where cle = 'valeur_polygamie_2' and coalesce(pulaar, '') = '';

update public.phrases_systeme set
    pulaar = 'Polygamie ɓeydooɗo e rewɓe tati', pulaar_valide = false,
    contexte = contexte || ' [brouillon 2026-11-17, source : modèle ; « tati » (trois) '
               || 'confirmé par pulaar_nombres]'
where cle = 'valeur_polygamie_3' and coalesce(pulaar, '') = '';

update public.phrases_systeme set
    pulaar = 'Polygamie ɓeydooɗo e rewɓe nayi', pulaar_valide = false,
    contexte = contexte || ' [brouillon 2026-11-17, source : modèle ; le modèle avait '
               || 'écrit « nayo », corrigé en « nayi » (quatre) d''après pulaar_nombres]'
where cle = 'valeur_polygamie_4' and coalesce(pulaar, '') = '';

-- --- Garde-fou --------------------------------------------------------------
-- Aucune de ces lignes ne doit être dite tant qu'un locuteur ne l'a pas relue.
do $$
declare n integer;
begin
    select count(*) into n from public.phrases_systeme
    where pulaar_valide and contexte like '%brouillon 2026-11-17%';
    if n > 0 then
        raise exception 'Un brouillon non relu est marqué valide (% lignes)', n;
    end if;
end $$;
