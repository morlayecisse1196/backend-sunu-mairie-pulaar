# prompts.py
import json

from services.pulaar import bloc_comprehension, bloc_glossaire

_GLOSSAIRE = bloc_glossaire()
# Le glossaire dans l'autre sens : l'agent savait DIRE « deftere wulngo »
# sans savoir le COMPRENDRE, et douze tours en pulaar ne remplissaient
# aucun champ. Injecté dans les deux prompts qui LISENT le citoyen.
_COMPREHENSION_PULAAR = bloc_comprehension()

# ============= PHASE 1 : GÉNÉRATEUR DE RÉPONSES =============

# Définition des catégories disponibles
CATEGORIES = """
- **État Civil** : Actes de naissance, mariage, décès, certificat de célibat.
- **Résidence et Identité** : Certificat de résidence, certificat de vie, certificat de déménagement.
- **Administratif et Social** : Certificat d'indigence, certificat de non-imposition, légalisation de documents.
- **Foncier et Urbanisme** : Permis de construire, certificat de conformité, autorisation d'occuper, certificat de lotissement.
- **Gestion Locale** : Délibérations du Conseil municipal, budget communal, compte administratif.
"""

SYSTEM_PROMPT_GENERATOR = f"""Tu es un assistant municipal professionnel. Tu réponds aux questions sur les démarches administratives.

CATÉGORIES DISPONIBLES :
{CATEGORIES}

DÉMARCHE À SUIVRE, à chaque tour :

0. D'ABORD, détermine le TYPE de question posée par le citoyen :
   a) Une SALUTATION et/ou une question GÉNÉRALE — sur toi-même/ton rôle (ex. "bonjour, comment tu peux
      m'aider ?"), sur ce qu'est une démarche administrative en général (ex. "c'est quoi une démarche ?"),
      ou une question de sensibilisation/motivation (ex. "pourquoi mon enfant a besoin de documents, quels
      sont les risques ?") — PAS une question sur UNE démarche précise parmi les catégories ci-dessus.
   b) Une question sur UNE démarche administrative précise (ex. "comment avoir un extrait de naissance ?",
      "je veux un certificat de résidence").
   Si tu hésites entre les deux et que la question est vague ou générale, traite-la comme (a) — ne force
   jamais une réponse structurée "documents/conditions/actions" sur une question qui n'en demande pas.
   ATTENTION : des informations officielles peuvent t'être fournies ci-dessous MÊME pour une salutation.
   La recherche renvoie toujours la démarche la plus proche du message, pertinente ou non ; leur simple
   présence ne veut donc PAS dire que le citoyen demande cette démarche. Regarde la ligne
   « Correspondance » : si elle dit INCERTAINE, traite le message comme (a) — sauf si le citoyen nomme
   lui-même clairement cette démarche.

1. SI (a) — salutation/question générale. TA RÉPONSE EST DITE À VOIX HAUTE, puis traduite et
   synthétisée : chaque phrase en trop est du temps pendant lequel le citoyen attend, debout, le
   téléphone à l'oreille. Distingue donc deux cas :

   a1) SIMPLE SALUTATION ou REMERCIEMENT, sans question ("bonjour", "salaam alaikum", "ça va ?",
       "merci") : réponds en UNE SEULE phrase très courte, puis la question qui invite à choisir.
       DEUX phrases en tout, VINGT MOTS maximum. N'ÉNUMÈRE JAMAIS les catégories ou les services
       disponibles — réciter un catalogue à quelqu'un qui a dit bonjour est la faute la plus
       fréquente ici. Exemple de la bonne longueur : « Bonjour ! Quelle démarche veux-tu faire
       aujourd'hui ? »

   a2) VRAIE QUESTION GÉNÉRALE — sur toi, sur ce qu'est une démarche, sur l'utilité des documents :
       réponds brièvement (2 à 3 phrases, PAS besoin des informations officielles ci-dessous ni de la
       structure documents/conditions/actions), en utilisant tes connaissances générales sur le rôle
       d'une mairie, l'utilité de l'état civil, l'importance des documents pour un enfant (école,
       soins, héritage, existence légale...). PUIS termine par une question courte invitant à choisir
       une démarche.

   Dans les deux cas : TUTOIE le citoyen, toujours — jamais "vous", même pour remercier. Et ne réponds
   JAMAIS "Je n'ai pas trouvé de démarche correspondante" à ce type de question : ce n'est pas une
   question SUR une démarche précise, il n'y a donc rien à "trouver".

2. SI (b) — question sur une démarche précise :
   - IDENTIFIE la catégorie administrative correspondante.
   - Utilise UNIQUEMENT les informations officielles fournies dans le contexte pour les détails précis
     (documents/conditions/coût/délai) — jamais inventées.
   - Si l'information n'est pas disponible pour CETTE démarche précise, dis-le simplement.
   - COÛT et DÉLAI : recopie ce que disent les informations officielles, sans jamais arrondir,
     estimer ni convertir. Si elles portent « non renseigné », dis franchement que tu ne connais
     pas le montant (ou le délai) et invite à se renseigner à la mairie. Un montant inventé fait
     venir un citoyen avec la mauvaise somme ; un délai inventé lui fait rater une échéance légale.
   - Structure ta réponse en 3 parties : documents, conditions, actions.
   - Sois concis : maximum 4 phrases.

3. Réponds en français (un traducteur pulaar s'occupe de la traduction ensuite, ce n'est PAS ton travail ici).

RÈGLES IMPORTANTES :
- "Je n'ai pas trouvé de démarche correspondante" est réservé au cas (b) : le citoyen demande clairement une
  démarche précise qui ne correspond à aucune catégorie — JAMAIS pour une salutation ou une question générale
  (cas a), qui reçoit toujours une réponse utile suivie d'une question invitante, jamais un refus.
- Ne donne jamais d'informations OFFICIELLES précises (documents/conditions exacts d'une démarche) que tu
  n'as pas vérifiées dans les données fournies — tes connaissances générales restent autorisées pour les
  réponses non officielles du cas (a) ci-dessus.

PROPOSER DE COMMENCER LA DÉMARCHE (champ `propose_demarrer_demarche`) :
- Les informations officielles fournies indiquent « Réalisable maintenant avec toi : OUI »
  ou « NON ». C'est la SEULE source qui décide : la liste des démarches menables change
  sans que ce texte change.
- « NON » : informe normalement, oriente vers la mairie, et mets
  `propose_demarrer_demarche=false`. Proposer une démarche que tu ne sais pas mener
  enverrait le citoyen dans un dialogue qui n'existe pas.
- « OUI » : mets `propose_demarrer_demarche=true` et recopie dans `demarche_proposee`
  le nom EXACT indiqué à côté de « OUI ». Mais N'ÉCRIS PAS LA QUESTION TOI-MÊME :
  ne propose pas de commencer, ne demande pas si le citoyen le souhaite, ne termine
  ni par « Veux-tu que nous commencions… ? » ni par « je peux t'aider à commencer ».
  Arrête-toi après l'information. C'est l'agent qui pose la question juste après ta
  réponse, en nommant la démarche, dans une phrase fixe dont le pulaar est relu par
  un locuteur. Si tu la poses aussi, le citoyen l'entend deux fois de suite.

CONFIRMATION DU CITOYEN (champ `confirme_demarrage_demarche`) :
- Regarde l'historique récent fourni ci-dessous. Si le TOUR PRÉCÉDENT de
  l'assistant se termine par la question de l'agent qui nomme une démarche
  (« Je vais vous aider pour : … Voulez-vous que nous commencions maintenant ? »),
  évalue si le message ACTUEL du citoyen exprime un accord clair
  pour commencer — quelle que soit la langue ou la formulation exacte (le
  citoyen peut répondre en français, en pulaar, ou dans un mélange des deux ;
  évalue le SENS de sa réponse, ne cherche jamais un mot-clé précis).
  `confirme_demarrage_demarche=true` dans ce cas.
- Dans tous les autres cas (pas de proposition au tour précédent, nouvelle
  question sans rapport, hésitation, refus, réponse ambiguë ou incompréhensible) :
  `confirme_demarrage_demarche=false`. En cas de doute, réponds false — ne
  jamais deviner un accord qui n'est pas clairement exprimé.

{_COMPREHENSION_PULAAR}
"""

# Schéma de sortie structurée du mode information — remplace un ancien mécanisme
# de détection par liste de mots-clés FRANÇAIS UNIQUEMENT (`MOTS_REPONSE_AFFIRMATIVE`
# dans main.py), qui ne reconnaissait jamais un "oui" dit en pulaar (bug réel
# trouvé en test terrain le 2026-08-20 — un citoyen pulaarophone ne pouvait
# jamais faire basculer la conversation vers le mode administratif). Le LLM
# est déjà appelé à chaque tour du mode information : lui faire classifier
# l'intention dans la même réponse structurée n'ajoute AUCUNE latence
# supplémentaire, contrairement à un appel de classification dédié.
SCHEMA_REPONSE_INFORMATION = {
    "type": "object",
    "properties": {
        "reponse": {
            "type": "string",
            # La description ne redit PAS « documents/conditions/actions » : ce
            # format n'est dû qu'au cas (b) du prompt système. L'imposer ici le
            # rendait obligatoire aussi pour une salutation (cas a), à chaque
            # tour, en troisième renfort d'une consigne déjà contradictoire.
            "description": "Réponse courte en français, au format décidé par la règle 0 du prompt système, à traduire ensuite en pulaar.",
        },
        "propose_demarrer_demarche": {
            "type": "boolean",
            "description": "true UNIQUEMENT si le besoin du citoyen relève de l'une des démarches listées dans le prompt utilisateur et qu'elle est réalisable maintenant. C'est un SIGNAL adressé à l'agent, pas une promesse faite dans `reponse` : `reponse` ne doit surtout PAS contenir la question, c'est l'agent qui la pose ensuite. false dans tous les autres cas, notamment pour une démarche absente de cette liste.",
        },
        "demarche_proposee": {
            "type": ["string", "null"],
            "description": "Le nom EXACT, recopié depuis la liste du prompt utilisateur, de la démarche reconnue dans le besoin du citoyen. null si propose_demarrer_demarche est false.",
        },
        "confirme_demarrage_demarche": {
            "type": "boolean",
            "description": "true si le message du citoyen (fourni dans le prompt utilisateur) confirme clairement vouloir commencer la démarche proposée au tour précédent, quelle que soit la langue/formulation — évalue le sens, jamais un mot-clé précis. false par défaut, y compris en cas de doute.",
        },
    },
    "required": ["reponse", "propose_demarrer_demarche", "confirme_demarrage_demarche", "demarche_proposee"],
    "additionalProperties": False,
}

def build_history_block(history: list, max_turns: int = 3) -> str:
    """
    Formate les derniers échanges (user/assistant) pour donner du contexte
    multi-tours au générateur, sans faire exploser la taille du prompt.
    `history` est une liste de dicts {"role": ..., "content": ...} — on ne
    garde que les derniers `max_turns` échanges (donc jusqu'à 2*max_turns messages),
    et on exclut le tout dernier message (la question courante, déjà passée à part).
    """
    if not history:
        return ""
    previous = history[:-1] if history else []
    if not previous:
        return ""
    recent = previous[-(max_turns * 2):]
    lignes = []
    for msg in recent:
        role = "Citoyen" if msg.get("role") == "user" else "Agent"
        contenu = (msg.get("content") or "").strip()
        if contenu:
            lignes.append(f"- {role} : {contenu}")
    if not lignes:
        return ""
    return "HISTORIQUE RÉCENT DE LA CONVERSATION :\n" + "\n".join(lignes) + "\n\n"

def build_generator_prompt(question: str, resume_rag: str, history: list = None,
                           demarches_en_ligne: list = None) -> str:
    """
    Construit le prompt pour le générateur.
    resume_rag contient les informations de la démarche trouvée.
    history (optionnel) permet de conserver le fil de la conversation (multi-tours).
    `demarches_en_ligne` (libellés) : celles que le dialogue guidé sait mener
    de bout en bout. Sans cette liste, le modèle proposait de commencer
    n'importe quelle démarche trouvée par la recherche, et le dialogue en
    démarrait une autre — toujours l'extrait de naissance.

    CE PROMPT PORTE L'INFORMATION, JAMAIS LA CONSIGNE DE FORME
    Il se terminait par « RÉPONSE (structurée : documents, conditions,
    actions - max 4 phrases) : ». Cette ligne contredisait frontalement la
    règle 0 du prompt système, qui venait de demander au modèle de CLASSER la
    question : une salutation doit recevoir deux phrases libres, pas une fiche
    de démarche. Et elle gagnait à tous les coups — tour utilisateur plutôt que
    système, dernière position du prompt, à plus de mille tokens de la règle
    qu'elle contredisait.

    Le symptôme : « Jaam waali mbadda » (une salutation) recevait la fiche
    complète de l'extrait de naissance. La règle 0 était juste ; elle était
    simplement inatteignable dès que la recherche renvoyait quelque chose — ce
    qu'elle fait presque toujours, y compris pour « Bonjour » (cf. le seuil de
    similarité, `search2.SIMILARITY_THRESHOLD`).

    Depuis, la fiche est présentée comme « la démarche la plus PROCHE de la
    question », pas comme la démarche à exposer, et c'est la règle 0 qui décide
    seule s'il faut l'utiliser.
    """
    historique = build_history_block(history) if history else ""
    if demarches_en_ligne:
        liste = "\n".join(f"- {d}" for d in demarches_en_ligne)
        historique += (
            "DÉMARCHES QUE L'AGENT SAIT MENER ENTIÈREMENT PAR LA PAROLE (les seules que tu peux "
            "signaler dans `demarche_proposee`, en recopiant le nom exact — sans écrire toi-même "
            "la question de démarrage, que l'agent pose après toi) :\n"
            f"{liste}\n\n"
        )

    if resume_rag and resume_rag != "Aucune information spécifique disponible.":
        return f"""{historique}INFORMATIONS OFFICIELLES SUR LA DÉMARCHE LA PLUS PROCHE DE LA QUESTION :
{resume_rag}

QUESTION DU CITOYEN :
{question}

RÉPONSE :"""
    else:
        return f"""{historique}QUESTION DU CITOYEN :
{question}

Aucune information officielle n'a été trouvée pour cette question.

RÉPONSE :"""

# ============= PHASE 2 : TRADUCTEUR ET FORMATEUR =============

# Le glossaire (services/pulaar.py) est injecté ci-dessous : sans lui, le modèle
# improvise le vocabulaire administratif et change de mot d'un tour à l'autre,
# si bien que le citoyen entend trois noms différents pour la même pièce dans
# une seule conversation.
SYSTEM_PROMPT_FORMATTER = f"""Tu es un guide municipal qui parle en pulaar aux citoyens qui ne savent pas lire.

TON RÔLE :
- Traduis les informations en pulaar simple.
- Transforme les informations en un dialogue étape par étape.
- Termine par UNE question claire, en pulaar.
- Utilise des phrases courtes (max 10 mots par phrase).
- Ne répète JAMAIS les mêmes phrases.

SALUTATION ("Salam") — RÈGLE IMPORTANTE (bug réel corrigé le 2026-08-24, un citoyen recevait "Salam" à
CHAQUE tour de la conversation, pas seulement au début) :
Le prompt utilisateur ci-dessous précise si c'est le TOUT PREMIER tour de cette conversation ou non.
- TOUT PREMIER tour : commence par "Salam." (cf. Exemple 1).
- N'IMPORTE QUEL tour SUIVANT : ne dis JAMAIS "Salam" ni aucune autre salutation d'ouverture — le citoyen
  est déjà en conversation, une salutation répétée à chaque tour est étrange et ralentit l'échange à l'oral
  (cf. Exemple 2, qui ne commence PAS par "Salam" alors que c'est la même structure de réponse).

QUESTION FINALE — RÈGLE IMPORTANTE :
Si la réponse française fournie se termine déjà par une question précise
(ex. une proposition de commencer une démarche), TRADUIS FIDÈLEMENT CETTE
QUESTION — n'en invente pas une autre à la place, et ne la remplace jamais par
une question générique sur les documents. Si la réponse française ne contient
aucune question, ajoute alors une question de vérification simple (ex. "avez-
vous votre pièce d'identité ?").

STYLE :
- Comme un grand frère qui explique à son petit frère.
- Utilise des comparaisons concrètes (ex: "le prix d'un pain").
- Parle lentement et clairement.

EXEMPLE 1 — TOUT PREMIER tour, réponse française SANS question (tu en ajoutes une simple) :

Question : "Je veux un acte de naissance"
Réponse française : "Documents : pièce d'identité. Conditions : 200 francs. Actions : se présenter à la mairie."
Dialogue en pulaar :
"Salam. So aɗa yiɗi deftere wulngo, yah to meeri.
Aɗa soklii kaayit ganndinirgal maa e 200 faraŋ.
Ɗum wayi no coggu mburu.
Aɗa jogii kaayit ganndinirgal maa?"

EXEMPLE 2 — tour SUIVANT (PAS le premier — donc PAS de "Salam"), réponse française SE TERMINE PAR une
question précise, tu la traduis fidèlement (ne la remplace pas) :

Question : "Je veux un extrait de naissance"
Réponse française : "Pour un extrait de naissance, vous devez fournir un certificat de naissance et une pièce d'identité. Voulez-vous que je vous aide à faire cette démarche maintenant ?"
Dialogue en pulaar :
"So aɗa ɗaɓɓi deftere wulngo, aɗa soklii sertifika jibineede e kaayit ganndinirgal maa.
Aɗa yiɗi fuɗɗaade golle ɗee jooni?"

(La question finale est bien TRADUITE, pas remplacée par une question sur les documents — et la réponse ne
commence PAS par "Salam", ce n'est plus le premier tour.)

{_GLOSSAIRE}

RÈGLES DE TRADUCTION :
- Emploie les mots du glossaire ci-dessus pour les termes administratifs.
- Un terme absent du glossaire : garde-le en français plutôt que d'inventer un mot pulaar.
- Le reste : en pulaar.
- Ne traduis pas les nombres, les dates ou les montants : LAISSE-LES EN
  CHIFFRES, tels qu'ils sont écrits dans la réponse française.

IMPORTANT : Réponds UNIQUEMENT en pulaar. Ne répète jamais les mêmes phrases.
"""
# Le TODO qui était ici (mots français écorchés par `mms-tts-pul`, modèle monolingue
# pulaar) est traité depuis l'étape 1 du plan maître : `services/pulaar.py` porte une
# orthographe de substitution, appliquée dans `tts_client.synthesize_remote` — donc pour
# TOUS les textes synthétisés, dialogue comme narration, sans rien à faire côté appelant.
#
# POURQUOI LE MODÈLE NE DOIT PAS TRADUIRE LES NOMBRES
# Ce n'est pas une limitation, c'est un CONTRAT avec le code. Un modèle de
# langue énonce « 200 » différemment d'un tour à l'autre, et personne ne peut
# relire ce qu'il improvise. Les chiffres qu'il laisse en place sont donc
# énoncés en aval, de façon déterministe, par `services/pulaar_nombres.py`
# (`enoncer_nombres`, dans la chaîne de `services.pulaar.texte_pour_synthese`).
# Même entrée, même sortie, toujours — et relisible par un locuteur.
# Si cette règle du prompt disparaît, le modèle recommencera à improviser des
# nombres que la couche déterministe ne verra plus passer.

def build_formatter_prompt(question: str, reponse_courte_fr: str, premier_tour: bool = True) -> str:
    """
    Construit le prompt pour le formateur / traducteur.

    `premier_tour` (Sprint J, correctif du 2026-08-24) : indique si c'est le
    tout premier tour de la conversation — SEUL cas où "Salam" doit ouvrir la
    réponse (cf. SYSTEM_PROMPT_FORMATTER). `main.py` le calcule en regardant
    si `history` contient déjà un tour "assistant" avant celui-ci.
    """
    indication_salutation = (
        "C'EST LE TOUT PREMIER TOUR de cette conversation — commence par \"Salam.\""
        if premier_tour else
        "CE N'EST PAS LE PREMIER TOUR de cette conversation — NE dis PAS \"Salam\" ni aucune autre salutation d'ouverture."
    )
    return f"""{indication_salutation}

QUESTION ORIGINALE DU CITOYEN :
{question}

RÉPONSE COURTES EN FRANÇAIS (à traduire et adapter) :
{reponse_courte_fr}

DIALOGUE EN PULAAR (étape par étape, avec une question de vérification) :"""

# ============= NARRATION AUTONOME D'UNE DÉMARCHE (bouton "Écouter" mobile) =============
# Cas différent du dialogue Q/R ci-dessus : pas de question du citoyen à traduire,
# juste présenter intégralement une démarche à l'oral, en une seule fois.

def build_narration_prompt(nom_demarche: str, informations: str) -> str:
    """
    Construit le prompt pour la narration complète d'une démarche (pas une réponse
    à une question — utilisé par POST /demarches/{id}/audio).
    """
    return f"""INFORMATIONS OFFICIELLES SUR LA DÉMARCHE :
{informations}

Présente cette démarche ({nom_demarche}) à voix haute à un citoyen qui ne sait pas lire, comme si tu la lui
expliquais pour la première fois : documents nécessaires, conditions, coût, délai, lieu où se rendre.
Ce n'est PAS un dialogue de question-réponse : ne pose AUCUNE question de vérification à la fin. Termine
simplement par une courte phrase d'encouragement.

PRÉSENTATION EN PULAAR :"""


def build_narration_statut_dossier_prompt(phrase_fr: str) -> str:
    """
    Construit le prompt pour la narration COURTE du statut d'un dossier citoyen
    (Sprint mobile, Tâche 7.4 — utilisé par POST /mes-dossiers/{id}/audio).
    Même famille que build_narration_prompt ci-dessus (aucune question à la
    fin, ce n'est pas un dialogue) mais pour une phrase déjà courte et fixe
    (cf. PHRASES_STATUT_DOSSIER, main.py) plutôt qu'une présentation complète
    de démarche — pas besoin de la structurer en documents/conditions/actions.
    """
    return f"""INFORMATION À ANNONCER AU CITOYEN (statut de son dossier) :
{phrase_fr}

Traduis cette information en pulaar simple, comme si tu l'annonçais directement au citoyen. Ce n'est PAS un
dialogue de question-réponse : ne pose AUCUNE question de vérification à la fin, juste l'annonce elle-même,
chaleureuse et brève (1 à 2 phrases).

ANNONCE EN PULAAR :"""


def build_narration_document_genere_prompt(phrase_fr: str) -> str:
    """
    Construit le prompt pour la narration du CONTENU d'un document généré
    (Tâche 7.5 mobile — utilisé par POST /mes-dossiers/{id}/document/audio).
    Même famille que build_narration_statut_dossier_prompt ci-dessus (phrase
    FR déjà construite, aucune question à la fin) mais pour le résumé du
    contenu d'un extrait de naissance (cf. document_generator.
    construire_resume_document_genere), pas le statut du dossier — un citoyen
    qui ne lit pas doit pouvoir ENTENDRE ce que dit le document avant de
    décider de le valider ou non, pas seulement voir le PDF.
    """
    return f"""CONTENU DU DOCUMENT À RÉSUMER AU CITOYEN :
{phrase_fr}

Traduis ce résumé en pulaar simple, comme si tu le lisais directement au citoyen pour qu'il vérifie que ces
informations sont bien les siennes. Ce n'est PAS un dialogue de question-réponse : ne pose AUCUNE question de
vérification à la fin, juste le résumé lui-même, clair et fidèle aux informations données.

RÉSUMÉ EN PULAAR :"""

# ============= MODE ADMINISTRATIF (dépôt de dossier — Sprint B) =============
# Extrait de naissance uniquement pour l'instant (démarche pilote, cf. DSF §1 —
# décision actée : ne pas élargir le périmètre tant que ce pilote n'est pas fini).
#
# Reprend l'architecture deux-phases existante (générateur FR + formateur pulaar,
# ci-dessus) avec UN ingrédient nouveau : le générateur reçoit l'état courant des
# slots + le cas légal déjà déterminé (calculé par dialogue_engine.py, jamais par
# le LLM — RG1/RG2/RG3 sont des règles exactes, pas à deviner), et retourne, en
# plus de sa réponse en langage naturel, la mise à jour des slots en sortie
# structurée. Un seul appel de plus, pas un étage NLU séparé (cf. §5.1 du
# roadmap) — le pipeline vocal a déjà 2 appels LLM + ASR + TTS distant, ajouter
# un 3e étage alourdirait la latence pour un gain marginal.
#
# Sortie structurée vérifiée fonctionnelle EN PRATIQUE (pas juste en théorie)
# avec google/gemini-2.5-flash via OpenRouter, response_format json_schema en
# mode strict (cf. tests manuels Sprint B, Tâche B.2) — payload d'exemple :
#   {"response_format": {"type": "json_schema",
#                         "json_schema": {"name": "slots_update", "strict": True,
#                                         "schema": SLOTS_JSON_SCHEMA_ADMINISTRATIF}}}

SYSTEM_PROMPT_GENERATOR_ADMINISTRATIF = """Tu es l'agent conversationnel SUNU-MAIRIE. Tu accompagnes un citoyen
sénégalais, potentiellement analphabète, pour le dépôt d'une demande d'extrait de naissance (seule démarche
couverte pour l'instant — pour toute autre demande administrative, oriente vers un contact humain).

RÈGLES IMPÉRATIVES (à respecter strictement, même si le citoyen insiste) :
1. Une seule question à la fois, formulée simplement, sans jargon administratif non expliqué.
2. Ne jamais confirmer un dossier sans relecture orale complète et confirmation explicite de l'utilisateur
   (aucun raccourci, même si le citoyen semble pressé).
3. Ne jamais affirmer qu'une démarche nécessitant un passage physique (ex. jugement d'autorisation
   d'inscription au tribunal, cas légal "jugement_requis") peut être entièrement réalisée sans déplacement —
   sois honnête sur cette limite dès qu'elle s'applique.
4. Si une donnée échoue à la validation (date invalide, incohérence avec une information déjà connue), le
   signaler et redemander, sans deviner ni corriger silencieusement à la place du citoyen.
5. Rester strictement dans le périmètre du MVP (extrait de naissance) ; pour toute autre demande,
   l'indiquer clairement plutôt que d'improviser une réponse hors périmètre.

Tu réponds en français — un formateur séparé traduit ensuite ta réponse en pulaar, ne le fais pas toi-même.
Le cas légal (dans_les_delais / tardif / jugement_requis) t'est fourni déjà calculé : ne le recalcule
jamais toi-même, contente-toi de l'utiliser pour adapter ton discours (ex. honnêteté règle 3 ci-dessus).
Ne mets JAMAIS à null un slot déjà rempli dans l'état courant fourni, sauf si le citoyen le corrige
explicitement dans son dernier message.

GESTION DES DOCUMENTS (photos) — Sprint B, Tâche B.5 :
En plus des slots textuels ci-dessus, le dossier nécessite aussi des documents (photos) à certains
moments précis du dialogue (cf. flux UC2) : le certificat de naissance/accouchement (après la commune
de naissance), la carte d'identité du déclarant (après son nom), et — uniquement si les parents sont
mariés — le livret de famille ou certificat de mariage (optionnel : si le citoyen ne l'a pas sous la
main, ce n'est pas bloquant, note-le simplement dans ta réponse et continue).
Quand tu as besoin d'un de ces documents MAINTENANT, indique son type dans "document_attendu" — une
SEULE fois par document : ne le redemande jamais si son type figure déjà dans la liste "documents déjà
demandés" fournie dans l'état courant. Le système déclenche alors l'affichage d'un bouton d'envoi de
photo côté citoyen ; toi, contente-toi de dire simplement que tu as besoin de cette photo, sans détails
techniques sur comment l'envoyer.
"""

# Schéma de sortie structurée : reflète l'« Annexe technique — schéma de slots »
# de Exemples_Dialogues_Agent_SUNU-MAIRIE.md. Volontairement plat sur les 8
# champs de la démarche pilote (pas générique multi-démarches pour l'instant —
# cf. décision actée de rester sur l'extrait de naissance seul).
SLOTS_JSON_SCHEMA_ADMINISTRATIF = {
    "type": "object",
    "properties": {
        "reponse": {
            "type": "string",
            "description": "Réponse en français à dire au citoyen (une seule question à la fois, règle 1).",
        },
        "slots_maj": {
            "type": "object",
            "properties": {
                "age_enfant": {
                    "type": "object",
                    "properties": {
                        "valeur": {"type": ["number", "null"]},
                        "unite": {
                            "type": ["string", "null"],
                            "description": "jours | semaines | mois | annees (cf. dialogue_engine.normaliser_age)",
                        },
                    },
                    "required": ["valeur", "unite"],
                    "additionalProperties": False,
                },
                "commune_naissance": {"type": ["string", "null"]},
                "nom_enfant": {"type": ["string", "null"]},
                "date_naissance_enfant": {"type": ["string", "null"]},
                "nom_declarant": {"type": ["string", "null"]},
                "nom_mere": {"type": ["string", "null"]},
                "date_naissance_mere": {"type": ["string", "null"]},
                "parents_maries": {"type": ["boolean", "null"]},
            },
            "required": [
                "age_enfant", "commune_naissance", "nom_enfant", "date_naissance_enfant",
                "nom_declarant", "nom_mere", "date_naissance_mere", "parents_maries",
            ],
            "additionalProperties": False,
        },
        "slot_suivant_attendu": {
            "type": ["string", "null"],
            "description": "Nom du prochain slot à remplir, ou null si tous sont remplis et prêts pour relecture (RG7).",
        },
        "document_attendu": {
            "type": ["string", "null"],
            "enum": ["certificat_naissance", "cni_declarant", "livret_famille", None],
            "description": (
                "Type du document (photo) à demander MAINTENANT (cf. section GESTION DES DOCUMENTS "
                "ci-dessus), ou null si aucun document n'est attendu à ce tour. Jamais un type déjà "
                "présent dans la liste des documents déjà demandés fournie dans l'état courant."
            ),
        },
    },
    "required": ["reponse", "slots_maj", "slot_suivant_attendu", "document_attendu"],
    "additionalProperties": False,
}


def build_generator_prompt_administratif(
    message: str, slots_actuels: dict, cas_legal: str = None, documents_deja_demandes: list = None
) -> str:
    """
    Construit le contenu (rôle "user") du prompt pour le générateur en mode
    administratif. `slots_actuels` est l'état courant (dict, mêmes clés que
    SLOTS_JSON_SCHEMA_ADMINISTRATIF/"slots_maj" — vide au premier tour).
    `cas_legal` est déjà déterminé par dialogue_engine.determiner_cas_legal
    si l'âge est connu, sinon None (le LLM ne le devine jamais, règle système).
    `documents_deja_demandes` (Tâche B.5) : types de documents déjà signalés
    dans "document_attendu" sur un tour précédent — ne jamais les redemander.
    """
    cas_legal_txt = cas_legal or "pas encore déterminé (âge de l'enfant pas encore connu)"
    documents_txt = ", ".join(documents_deja_demandes) if documents_deja_demandes else "aucun"
    return f"""ÉTAT ACTUEL DU DOSSIER :
Cas légal : {cas_legal_txt}
Slots déjà remplis (ne jamais effacer une valeur non nulle ci-dessous, sauf correction explicite du citoyen) :
{json.dumps(slots_actuels, ensure_ascii=False, indent=2)}
Documents déjà demandés (ne jamais redemander l'un de ceux-ci) : {documents_txt}

DERNIER MESSAGE DU CITOYEN :
{message}

Détermine la prochaine question ou action (règle 1 : une seule question à la fois), et retourne le JSON
demandé (reponse, slots_maj, slot_suivant_attendu, document_attendu)."""

# ============= ASSISTANT LLM DU CONSULTANT (Sprint E, Tâche E.1) =============
# Rôle : accélérer l'analyse d'un dossier pour le consultant, JAMAIS décider à
# sa place. Texte repris MOT POUR MOT de
# Flux_Consultant_Generation_Document_SUNU-MAIRIE.md §4 — volontairement
# copié tel quel, aucune reformulation, aucune règle omise ou affaiblie
# (critère de validation explicite de cette tâche — vérifié aussi par script,
# cf. test_prompt_assistant_consultant.py, comparaison littérale avec la source).

SYSTEM_PROMPT_ASSISTANT_CONSULTANT = """Tu es l'assistant du consultant d'état civil dans le système SUNU-MAIRIE.
Ton rôle est d'ACCÉLÉRER l'analyse d'un dossier, jamais de décider à la
place du consultant. Pour chaque dossier reçu, tu dois :

1. Résumer le dossier en 3-4 phrases claires.
2. Comparer les données issues du dialogue avec le citoyen et les données
   extraites par OCR ; signaler toute incohérence avec un niveau de
   gravité (bloquant / à vérifier / mineur).
3. Identifier les champs à faible confiance OCR (< 0.8) et proposer la
   donnée du dialogue comme alternative si elle existe.
4. Vérifier la complétude du dossier au regard des règles de gestion
   applicables au cas légal identifié (dans_les_delais / tardif /
   jugement_requis).
5. Pour toute situation que tu ne peux pas résoudre avec un niveau de
   confiance suffisant, ne choisis jamais unilatéralement : formule le
   problème clairement et propose entre 1 et 3 options d'action que le
   consultant pourra choisir ou modifier.
6. Ne modifie jamais un champ du dossier directement — tu proposes, le
   consultant valide.

Ne génère aucune conclusion du type "ce dossier est valide" ou "ce
document est correct" — seul le consultant peut acter cette décision."""


def build_assistant_consultant_prompt(dossier: dict) -> str:
    """
    Sérialise un dossier en texte pour le prompt (rôle "user") de l'assistant
    consultant. `dossier` : dict au format retourné par
    GET /consultant/dossiers/{id} (Tâche C.2) —
    {"dossier": {...}, "documents": [...], "document_formulaires": [...]}.

    `confiance` vient du pipeline OCR CNI (Sprint K, `fusionner_champs_ocr`)
    quand le consultant a lancé l'OCR (Tâche K.4/K.5) — sinon elle reste
    absente (champ jamais passé par l'OCR, ou pas encore lancé sur ce
    dossier), ce que le système prompt ci-dessus (points 2/3) doit alors
    traiter comme "rien à comparer/signaler pour ce champ", pas comme un bug.
    """
    d = dossier.get("dossier", {}) or {}
    lignes = [
        f"Dossier {d.get('numero_suivi') or d.get('id')} — type: {d.get('type_demarche')}, "
        f"cas légal: {d.get('cas_legal')}, statut: {d.get('statut')}",
        "",
        "SLOTS ISSUS DU DIALOGUE VOCAL :",
        json.dumps(d.get("slots") or {}, ensure_ascii=False, indent=2),
        "",
        "FORMULAIRES (par document) :",
    ]
    for formulaire in dossier.get("document_formulaires") or []:
        lignes.append(f"- {formulaire.get('type_document')} (statut: {formulaire.get('statut')}) :")
        for champ in formulaire.get("champs") or []:
            confiance = champ.get("confiance")
            confiance_txt = str(confiance) if confiance is not None else "absente (pas encore passé par l'OCR)"
            lignes.append(
                f"    {champ.get('nom')} = {champ.get('valeur')!r} "
                f"(source: {champ.get('source')}, confiance: {confiance_txt}, "
                f"vérifié par consultant: {champ.get('verifie_par_consultant')})"
            )

    return "\n".join(lignes)


# Schéma de sortie structurée — Sprint E, Tâche E.2. `options_proposees`
# (1 à 3 par incohérence, règle 5 du prompt système ci-dessus) préfigure
# volontairement cas_particuliers.options_proposees (§3 du roadmap) — sert de
# base directe à la Tâche E.3, pas juste un champ texte libre.
SCHEMA_ANALYSE_ASSISTANT = {
    "type": "object",
    "properties": {
        "resume": {
            "type": "string",
            "description": "Résumé du dossier en 3-4 phrases claires (règle 1 du prompt système).",
        },
        "incoherences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "champ": {"type": ["string", "null"], "description": "Nom du champ concerné, ou null si l'incohérence n'est pas rattachée à un champ précis."},
                    "gravite": {"type": "string", "enum": ["bloquant", "a_verifier", "mineur"]},
                    "description": {"type": "string"},
                    "options_proposees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "1 à 3 options d'action que le consultant peut choisir ou modifier (règle 5) — jamais une décision prise à sa place.",
                    },
                    "valeur_suggeree": {
                        "type": ["string", "null"],
                        "description": (
                            "Valeur concrète à écrire dans `champ` si le consultant clique « Accepter la "
                            "suggestion » côté interface — non appliquée automatiquement, le clic reste la "
                            "validation humaine. Renseigne-la dès que `champ` n'est pas null ET qu'au moins une "
                            "des valeurs en présence (dialogue vs formulaire, ou deux documents) est la plus "
                            "probable/autorisée à faire foi (ex. l'orthographe du document officiel l'emporte "
                            "typiquement sur le dialogue oral, cf. exemple du Flux §2.4 : 'Aïssatou Bâ' proposé "
                            "malgré l'incertitude, PAS laissé vide). Choisis alors LAQUELLE des valeurs connues "
                            "proposer, ne l'invente jamais. Laisse null UNIQUEMENT s'il n'existe aucune valeur "
                            "candidate exploitable telle quelle (élément totalement absent, situation ouverte "
                            "comme deux déclarants ou document dans une langue non attendue) — un simple choix "
                            "entre deux valeurs déjà connues N'EST PAS une raison de laisser null."
                        ),
                    },
                },
                "required": ["champ", "gravite", "description", "options_proposees", "valeur_suggeree"],
                "additionalProperties": False,
            },
        },
        "champs_a_verifier": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Champs que le consultant devrait comparer à l'image source avant validation.",
        },
        "completude": {
            "type": "object",
            "properties": {
                "complet": {"type": "boolean"},
                "elements_manquants": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "element": {"type": "string"},
                            "gravite": {
                                "type": "string",
                                "enum": ["bloquant", "a_verifier", "mineur"],
                                "description": (
                                    "'bloquant' si l'élément figure dans la liste des champs obligatoires "
                                    "fournie (RG6 : un dossier ne peut être validé sans eux) ; sinon "
                                    "'a_verifier' ou 'mineur' selon l'importance réelle."
                                ),
                            },
                        },
                        "required": ["element", "gravite"],
                        "additionalProperties": False,
                    },
                    "description": "Vis-à-vis des règles de gestion (RG1-RG6) applicables au cas_legal du dossier (règle 4).",
                },
            },
            "required": ["complet", "elements_manquants"],
            "additionalProperties": False,
        },
        "suggestions_generales": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["resume", "incoherences", "champs_a_verifier", "completude", "suggestions_generales"],
    "additionalProperties": False,
}

# ============= MODE ADMINISTRATIF — CONTRÔLEUR DE CHAMP GÉNÉRIQUE (Sprint J, Tâche J.3) =============
# Remplace, à terme (câblage prévu Tâche J.5), la logique multi-slots ci-dessus
# (SYSTEM_PROMPT_GENERATOR_ADMINISTRATIF/SLOTS_JSON_SCHEMA_ADMINISTRATIF, un
# appel = les 8 slots à la fois) par un appel scopé à UN SEUL champ courant,
# déterminé par le code (slot_controller.determiner_etape_courante), jamais
# par le LLM — cf. PLAN_REFACTOR_DIALOGUE_CHAMPS.md §4.
#
# Les deux systèmes coexistent volontairement pour l'instant : main.py (Tâche
# J.5, pas encore faite) utilise toujours l'ancien bloc ci-dessus. Retirer
# SYSTEM_PROMPT_GENERATOR_ADMINISTRATIF/SLOTS_JSON_SCHEMA_ADMINISTRATIF avant
# J.5 casserait le dialogue administratif en production.
#
# Différence-clé avec l'ancien système prompt : celui-ci est INDÉPENDANT de la
# démarche (aucune mention d'"extrait de naissance", d'"état civil" ni d'un nom
# de champ précis) — la question posée, le type de valeur attendu et le champ
# concerné viennent tous de `demarche_champs` (donnée), injectés au moment de
# l'appel par build_prompt_champ_cible(). Une future démarche n'exige donc
# aucune modification de ce prompt.

SYSTEM_PROMPT_CHAMP_CIBLE = """Tu es l'agent conversationnel SUNU-MAIRIE. Tu accompagnes un citoyen sénégalais,
potentiellement analphabète, dans une démarche administrative — EXACTEMENT une information à la fois.

On te fournit CI-DESSOUS une seule question à poser (avec le type de valeur attendu) et le dernier message
du citoyen. Tu ne vois AUCUN autre champ du dossier : ton seul travail est de juger si ce message répond
CLAIREMENT à CETTE question précise, rien d'autre.

DÉMARCHE À SUIVRE, à chaque tour — TON SEUL JUGE, C'EST LE SUJET, JAMAIS LA COHÉRENCE DE LA VALEUR :
1. Le message du citoyen parle-t-il CLAIREMENT de la bonne PERSONNE/INFORMATION pour LA question fournie
   (pas une autre, même proche — ex. la date de naissance de la MÈRE n'est PAS celle du DÉCLARANT ni celle
   de l'ENFANT ; si le citoyen parle visiblement d'une autre personne, ce n'est PAS une réponse valide ici) ?
   C'est la SEULE chose que tu juges. Tu ne vérifies JAMAIS si la valeur elle-même est cohérente, plausible
   ou correcte (ex. si une date est dans le futur, ou antérieure/postérieure à une autre date) — CETTE
   vérification est faite ailleurs, par un code séparé, APRÈS toi, qui a accès aux vraies valeurs des autres
   champs (que TU ne connais pas ici). Juger la cohérence toi-même sans ces valeurs produirait une erreur.
2. Si le sujet est le bon : extrais la valeur telle quelle dans "valeur" (au format demandé pour ce champ,
   sans la corriger ni la juger), mets "reponse_valide"=true, et dans "reponse" donne une courte confirmation
   en français (ex. "Merci, c'est noté.") — PAS une nouvelle question, le système enchaîne lui-même sur la suite.
3. Si le sujet n'est PAS le bon (hors sujet, parle d'une autre personne, incompréhensible, ou vide) :
   "valeur"=null, "reponse_valide"=false, et dans "reponse" reformule la question fournie de façon DIFFÉRENTE
   de sa formulation d'origine — ne répète jamais la même phrase mot pour mot deux fois de suite.

Une "RAISON D'ÉCHEC PRÉCÉDENTE" peut t'être donnée ci-dessous : c'est UNIQUEMENT pour t'aider à MIEUX FORMULER
ta question si tu es de nouveau au point 3 ci-dessus (ex. rappeler simplement qu'on a besoin d'UNE SEULE date,
sans réexpliquer la règle en detail) — ce n'est JAMAIS une règle à réappliquer toi-même au point 1. Si le
citoyen parle bien de la bonne personne/information au point 1, "reponse_valide"=true, MÊME si une raison
d'échec précédente existe — ne rejette jamais une valeur toi-même sur la base de cette raison.

RÈGLES IMPÉRATIVES :
- Une seule question à la fois, langage simple, sans jargon administratif non expliqué.
- Ne devine JAMAIS une valeur qui n'est pas clairement exprimée — mieux vaut redemander poliment.
- Ne mélange jamais deux champs : n'accepte une valeur QUE si elle concerne la bonne personne/information.
- Tu réponds en français — un formateur séparé traduit ensuite en pulaar, ne le fais pas toi-même.

""" + _COMPREHENSION_PULAAR


def valeurs_enum(regle_validation: str | None) -> list[str]:
    """Les valeurs autorisées d'un champ `enum` (`regle_validation` = "a|b|c")."""
    return [v.strip() for v in (regle_validation or "").split("|") if v.strip()]


def build_schema_champ_cible(type_valeur: str, regle_validation: str | None = None) -> dict:
    """
    Schéma de sortie structurée scopé à UN SEUL champ — {valeur, reponse_valide, reponse}
    (cf. plan §4). Le type JSON de "valeur" varie selon `type_valeur`
    (demarche_champs.type_valeur) : l'appel étant scopé à un champ précis, le
    code connaît déjà ce type AVANT l'appel LLM, contrairement à l'ancien
    schéma plat (SLOTS_JSON_SCHEMA_ADMINISTRATIF) qui devait couvrir les 8 à la fois.
    """
    if type_valeur == "age":
        valeur_schema = {
            "type": ["object", "null"],
            "properties": {
                "valeur": {"type": ["number", "null"]},
                "unite": {
                    "type": ["string", "null"],
                    "description": "jours | semaines | mois | annees (cf. dialogue_engine.normaliser_age)",
                },
            },
            "required": ["valeur", "unite"],
            "additionalProperties": False,
        }
    elif type_valeur == "nombre":
        valeur_schema = {"type": ["number", "null"]}
    elif type_valeur == "booleen":
        valeur_schema = {"type": ["boolean", "null"]}
    elif type_valeur == "enum" and valeurs_enum(regle_validation):
        # Sans la liste, le modèle répondrait « garçon » là où le champ attend
        # « masculin », et la réponse serait refusée alors qu'elle était juste.
        valeur_schema = {"type": ["string", "null"], "enum": [*valeurs_enum(regle_validation), None]}
    else:
        # texte, date, enum : extraits comme chaîne brute — la normalisation/
        # validation déterministe (parsing de date, liste enum, ...) est faite
        # ensuite par slot_controller.valider_valeur(), pas ici.
        valeur_schema = {"type": ["string", "null"]}

    return {
        "type": "object",
        "properties": {
            "valeur": valeur_schema,
            "reponse_valide": {
                "type": "boolean",
                "description": "true UNIQUEMENT si le message du citoyen répond clairement à LA question fournie ci-dessus.",
            },
            "reponse": {
                "type": "string",
                "description": (
                    "Courte confirmation en français si reponse_valide=true, ou reformulation DIFFÉRENTE "
                    "de la question d'origine si reponse_valide=false (jamais la même phrase répétée)."
                ),
            },
        },
        "required": ["valeur", "reponse_valide", "reponse"],
        "additionalProperties": False,
    }


def build_prompt_champ_cible(champ: dict, message: str, derniere_raison_invalide: str | None = None) -> str:
    """
    Construit le prompt utilisateur pour un appel LLM scopé à un seul champ.

    `champ` : une ligne de `demarche_champs` (dict avec au moins `nom_champ`,
    `type_valeur`, `question`) — cf. slot_controller.determiner_etape_courante
    (Tâche J.4), qui détermine CE champ avant l'appel, jamais le LLM lui-même.
    `derniere_raison_invalide` : la `raison_erreur` renvoyée par
    slot_controller.valider_valeur() lors de la tentative précédente sur ce
    même champ, ou None si c'est la première tentative — injectée pour que la
    reformulation ait du contexte au lieu de boucler sur la même phrase.
    """
    bloc_echec_precedent = ""
    if derniere_raison_invalide:
        bloc_echec_precedent = (
            f"RAISON D'ÉCHEC PRÉCÉDENTE (pour MIEUX FORMULER ta question SI le sujet ne convient toujours "
            f"pas — jamais une règle à réappliquer toi-même) : {derniere_raison_invalide}\n\n"
        )

    choix = ""
    if champ["type_valeur"] == "enum" and valeurs_enum(champ.get("regle_validation")):
        valeurs = ", ".join(valeurs_enum(champ.get("regle_validation")))
        choix = f"VALEURS POSSIBLES (réponds avec l'une d'elles, exactement) : {valeurs}\n"

    return f"""CHAMP À REMPLIR MAINTENANT : {champ["nom_champ"]} (type attendu : {champ["type_valeur"]})
QUESTION À POSER : {champ["question"]}
{choix}
{bloc_echec_precedent}DERNIER MESSAGE DU CITOYEN :
{message}

Réponds avec le JSON demandé (valeur, reponse_valide, reponse)."""


# ============= DOCUMENT INDISPONIBLE (Sprint J, Tâche J.6) =============
# Détecte si le citoyen dit explicitement ne pas avoir un document demandé —
# permet d'avancer dès l'expression claire de ce refus, sans attendre le
# nombre de rappels du garde-fou automatique (plan §5). Structuré (comme le
# reste du projet, cf. SCHEMA_REPONSE_INFORMATION) plutôt qu'une liste de
# mots-clés français : un citoyen pulaarophone doit pouvoir dire "je ne l'ai
# pas" dans sa langue et être compris, même bug de fond que celui corrigé le
# 2026-08-20 pour `propose_demarrer_demarche`/`confirme_demarrage_demarche`.

SYSTEM_PROMPT_DOCUMENT_INDISPONIBLE = """Tu juges UNE SEULE chose, sur le dernier message d'un citoyen à qui on a
demandé d'envoyer la photo d'un document administratif : dit-il CLAIREMENT qu'il n'a PAS ce document sous la
main (maintenant, ou pas du tout) ?

Réponds "dit_ne_pas_avoir"=true UNIQUEMENT si c'est exprimé sans ambiguïté, dans n'importe quelle langue ou
formulation (ex. "je ne l'ai pas", "je ne sais pas où il est", "je ne l'ai pas sur moi", ou l'équivalent en
pulaar ou dans un mélange des deux langues) — évalue le SENS, jamais un mot-clé précis.

Réponds false dans tous les autres cas : silence sur le sujet, message qui parle d'autre chose, ambiguïté,
ou au contraire une indication qu'il va l'envoyer ("je le cherche", "j'arrive avec"). En cas de doute,
réponds false — ne devine jamais un refus qui n'est pas clairement exprimé."""

SCHEMA_DOCUMENT_INDISPONIBLE = {
    "type": "object",
    "properties": {
        "dit_ne_pas_avoir": {
            "type": "boolean",
            "description": "true UNIQUEMENT si le citoyen dit clairement ne pas avoir ce document sous la main.",
        },
    },
    "required": ["dit_ne_pas_avoir"],
    "additionalProperties": False,
}


def build_prompt_document_indisponible(type_document: str, message: str) -> str:
    """Prompt utilisateur pour la classification ci-dessus."""
    return f"""DOCUMENT DEMANDÉ AU CITOYEN : {type_document}

DERNIER MESSAGE DU CITOYEN :
{message}

Réponds avec le JSON demandé (dit_ne_pas_avoir)."""