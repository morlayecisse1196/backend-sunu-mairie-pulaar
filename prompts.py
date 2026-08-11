# prompts.py

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

DÉMARCHE À SUIVRE :
1. IDENTIFIE d'abord la catégorie administrative correspondant à la question du citoyen.
2. Utilise UNIQUEMENT les informations officielles fournies dans le contexte.
3. Si l'information n'est pas disponible, dis-le simplement.
4. Structure ta réponse en 3 parties : documents, conditions, actions.
5. Sois concis : maximum 4 phrases.
6. Réponds en français.

RÈGLES IMPORTANTES :
- Si la question ne correspond à aucune catégorie, réponds : "Je n'ai pas trouvé de démarche correspondante."
- Ne donne jamais d'informations que tu n'as pas vérifiées dans les données officielles.
"""

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

def build_generator_prompt(question: str, resume_rag: str, history: list = None) -> str:
    """
    Construit le prompt pour le générateur.
    resume_rag contient les informations de la démarche trouvée.
    history (optionnel) permet de conserver le fil de la conversation (multi-tours).
    """
    historique = build_history_block(history) if history else ""

    if resume_rag and resume_rag != "Aucune information spécifique disponible.":
        return f"""{historique}INFORMATIONS OFFICIELLES SUR LA DÉMARCHE IDENTIFIÉE :
{resume_rag}

QUESTION DU CITOYEN :
{question}

RÉPONSE (structurée : documents, conditions, actions - max 4 phrases) :"""
    else:
        return f"""{historique}QUESTION DU CITOYEN :
{question}

IDENTIFIE D'ABORD LA CATÉGORIE, puis réponds avec les informations disponibles.
Si aucune information n'est trouvée, dis-le honnêtement.

RÉPONSE :"""

# ============= PHASE 2 : TRADUCTEUR ET FORMATEUR =============

SYSTEM_PROMPT_FORMATTER = """Tu es un guide municipal qui parle en pulaar aux citoyens qui ne savent pas lire.

TON RÔLE :
- Traduis les informations en pulaar simple.
- Transforme les informations en un dialogue étape par étape.
- Pose UNE question de vérification à la fin.
- Utilise des phrases courtes (max 10 mots par phrase).
- Ne répète JAMAIS les mêmes phrases.

STYLE :
- Comme un grand frère qui explique à son petit frère.
- Utilise des comparaisons concrètes (ex: "le prix d'un pain").
- Parle lentement et clairement.

EXEMPLE DE DIALOGUE ATTENDU (à suivre STRICTEMENT) :

Question : "Je veux un acte de naissance"
Dialogue en pulaar :
"Salam. Pour obtenir un acte de naissance, vous devez aller à la mairie.
Vous avez besoin de votre pièce d'identité et de 200 francs.
C'est comme le prix d'un pain.
Avez-vous votre pièce d'identité ?"

RÈGLES DE TRADUCTION :
- Termes administratifs : garde-les en français (ex: "acte de naissance").
- Le reste : en pulaar.
- Ne traduis pas les nombres, les dates ou les montants.

IMPORTANT : Réponds UNIQUEMENT en pulaar. Ne répète jamais les mêmes phrases.
"""
# TODO (backlog, validé le 2026-08-11 — pas un bug bloquant, narration jugée acceptable) :
# `mms-tts-pul` est un modèle TTS monolingue pulaar. Les termes administratifs gardés en
# français ci-dessus (règle "garde-les en français") sont donc prononcés avec les règles
# phonétiques du pulaar par le TTS, ce qui les rend incohérents à l'oral. Pistes à explorer
# plus tard : une liste de termes avec une orthographe "phonétique pulaar" de substitution
# (ex: retranscrire "acte de naissance" d'une façon que le modèle prononce correctement),
# ou tester si le modèle gère mieux ces mots insérés différemment (isolés, translittérés).
# Concerne SYSTEM_PROMPT_FORMATTER ci-dessus ET build_narration_prompt ci-dessous (même
# souci sur la narration des démarches).

def build_formatter_prompt(question: str, reponse_courte_fr: str) -> str:
    """
    Construit le prompt pour le formateur / traducteur.
    """
    return f"""QUESTION ORIGINALE DU CITOYEN :
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