-- ============================================================================
-- Migration 029 — Premier jet pulaar pour les trois démarches
--
-- ⚠️ CE SONT DES BROUILLONS, PAS DES TRADUCTIONS RELUES. Rien n'est marqué
-- `pulaar_valide` : le dialogue ne dira donc AUCUNE de ces phrases telles
-- quelles (cf. `Phrase.pulaar_pret`, étape 3.1). Elles servent de point de
-- départ dans l'atelier : corriger un texte existant va plus vite que partir
-- d'une page blanche, et écouter révèle ce que la lecture ne montre pas.
--
-- Style repris du corpus déjà validé (`phrases.tsv`) et du glossaire
-- (`services/pulaar.py`) : mots d'emprunt écrits comme ils se prononcent
-- (meeri, komin, sertifika, fotoo, dosiye), et tournures des phrases que vous
-- avez déjà relues.
--
-- Les RELANCES sont construites à partir de la question, avec les deux
-- entrées en tête du corpus validé (« Mi faamaani e no fewi. » et « En
-- fuɗɗito seese. »). Le français des relances, lui, reformule parfois
-- autrement : c'est l'un des premiers points à reprendre à l'atelier.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Extrait de naissance — uniquement ce que les migrations 025 et 026 ont
-- ajouté ou réécrit. Le reste est déjà relu, on n'y touche pas.
-- ----------------------------------------------------------------------------

update public.demarche_champs set question_pulaar = 'Ɓiɗɗo maa ko gorko walla ko debbo?'
where type_demarche = 'extrait_naissance' and nom_champ = 'sexe_enfant';

update public.demarche_champs set question_pulaar = 'Aan, ko a baaba ɓiɗɗo oo?'
where type_demarche = 'extrait_naissance' and nom_champ = 'declarant_est_pere';

update public.demarche_champs set question_pulaar = 'Innde baaba ɓiɗɗo oo timmunde ko honnde?'
where type_demarche = 'extrait_naissance' and nom_champ = 'nom_pere';

update public.demarche_champs set question_pulaar = 'Baaba e neene ɓiɗɗo oo, hara eɓe resondiri?'
where type_demarche = 'extrait_naissance' and nom_champ = 'parents_maries';

update public.demarche_gabarits set pulaar =
    'Jooni mi fillitanay ma ko mi winndi fof, ngam ƴeewde so ko goonga : '
 || '{nom_enfant}, jibinaaɗo {date_naissance_enfant} e {commune_naissance}. '
 || 'Neene makko ko {nom_mere}, jibinaaɗo {date_naissance_mere}. '
 || 'Winnditaare ndee ko {nom_declarant} waɗi ndi. Ko ɗum fof woni goonga?'
where type_demarche = 'extrait_naissance' and cle = 'recapitulatif';

-- ----------------------------------------------------------------------------
-- Constatation de mariage
-- ----------------------------------------------------------------------------

update public.demarche_champs set question_pulaar = case nom_champ
    when 'prenoms_epoux'          then 'Inɗe gorko oo ko honɗe?'
    when 'nom_epoux'              then 'Innde ɓesngu gorko oo ko honnde?'
    when 'date_naissance_epoux'   then 'Ñalnde jibineede gorko oo ko honnde?'
    when 'lieu_naissance_epoux'   then 'Gorko oo jibinaa ko toy?'
    when 'profession_epoux'       then 'Golle gorko oo ko honɗe?'
    when 'domicile_epoux'         then 'Gorko oo hoɗi ko toy?'
    when 'nom_pere_epoux'         then 'Innde baaba gorko oo ko honnde?'
    when 'nom_mere_epoux'         then 'Innde neene gorko oo ko honnde?'
    when 'prenoms_epouse'         then 'Inɗe debbo oo ko honɗe?'
    when 'nom_epouse'             then 'Innde ɓesngu debbo oo ko honnde?'
    when 'date_naissance_epouse'  then 'Ñalnde jibineede debbo oo ko honnde?'
    when 'lieu_naissance_epouse'  then 'Debbo oo jibinaa ko toy?'
    when 'profession_epouse'      then 'Golle debbo oo ko honɗe?'
    when 'domicile_epouse'        then 'Debbo oo hoɗi ko toy?'
    when 'nom_pere_epouse'        then 'Innde baaba debbo oo ko honnde?'
    when 'nom_mere_epouse'        then 'Innde neene debbo oo ko honnde?'
    when 'date_celebration'       then 'Ñalnde dewgal ngal waɗi ko honnde?'
    when 'lieu_celebration'       then 'Dewgal ngal waɗi ko toy?'
    when 'option_matrimoniale'    then 'Gorko oo holliri ko dewgal gootal, walla ko o waawi resde rewɓe ɗiɗo, tato walla nayo?'
    when 'regime_matrimonial'     then 'Jawdi ndin, on njiɗi ko nde seerndee, nde wonta denndaandi, walla laawol dote?'
    when 'nom_temoin_1'           then 'Innde seede gadano tawanooɗo dewgal ngal ko honnde?'
    when 'piece_temoin_1'         then 'Limoore kaayit ganndinirgal seede gadano oo ko honnde?'
    when 'nom_temoin_2'           then 'Innde seede ɗiɗaɓo oo ko honnde?'
    when 'piece_temoin_2'         then 'Limoore kaayit ganndinirgal seede ɗiɗaɓo oo ko honnde?'
    else question_pulaar end
where type_demarche = 'constatation_mariage';

update public.demarche_documents set message_demande_pulaar = case type_document
    when 'cni_epoux'             then 'Neldu kam fotoo kaayit ganndinirgal gorko oo. Waɗ ngal feewde, tawa ɗowdi alaa dow mum.'
    when 'cni_epouse'            then 'Neldu kam fotoo kaayit ganndinirgal debbo oo. Waɗ ngal feewde, tawa ɗowdi alaa dow mum.'
    when 'acte_naissance_epoux'  then 'Neldu kam fotoo deftere wulngo gorko oo.'
    when 'acte_naissance_epouse' then 'Neldu kam fotoo deftere wulngo debbo oo.'
    when 'cni_temoin_1'          then 'Neldu kam fotoo kaayit ganndinirgal seede gadano oo.'
    when 'cni_temoin_2'          then 'Neldu kam fotoo kaayit ganndinirgal seede ɗiɗaɓo oo.'
    when 'dispense_age'          then 'Neldu kam fotoo yamiroore ñaawirdu ndun fii hitaande.'
    else message_demande_pulaar end,
    messages_rappel_pulaar = case type_document
    when 'cni_epoux'             then array['Mi heɓaani tawo fotoo kaayit ganndinirgal gorko oo.',
                                            'Hay jooni mi heɓaani kaayit ganndinirgal gorko oo.']
    when 'cni_epouse'            then array['Mi heɓaani tawo fotoo kaayit ganndinirgal debbo oo.',
                                            'Hay jooni mi heɓaani kaayit ganndinirgal debbo oo.']
    when 'acte_naissance_epoux'  then array['Mi heɓaani tawo deftere wulngo gorko oo.',
                                            'Hay jooni mi heɓaani deftere wulngo gorko oo.']
    when 'acte_naissance_epouse' then array['Mi heɓaani tawo deftere wulngo debbo oo.',
                                            'Hay jooni mi heɓaani deftere wulngo debbo oo.']
    when 'cni_temoin_1'          then array['Mi heɓaani tawo kaayit ganndinirgal seede gadano oo.',
                                            'Hay jooni mi heɓaani kaayit ganndinirgal seede gadano oo.']
    when 'cni_temoin_2'          then array['Mi heɓaani tawo kaayit ganndinirgal seede ɗiɗaɓo oo.',
                                            'Hay jooni mi heɓaani kaayit ganndinirgal seede ɗiɗaɓo oo.']
    when 'dispense_age'          then array['Mi heɓaani tawo yamiroore ñaawirdu ndun.',
                                            'Hay jooni mi heɓaani yamiroore ñaawirdu ndun.']
    else messages_rappel_pulaar end
where type_demarche = 'constatation_mariage';

update public.demarche_gabarits set pulaar =
    'Jooni mi fillitanay ma ko mi winndi, ngam ƴeewde so ko goonga : '
 || 'dewgal {prenoms_epoux} {nom_epoux} e {prenoms_epouse} {nom_epouse}, '
 || 'ngal waɗi {date_celebration} to {lieu_celebration}. '
 || 'Ko hollinaa : {option_matrimoniale}. Laawol jawdi : {regime_matrimonial}. '
 || 'Seedeeɓe ɓen ko {nom_temoin_1} e {nom_temoin_2}. Ko ɗum fof woni goonga?'
where type_demarche = 'constatation_mariage' and cle = 'recapitulatif';

-- ----------------------------------------------------------------------------
-- Déclaration de décès
-- ----------------------------------------------------------------------------

update public.demarche_champs set question_pulaar = case nom_champ
    when 'prenoms_defunt'                then 'Inɗe neɗɗo maayɗo oo ko honɗe?'
    when 'nom_defunt'                    then 'Innde ɓesngu makko ko honnde?'
    when 'sexe_defunt'                   then 'O wonnoo ko gorko walla ko debbo?'
    when 'date_naissance_defunt'         then 'Ñalnde jibineede makko ko honnde?'
    when 'lieu_naissance_defunt'         then 'O jibinaa ko toy?'
    when 'profession_defunt'             then 'Golle makko ko honɗe?'
    when 'domicile_defunt'               then 'O hoɗatnoo ko toy?'
    when 'nationalite_defunt'            then 'O ummoriino ko leydi honndi?'
    when 'situation_matrimoniale_defunt' then 'O wonnoo ko resaani, o resii, joom suudu makko maayii, walla o seerii?'
    when 'nom_pere_defunt'               then 'Innde baaba makko ko honnde?'
    when 'nom_mere_defunt'               then 'Innde neene makko ko honnde?'
    when 'date_deces'                    then 'Ñalnde o maayi ko honnde?'
    when 'heure_deces'                   then 'O maayi ko waktu honngu, e taƴre?'
    when 'lieu_deces'                    then 'O maayi ko to galle, to opitaal walla nokku cellal, e laawol, walla nokku goɗɗo?'
    when 'commune_deces'                 then 'O maayi ko e komin honnbo?'
    when 'certificat_medical_existe'     then 'Aɗa jogii sertifika maayde siifaaɗo doktoor walla gollotooɗo cellal?'
    when 'obstacle_medico_legal'         then 'E oo sertifika, geɗal « obstacle médico-légal » ngal hokkaa ko « eey »?'
    when 'nom_declarant'                 then 'Innde maa timmunde ko honnde, an mo winnditotoo oo?'
    when 'piece_declarant'               then 'Limoore kaayit ganndinirgal maa ko honnde?'
    when 'lien_avec_defunt'              then 'Ko enɗam honɗam ngonnoo hakkunde maa e neɗɗo maayɗo oo?'
    when 'domicile_declarant'            then 'Aɗa hoɗi ko toy?'
    when 'nom_temoin_1'                  then 'Innde seede gadano oo seedantooɗo maayde ndee ko honnde?'
    when 'piece_temoin_1'                then 'Limoore kaayit ganndinirgal makko ko honnde?'
    when 'nom_temoin_2'                  then 'Innde seede ɗiɗaɓo oo ko honnde?'
    when 'piece_temoin_2'                then 'Limoore kaayit ganndinirgal makko ko honnde?'
    else question_pulaar end
where type_demarche = 'declaration_deces';

update public.demarche_documents set message_demande_pulaar = case type_document
    when 'certificat_deces'     then 'Neldu kam fotoo sertifika maayde ngal doktoor siifi. Teskee : kaayit ngal no seerta ɗiɗi. '
                                  || 'Ƴettu tan geɗal dow ngal, ngal wiyetee « certificat de décès ». Geɗal les ngal no holla ko waɗi maayde ndee : '
                                  || 'ɗum ko sirru, reen ngal, mi waawaa winndude ngal.'
    when 'cni_declarant_recto'  then 'Neldu kam fotoo geɗal kaayit ganndinirgal maa ngal fotoo maa woni e mum.'
    when 'cni_declarant_verso'  then 'Jooni yiltu kaayit ngal, neldaa kam fotoo geɗal goɗngal ngal.'
    when 'cni_defunt'           then 'So aɗa jogii ngal, neldu kam fotoo kaayit ganndinirgal neɗɗo maayɗo oo.'
    when 'livret_famille'       then 'So ɓesngu ngun no jogii deftere ɓesngu, neldu kam fotoo hello ngo ngal habri.'
    when 'pv_police'            then 'Doktoor oo holliri ko « obstacle médico-légal ». Neldu kam fotoo kaayit ngal polis walla saŋdarmori winndi.'
    when 'cni_temoin_1'         then 'Neldu kam fotoo kaayit ganndinirgal seede gadano oo.'
    when 'cni_temoin_2'         then 'Neldu kam fotoo kaayit ganndinirgal seede ɗiɗaɓo oo.'
    else message_demande_pulaar end,
    messages_rappel_pulaar = case type_document
    when 'certificat_deces'     then array['Mi heɓaani tawo sertifika doktoor oo. Teskee : ko geɗal dow ngal tan.',
                                           'Hay jooni mi heɓaani geɗal dow sertifika maayde ngal, ngal seertata ngal.']
    when 'cni_declarant_recto'  then array['Mi heɓaani tawo geɗal ngal fotoo maa woni e mum.',
                                           'Hay jooni mi heɓaani geɗal ngal fotoo maa woni e mum.']
    when 'cni_declarant_verso'  then array['Mi heɓaani tawo geɗal goɗngal kaayit ngal.',
                                           'Hay jooni mi heɓaani geɗal ɗiɗaɓal kaayit ganndinirgal maa.']
    when 'cni_defunt'           then array['Mi heɓaani tawo kaayit ganndinirgal neɗɗo maayɗo oo.',
                                           'So a alaa ngal, wi''am tan, en njokkay.']
    when 'livret_famille'       then array['Mi heɓaani tawo deftere ɓesngu ndee.',
                                           'So a alaa deftere ɓesngu, wi''am tan, en njokkay.']
    when 'pv_police'            then array['Mi heɓaani tawo kaayit polis oo.',
                                           'Hay jooni mi heɓaani kaayit polis walla saŋdarmori oo.']
    when 'cni_temoin_1'         then array['Mi heɓaani tawo kaayit ganndinirgal seede gadano oo.',
                                           'Hay jooni mi heɓaani kaayit ganndinirgal seede gadano oo.']
    when 'cni_temoin_2'         then array['Mi heɓaani tawo kaayit ganndinirgal seede ɗiɗaɓo oo.',
                                           'Hay jooni mi heɓaani kaayit ganndinirgal seede ɗiɗaɓo oo.']
    else messages_rappel_pulaar end
where type_demarche = 'declaration_deces';

update public.demarche_gabarits set pulaar =
    'Jooni mi fillitanay ma ko mi winndi, ngam ƴeewde so ko goonga : '
 || 'maayde {prenoms_defunt} {nom_defunt}, jibinaaɗo {date_naissance_defunt} to {lieu_naissance_defunt}, '
 || 'o maayi {date_deces} to {commune_deces}. '
 || 'Winnditaare ndee ko {nom_declarant} waɗi ndi, {lien_avec_defunt}. Ko ɗum fof woni goonga?'
where type_demarche = 'declaration_deces' and cle = 'recapitulatif';

-- ----------------------------------------------------------------------------
-- Les relances, construites à partir de la question — mêmes deux entrées en
-- tête que dans le corpus déjà relu. Seules les lignes encore vides sont
-- remplies : une relance déjà écrite à l'atelier n'est jamais écrasée.
-- ----------------------------------------------------------------------------

update public.demarche_champs
set relances_pulaar = array[
        'Mi faamaani e no fewi. ' || question_pulaar,
        'En fuɗɗito seese. ' || question_pulaar
    ]
where type_demarche in ('extrait_naissance', 'constatation_mariage', 'declaration_deces')
  and question_pulaar is not null and question_pulaar <> ''
  and coalesce(array_length(relances_pulaar, 1), 0) = 0
  and coalesce(array_length(relances, 1), 0) = 2;

-- Aucun `pulaar_valide` n'est touché : tout reste à écouter et à valider
-- dans l'atelier, phrase par phrase.
