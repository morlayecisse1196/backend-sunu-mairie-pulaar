"""
Recherche des démarches (RAG) pour le mode information.

Sémantique (pgvector, search2.py) puis repli mot-clé (Supabase REST,
search.py), exécutée dans un thread : l'encodage sentence-transformers et la
connexion Postgres sont synchrones et bloquaient auparavant l'event loop du
WebSocket pendant chaque tour. Ne lève jamais d'exception : un incident RAG ne
doit pas faire tomber le tour de conversation.

Les modules search2/search sont importés à la première utilisation : search2
charge le modèle d'embeddings à l'import (plusieurs secondes), inutile pour les
routes qui n'en ont pas besoin ni pour les tests.
"""
from __future__ import annotations

import asyncio

from services import pulaar
from services.journal import obtenir_logger

log = obtenir_logger("rag")


def _rechercher_sync(question: str, commune: str | None, limite: int) -> list:
    # Les termes pulaar validés sont remplacés par leur équivalent français
    # AVANT l'encodage : le modèle d'embeddings ne connaît pas le pulaar, et
    # une demande explicite y tombait dans la même bande que les salutations
    # (cf. SEUIL_CONFIANCE plus bas, et services/pulaar.vers_francais pour les
    # mesures). La question du citoyen n'est pas modifiée ailleurs : on ne
    # réécrit que ce qui part à la recherche.
    question = pulaar.vers_francais(question)
    try:
        from search2 import search_demarches as recherche_semantique

        resultats = recherche_semantique(question, commune=commune, limit=limite)
        if resultats:
            return resultats
        # Zéro résultat n'est PAS une réponse : la table des vecteurs peut être
        # vide (script de génération jamais passé), et l'agent se retrouvait
        # alors sans aucune information officielle, sans la moindre erreur.
        log.warning("RAG sémantique sans résultat — repli mot-clé")
    except Exception as exc:  # noqa: BLE001
        log.warning("RAG sémantique indisponible (%s) — repli mot-clé", type(exc).__name__)
    try:
        from search import search_demarches as recherche_mot_cle

        return recherche_mot_cle(question, commune=commune, limit=limite)
    except Exception as exc:  # noqa: BLE001
        log.warning("RAG mot-clé indisponible (%s) — aucune démarche", type(exc).__name__)
        return []


async def rechercher_demarches(question: str, commune: str | None, limite: int = 3) -> list:
    return await asyncio.to_thread(_rechercher_sync, question, commune, limite)


def diagnostic(question: str = "extrait de naissance") -> dict:
    """
    La recherche sémantique répond-elle ?

    Elle tombe en silence : `_rechercher_sync` bascule sur la recherche par
    mots-clés et la conversation continue, en moins bien. Une base injoignable
    ou un mot de passe changé dans `.env` peut donc dégrader toutes les
    réponses du mode information pendant des semaines sans que personne le
    voie. Ce diagnostic est fait pour être MONTRÉ, pas journalisé.
    """
    try:
        from search2 import search_demarches as recherche_semantique

        if recherche_semantique(question, commune=None, limit=1):
            return {"semantique": True, "detail": "La recherche sémantique répond."}
        # Elle répond, mais ne trouve rien : la table des vecteurs est vide ou
        # incomplète. Sans ce cas, la panne restait invisible.
        return {
            "semantique": False,
            "detail": (
                "La recherche sémantique ne trouve aucune fiche : les vecteurs n'ont pas été "
                "générés. Lancez `seed_embeddings.py` avec le Python du venv, puis rechargez "
                "cette page."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        # Le détail technique reste ici (écran d'administration), sans jamais
        # recopier l'URL de connexion : elle porte le mot de passe.
        return {
            "semantique": False,
            "detail": (
                f"Recherche sémantique indisponible ({type(exc).__name__}). "
                f"L'agent répond avec la recherche par mots-clés, moins précise. "
                f"Vérifiez DATABASE_URL dans le .env du backend (mot de passe de la base "
                f"changé ?) puis redémarrez le backend."
            ),
        }


#: Ce que l'agent dit quand la base ne renseigne pas un point. Il ne doit
#: jamais combler un vide : un coût inventé fait venir un citoyen avec la
#: mauvaise somme, un délai inventé lui fait rater une échéance légale.
INCONNU = "non renseigné — dis-le et invite à se renseigner auprès de la mairie"

#: L'oral impose la brièveté : on transmet ce qui sert à répondre, pas la
#: fiche entière.
MAX_ELEMENTS = 5
MAX_CARACTERES = 400

#: En dessous de cette similarité, la démarche trouvée est la PLUS PROCHE du
#: message, pas forcément celle qu'on y demande — et le modèle doit le savoir.
#:
#: POURQUOI UNE CONFIANCE PLUTÔT QU'UN SEUIL PLUS HAUT
#: `search2.SIMILARITY_THRESHOLD` vaut 0,35, ce qui laisse passer presque
#: toutes les salutations : mesuré sur le modèle d'embeddings du projet,
#: « Bonjour » accroche « Extrait de naissance » à 0,493 et « Jaam waali
#: mbadda » à 0,431, quand une vraie demande est à 0,749. Sur quinze
#: salutations testées, douze franchissent 0,35.
#:
#: Monter le seuil règlerait les salutations et casserait le pulaar : la
#: demande « mi yiɗi deftere wulngo » (« je veux un extrait de naissance »)
#: tombe à 0,407, dans la même bande que les salutations françaises, parce que
#: le modèle d'embeddings ne connaît pas le pulaar. Un seuil unique ferait donc
#: taire exactement les citoyens que ce projet existe pour servir.
#:
#: D'où ce choix : ne rien cacher au modèle. Une correspondance faible est
#: transmise COMME FAIBLE, et la règle 0 du prompt système décide. Le vrai
#: correctif — traduire la question en français avant de l'encoder — rendrait
#: ensuite un seuil franc possible, les deux bandes devenant disjointes.
SEUIL_CONFIANCE = 0.55


def _liste(valeurs) -> str:
    elements = [str(v).strip() for v in (valeurs or []) if str(v).strip()]
    if not elements:
        return INCONNU
    return " ; ".join(elements[:MAX_ELEMENTS])[:MAX_CARACTERES]


def _texte(valeur) -> str:
    propre = str(valeur or "").strip()
    return propre[:MAX_CARACTERES] if propre else INCONNU


def _correspondance_fiable(similarite) -> bool:
    """
    Vrai si la démarche trouvée correspond vraiment au message.

    Une similarité absente (repli mot-clé, `search.py`, qui n'en produit pas)
    compte comme fiable : ce repli ne se déclenche que sur une correspondance
    de mots, donc sur des termes réellement prononcés.
    """
    if similarite is None:
        return True
    try:
        return float(similarite) >= SEUIL_CONFIANCE
    except (TypeError, ValueError):
        return True


def _ligne_confiance(similarite) -> str:
    """
    Dit au modèle à quel point la démarche trouvée correspond à la question.

    La recherche rend TOUJOURS sa plus proche voisine : sans cette ligne, une
    démarche accrochée à 0,43 par une salutation est présentée avec le même
    aplomb qu'une demande explicite à 0,95. Le modèle n'a alors aucun moyen de
    faire la différence, et expose une fiche que personne n'a demandée.

    Voir `_correspondance_fiable` pour le traitement d'une similarité absente.
    """
    if not _correspondance_fiable(similarite):
        return (
            f"Correspondance : INCERTAINE ({float(similarite):.2f}) — ces informations "
            "sont probablement SANS RAPPORT avec le message. Ne les expose pas si le "
            "citoyen n'a pas clairement demandé cette démarche-là ; salue ou "
            "réponds simplement, puis demande-lui ce qu'il veut faire."
        )
    if similarite is None:
        return "Correspondance : fiable (trouvée par les mots du message)."
    try:
        return f"Correspondance : fiable ({float(similarite):.2f})."
    except (TypeError, ValueError):
        return "Correspondance : fiable (trouvée par les mots du message)."


def resume_rag(resultats: list) -> str:
    """
    Les informations officielles de la démarche trouvée, pour le prompt.

    Seuls le nom et trois documents étaient transmis : le coût, le délai, le
    lieu et les conditions dormaient en base. Un citoyen qui demandait « combien
    ça coûte ? » n'obtenait donc rien de fiable — au mieux un aveu d'ignorance,
    au pire une invention du modèle.
    """
    if not resultats:
        return "Aucune information officielle trouvée pour cette question."

    from services import demarche as service_demarche

    fiche = resultats[0]
    nom = _texte(fiche.get("nom_demarche"))
    menable = service_demarche.reconnaitre_demarche(fiche.get("nom_demarche"))
    fiable = _correspondance_fiable(fiche.get("similarite"))
    lignes = [
        f"Démarche la plus proche du message : {nom}",
        _ligne_confiance(fiche.get("similarite")),
        # Ce drapeau décide si l'agent a le droit de proposer de commencer :
        # proposer une démarche qu'il ne sait pas mener enverrait le citoyen
        # dans un dialogue qui n'existe pas.
        #
        # L'invitation à recopier le nom est retirée quand la correspondance
        # est incertaine : « OUI — nom exact à recopier » est un ORDRE, et il
        # suffisait à faire proposer une démarche que personne n'avait
        # demandée, en contournant l'avertissement de la ligne précédente. Le
        # fait (menable ou non) reste transmis ; seul l'impératif disparaît.
        "Réalisable maintenant avec toi : "
        + ("NON — explique la démarche et oriente vers la mairie" if not menable
           else f"OUI — nom exact à recopier : {menable.libelle}" if fiable
           else f"OUI techniquement ({menable.libelle}), mais ne la propose PAS "
                "tant que le citoyen ne l'a pas demandée lui-même"),
        f"Documents à fournir : {_liste(fiche.get('documents_requis'))}",
        f"Conditions : {_liste(fiche.get('conditions'))}",
        f"Coût : {_texte(fiche.get('cout'))}",
        f"Délai : {_texte(fiche.get('delai'))}",
        f"Où : {_texte(fiche.get('lieu'))}",
    ]
    alertes = [str(a).strip() for a in (fiche.get("alertes") or []) if str(a).strip()]
    if alertes:
        lignes.append(f"À signaler au citoyen : {' ; '.join(alertes[:MAX_ELEMENTS])[:MAX_CARACTERES]}")
    return "\n".join(lignes)
