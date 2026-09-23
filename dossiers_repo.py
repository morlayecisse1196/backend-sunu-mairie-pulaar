"""
dossiers_repo.py — Sprint B, Tâche B.3.

Accès Supabase (REST client) pour la table `dossiers`, sur le modèle de
`demarches_repo.py`. Utilisé par le handler WebSocket (main.py) pour
persister l'état du dossier en cours de remplissage en mode administratif.

Les échecs réseau ne lèvent jamais d'exception jusqu'à l'appelant WebSocket :
un souci de persistance ne doit pas faire tomber la conversation en cours
(même principe que search_demarches dans main.py). L'état en mémoire du
handler WS reste la source de vérité pour la conversation en cours ; un échec
de persistance ne fait que retarder sa visibilité côté consultant — limite
connue, acceptable pour le MVP (pas de file de réconciliation/retry).
"""
import random
import uuid
from datetime import datetime, timezone
from typing import Optional

from supabase_client import get_supabase_client
from dialogue_engine import MAX_DOCUMENT_BYTES, TYPES_MIME_DOCUMENT_VALIDES, construire_champs_formulaire

# Bucket Storage PRIVÉ (jamais public) pour les documents de dossier : ce sont
# des pièces d'identité et actes d'état civil (CNI, certificat de naissance),
# donc uniquement des URLs signées à durée limitée (get_document_signed_url),
# jamais d'URL publique permanente.
BUCKET_DOCUMENTS = "documents-dossiers"


def ensure_bucket_documents() -> None:
    """Crée le bucket Storage privé s'il n'existe pas déjà (idempotent)."""
    supabase = get_supabase_client()
    try:
        supabase.storage.get_bucket(BUCKET_DOCUMENTS)
    except Exception:
        try:
            supabase.storage.create_bucket(
                BUCKET_DOCUMENTS,
                options={
                    "public": False,
                    "file_size_limit": MAX_DOCUMENT_BYTES,
                    "allowed_mime_types": TYPES_MIME_DOCUMENT_VALIDES,
                },
            )
        except Exception as e:
            print(f"⚠️ Création du bucket {BUCKET_DOCUMENTS} échouée ({e}) — l'upload suivant échouera probablement aussi.")


def resoudre_commune_id(nom_commune: Optional[str]) -> Optional[str]:
    """
    Cherche l'id de la commune correspondant à `nom_commune` (comparaison
    insensible à la casse). Retourne None si absent de la table `communes`
    (ex. commune connue du profil citoyen mais pas encore seedée, ou
    "National" — sentinelle du RAG informationnel, jamais une vraie commune).
    """
    if not nom_commune or nom_commune == "National":
        return None
    try:
        supabase = get_supabase_client()
        response = (
            supabase.table("communes")
            .select("id")
            .ilike("nom", nom_commune)
            .limit(1)
            .execute()
        )
        if response.data:
            return response.data[0]["id"]
        return None
    except Exception as e:
        print(f"⚠️ Résolution commune_id échouée pour {nom_commune!r} ({e}).")
        return None


def create_dossier(
    citoyen_id: str,
    type_demarche: str,
    slots: dict,
    cas_legal: Optional[str] = None,
    commune_id: Optional[str] = None,
    statut: str = "en_cours",
) -> Optional[dict]:
    """
    Crée un nouveau dossier (transition mode information → administratif).
    Retourne la ligne insérée (avec son `id`), ou None si l'insertion échoue
    — l'appelant doit alors continuer la conversation sans dossier persisté
    (état en mémoire seul) plutôt que de couper la session.
    """
    try:
        supabase = get_supabase_client()
        payload = {
            "citoyen_id": citoyen_id,
            "type_demarche": type_demarche,
            "slots": slots,
            "cas_legal": cas_legal,
            "commune_id": commune_id,
            "statut": statut,
        }
        response = supabase.table("dossiers").insert(payload).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"⚠️ Création du dossier échouée pour citoyen {citoyen_id} ({e}).")
        return None


def update_dossier(dossier_id: str, **champs) -> bool:
    """
    Mise à jour partielle d'un dossier (slots, cas_legal, commune_id, statut...).
    `updated_at` est toujours renseigné : aucun trigger DB ne le fait
    automatiquement (pas posé dans 001_dossiers.sql). Retourne False (sans
    lever d'exception) si la mise à jour échoue.
    """
    if not champs:
        return True
    try:
        supabase = get_supabase_client()
        champs["updated_at"] = datetime.now(timezone.utc).isoformat()
        supabase.table("dossiers").update(champs).eq("id", dossier_id).execute()
        return True
    except Exception as e:
        print(f"⚠️ Mise à jour du dossier {dossier_id} échouée ({e}).")
        return False


def generer_numero_suivi(annee: Optional[int] = None) -> str:
    """
    Génère un numéro de suivi lisible, format SM-{année}-{6 chiffres} (cf.
    Exemples_Dialogues_Agent_SUNU-MAIRIE.md, exemple 2.1 : "SM-2026-000452"),
    unique en base (colonne dossiers.numero_suivi UNIQUE, cf. 001_dossiers.sql).

    Génération par tirage + vérification d'unicité, PAS une séquence Postgres
    dédiée — suffisant au volume attendu du MVP (collision improbable),
    à revoir si le volume de dossiers grandit significativement.
    """
    if annee is None:
        annee = datetime.now(timezone.utc).year
    supabase = get_supabase_client()
    for _ in range(5):
        candidat = f"SM-{annee}-{random.randint(0, 999999):06d}"
        try:
            existe = (
                supabase.table("dossiers")
                .select("id")
                .eq("numero_suivi", candidat)
                .limit(1)
                .execute()
            )
            if not existe.data:
                return candidat
        except Exception as e:
            print(f"⚠️ Vérification d'unicité du numéro de suivi échouée ({e}) — nouvel essai.")
    # Repli si 5 tirages collisionnent (ou si Supabase était injoignable) :
    # suffixe horodaté, unique par construction à la seconde près.
    return f"SM-{annee}-{int(datetime.now(timezone.utc).timestamp()) % 1000000:06d}"


def upload_document(
    dossier_id: str, type_document: str, contenu: bytes, content_type: str, extension: str
) -> Optional[dict]:
    """
    Upload un fichier dans Supabase Storage (bucket privé) puis crée la ligne
    `documents` correspondante. Retourne la ligne insérée, ou None si l'upload
    ou l'insertion échoue.

    Contrairement aux autres fonctions de ce module (qui avalent leurs
    erreurs pour ne jamais interrompre une conversation en cours), un échec
    ici N'EST PAS silencieux pour l'appelant : c'est une action explicite du
    citoyen (upload), l'endpoint REST doit renvoyer une erreur claire, pas
    faire semblant que ça a marché.

    Limite connue : si l'upload Storage réussit mais l'insertion `documents`
    échoue ensuite, le fichier reste orphelin dans Storage (pas de
    transaction inter-systèmes ici — acceptable pour le MVP, mais log préci
    le chemin pour un nettoyage manuel si besoin).
    """
    ensure_bucket_documents()
    chemin = f"{dossier_id}/{type_document}_{uuid.uuid4().hex}.{extension}"
    supabase = get_supabase_client()
    try:
        supabase.storage.from_(BUCKET_DOCUMENTS).upload(
            chemin, contenu, file_options={"content-type": content_type}
        )
    except Exception as e:
        print(f"⚠️ Upload Storage échoué pour dossier {dossier_id} ({e}).")
        return None

    try:
        payload = {
            "dossier_id": dossier_id,
            "type": type_document,
            # Chemin dans le bucket, PAS une URL — le bucket est privé, cf.
            # get_document_signed_url pour générer une URL d'accès temporaire.
            "fichier_url": chemin,
            "mode": "photo",
            "statut": "recu",
        }
        response = supabase.table("documents").insert(payload).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(
            f"⚠️ Insertion de la ligne documents échouée pour dossier {dossier_id} ({e}) "
            f"— fichier orphelin dans Storage : {chemin}"
        )
        return None


def get_document_signed_url(chemin: str, expires_in: int = 3600) -> Optional[str]:
    """
    URL signée temporaire (1h par défaut) pour accéder à un document stocké —
    jamais d'URL publique permanente pour ces pièces (identité, état civil).
    Destiné au consultant (Sprint C/D) pour afficher/télécharger un document.
    """
    try:
        supabase = get_supabase_client()
        result = supabase.storage.from_(BUCKET_DOCUMENTS).create_signed_url(chemin, expires_in)
        return result.get("signedURL") or result.get("signedUrl")
    except Exception as e:
        print(f"⚠️ Génération d'URL signée échouée pour {chemin!r} ({e}).")
        return None


def telecharger_document_bytes(document: dict) -> Optional[bytes]:
    """
    Télécharge le contenu RÉEL d'un document (Sprint K, Tâche K.4 — OCR CNI :
    besoin des octets bruts pour les passer au pipeline, pas juste une URL) —
    même méthode `.download()` déjà utilisée par test_upload_document.py.
    """
    try:
        supabase = get_supabase_client()
        return supabase.storage.from_(BUCKET_DOCUMENTS).download(document["fichier_url"])
    except Exception as e:
        print(f"⚠️ Téléchargement du document {document.get('id')} échoué ({e}).")
        return None


def get_commune(commune_id: Optional[str]) -> Optional[dict]:
    """Lit une ligne `communes` par id — utilisé par document_generator.py (Tâche D.2)."""
    if not commune_id:
        return None
    try:
        supabase = get_supabase_client()
        response = supabase.table("communes").select("*").eq("id", commune_id).limit(1).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"⚠️ Lecture de la commune {commune_id} échouée ({e}).")
        return None


def get_or_create_formulaire_acte(dossier_id: str) -> Optional[dict]:
    """
    Formulaire "extrait_naissance" (Tâche D.2) : contrairement aux formulaires
    de get_or_create_document_formulaire (un par PIÈCE uploadée), celui-ci
    porte les champs propres au document de SORTIE lui-même (numéro d'acte et
    de registre, signataire, bloc jugement) — rattachés à aucun document
    photographié, donc document_id reste NULL. Toujours créé vide (aucune
    correspondance dialogue fiable pour ces champs, cf. dialogue_engine.py) :
    entièrement à la saisie manuelle du consultant.
    """
    supabase = get_supabase_client()
    try:
        existant = (
            supabase.table("document_formulaires")
            .select("*")
            .eq("dossier_id", dossier_id)
            .eq("type_document", "extrait_naissance")
            .is_("document_id", "null")
            .limit(1)
            .execute()
        )
        if existant.data:
            return existant.data[0]
    except Exception as e:
        print(f"⚠️ Lecture du formulaire acte échouée pour dossier {dossier_id} ({e}).")
        return None

    champs = construire_champs_formulaire("extrait_naissance", {})
    try:
        payload = {
            "dossier_id": dossier_id,
            "document_id": None,
            "type_document": "extrait_naissance",
            "champs": champs,
            "statut": "a_remplir",
        }
        response = supabase.table("document_formulaires").insert(payload).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"⚠️ Création du formulaire acte échouée pour dossier {dossier_id} ({e}).")
        return None


def create_cas_particulier(
    dossier_id: str, type_incident: str, description: Optional[str] = None,
    options_proposees: Optional[list] = None,
) -> Optional[dict]:
    """
    Insertion dans `cas_particuliers` (Sprint E, Tâche E.3 — taxonomie
    `type_incident` reprise de Flux_Consultant_Generation_Document_
    SUNU-MAIRIE.md §2.5, cf. dialogue_engine.TYPES_INCIDENT_CAS_PARTICULIER).
    Utilisé aussi bien par document_generator.py (échec de génération,
    Tâche D.2) que par l'endpoint de création consultant (Tâche E.3) — deux
    "signaleurs" différents (l'agent ou le consultant lui-même), même mécanisme.

    `description` réutilise la colonne `description_llm` de la table (nom
    hérité de la migration 001) même quand ce n'est pas un LLM qui écrit —
    pas justifié d'ajouter une colonne pour si peu.

    1 à 3 options si fournies (règle du §2.5) — pas imposé ici en dur (une
    liste vide reste acceptée, ex. cas créé manuellement par un consultant
    qui n'a pas encore d'option à proposer), la validation de count est faite
    côté endpoint (Tâche E.3) où le contexte permet un message d'erreur clair.
    """
    try:
        supabase = get_supabase_client()
        payload = {
            "dossier_id": dossier_id, "type_incident": type_incident,
            "description_llm": description, "options_proposees": options_proposees or [],
        }
        response = supabase.table("cas_particuliers").insert(payload).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"⚠️ Création du cas particulier échouée pour dossier {dossier_id} ({e}).")
        return None


def list_cas_particuliers(dossier_id: str) -> list:
    try:
        supabase = get_supabase_client()
        response = (
            supabase.table("cas_particuliers")
            .select("*")
            .eq("dossier_id", dossier_id)
            .order("horodatage", desc=True)
            .execute()
        )
        return response.data or []
    except Exception as e:
        print(f"⚠️ Liste des cas particuliers échouée pour dossier {dossier_id} ({e}).")
        return []


def get_cas_particulier(cas_id: str) -> Optional[dict]:
    try:
        supabase = get_supabase_client()
        response = supabase.table("cas_particuliers").select("*").eq("id", cas_id).limit(1).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"⚠️ Lecture du cas particulier {cas_id} échouée ({e}).")
        return None


def resoudre_cas_particulier(cas_id: str, decision_consultant: str) -> Optional[dict]:
    """
    Enregistre la décision du consultant (choix d'une option proposée ou
    formulation libre — jamais une valeur par défaut, cf. Tâche E.3) et
    horodate la résolution (resolu_le, migration 005 — distinct de
    `horodatage`, qui reste la création, pour une traçabilité complète DSF §6).
    """
    try:
        supabase = get_supabase_client()
        response = (
            supabase.table("cas_particuliers")
            .update({"decision_consultant": decision_consultant, "resolu_le": datetime.now(timezone.utc).isoformat()})
            .eq("id", cas_id)
            .execute()
        )
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"⚠️ Résolution du cas particulier {cas_id} échouée ({e}).")
        return None


def get_dossier(dossier_id: str) -> Optional[dict]:
    """Relit un dossier par id (utile pour les tests manuels de validation)."""
    try:
        supabase = get_supabase_client()
        response = supabase.table("dossiers").select("*").eq("id", dossier_id).limit(1).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"⚠️ Lecture du dossier {dossier_id} échouée ({e}).")
        return None


def list_dossiers_par_commune(commune_id: str) -> list:
    """
    Dossiers d'une commune, triés par ancienneté (les plus anciens d'abord —
    cf. Flux_Consultant_Generation_Document_SUNU-MAIRIE.md §2.1), en excluant
    les dossiers encore 'en_cours' : citoyen pas allé au bout du dialogue et
    de la relecture RG7 — pas encore "reçus", cf. DSF UC2 post-condition
    ("le dossier est visible côté consultant avec statut « reçu »").
    """
    try:
        supabase = get_supabase_client()
        response = (
            supabase.table("dossiers")
            .select("*")
            .eq("commune_id", commune_id)
            .neq("statut", "en_cours")
            .order("created_at", desc=False)
            .execute()
        )
        return response.data or []
    except Exception as e:
        print(f"⚠️ Liste des dossiers échouée pour commune {commune_id} ({e}).")
        return []


def list_dossiers_par_citoyen(citoyen_id: str) -> list:
    """
    Dossiers d'UN citoyen (mobile, Tâche 7.1 du roadmap Flutter — écran « Mes
    démarches ») — filtrage exclusivement sur l'identité du token, jamais un
    paramètre d'URL, même principe que list_dossiers_par_commune côté
    consultant (§5.6 du roadmap). Contrairement à list_dossiers_par_commune,
    n'exclut PAS le statut 'en_cours' : le citoyen doit pouvoir retrouver son
    propre dossier en cours de constitution, ce n'est que côté consultant que
    ce statut n'a pas encore de sens à afficher.
    """
    try:
        supabase = get_supabase_client()
        response = (
            supabase.table("dossiers")
            .select("*")
            .eq("citoyen_id", citoyen_id)
            .order("created_at", desc=False)
            .execute()
        )
        return response.data or []
    except Exception as e:
        print(f"⚠️ Liste des dossiers échouée pour citoyen {citoyen_id} ({e}).")
        return []


def create_remarque(
    dossier_id: str, texte: str, source: str, document_genere_id: Optional[str] = None,
    champ_concerne: Optional[str] = None,
) -> Optional[dict]:
    """
    Journalise une remarque sur un document généré (table `remarques`, prévue
    depuis 001_dossiers.sql mais jamais utilisée avant la Tâche 7.1 —
    « demander des corrections » côté citoyen). `source` ∈ 'citoyen'|'consultant'
    (contrainte en base) ; ce backend ne l'utilise pour l'instant que côté
    citoyen, le consultant n'a pas encore d'écran pour en écrire une lui-même.
    """
    try:
        supabase = get_supabase_client()
        payload = {
            "dossier_id": dossier_id, "document_genere_id": document_genere_id,
            "texte": texte, "source": source,
            # Colonne prévue depuis 001_dossiers.sql, enfin utilisée : le
            # citoyen peut désigner LE champ fautif (lecture ligne par ligne),
            # ce qui évite au consultant de deviner ce qui est à corriger.
            "champ_concerne": champ_concerne,
        }
        response = supabase.table("remarques").insert(payload).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"⚠️ Création de la remarque échouée pour dossier {dossier_id} ({e}).")
        return None


def list_documents(dossier_id: str) -> list:
    """Documents (pièces uploadées) d'un dossier."""
    try:
        supabase = get_supabase_client()
        response = supabase.table("documents").select("*").eq("dossier_id", dossier_id).execute()
        return response.data or []
    except Exception as e:
        print(f"⚠️ Liste des documents échouée pour dossier {dossier_id} ({e}).")
        return []


def list_document_formulaires(dossier_id: str) -> list:
    """Formulaires structurés déjà existants pour un dossier (sans en créer)."""
    try:
        supabase = get_supabase_client()
        response = supabase.table("document_formulaires").select("*").eq("dossier_id", dossier_id).execute()
        return response.data or []
    except Exception as e:
        print(f"⚠️ Liste des document_formulaires échouée pour dossier {dossier_id} ({e}).")
        return []


def get_or_create_document_formulaire(dossier_id: str, document: dict, slots: dict) -> Optional[dict]:
    """
    Retourne le document_formulaire existant pour ce document, ou le crée
    (pré-rempli depuis les slots du dialogue, cf. construire_champs_formulaire)
    s'il n'existe pas encore — Sprint C, Tâche C.3.
    """
    supabase = get_supabase_client()
    try:
        existant = (
            supabase.table("document_formulaires")
            .select("*")
            .eq("document_id", document["id"])
            .limit(1)
            .execute()
        )
        if existant.data:
            return existant.data[0]
    except Exception as e:
        print(f"⚠️ Lecture document_formulaires échouée pour document {document['id']} ({e}).")
        return None

    champs = construire_champs_formulaire(document["type"], slots)
    try:
        payload = {
            "dossier_id": dossier_id,
            "document_id": document["id"],
            "type_document": document["type"],
            "champs": champs,
            "statut": "rempli" if champs and all(c["valeur"] is not None for c in champs) else "a_remplir",
        }
        response = supabase.table("document_formulaires").insert(payload).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"⚠️ Création document_formulaires échouée pour document {document['id']} ({e}).")
        return None


# ---------------------------------------------------------------------------
# Documents générés (PDF) — Sprint D, Tâche D.3.
# ---------------------------------------------------------------------------

BUCKET_DOCUMENTS_GENERES = "documents-generes"


def ensure_bucket_documents_generes() -> None:
    """Bucket Storage PRIVÉ pour les PDF générés — mêmes raisons que BUCKET_DOCUMENTS (Tâche B.5) : ce sont
    des actes d'état civil (brouillon ou non), jamais d'URL publique permanente."""
    supabase = get_supabase_client()
    try:
        supabase.storage.get_bucket(BUCKET_DOCUMENTS_GENERES)
    except Exception:
        try:
            supabase.storage.create_bucket(
                BUCKET_DOCUMENTS_GENERES,
                options={"public": False, "file_size_limit": 10 * 1024 * 1024, "allowed_mime_types": ["application/pdf"]},
            )
        except Exception as e:
            print(f"⚠️ Création du bucket {BUCKET_DOCUMENTS_GENERES} échouée ({e}).")


def get_next_version_documents_generes(dossier_id: str) -> int:
    """1 pour une première génération, max(version)+1 sinon — jamais d'écrasement, historique conservé."""
    try:
        supabase = get_supabase_client()
        response = (
            supabase.table("documents_generes")
            .select("version")
            .eq("dossier_id", dossier_id)
            .order("version", desc=True)
            .limit(1)
            .execute()
        )
        return (response.data[0]["version"] + 1) if response.data else 1
    except Exception as e:
        print(f"⚠️ Lecture de la version précédente échouée pour dossier {dossier_id} ({e}) — repli sur version=1.")
        return 1


def upload_document_genere(dossier_id: str, version: int, pdf_bytes: bytes) -> Optional[str]:
    """Stocke le PDF généré, retourne son chemin dans le bucket (pas une URL — bucket privé, cf. B.5)."""
    ensure_bucket_documents_generes()
    chemin = f"{dossier_id}/v{version}.pdf"
    try:
        supabase = get_supabase_client()
        supabase.storage.from_(BUCKET_DOCUMENTS_GENERES).upload(
            chemin, pdf_bytes, file_options={"content-type": "application/pdf"}
        )
        return chemin
    except Exception as e:
        print(f"⚠️ Upload du PDF généré échoué pour dossier {dossier_id} v{version} ({e}).")
        return None


def get_document_genere_signed_url(chemin: str, expires_in: int = 3600) -> Optional[str]:
    try:
        supabase = get_supabase_client()
        result = supabase.storage.from_(BUCKET_DOCUMENTS_GENERES).create_signed_url(chemin, expires_in)
        return result.get("signedURL") or result.get("signedUrl")
    except Exception as e:
        print(f"⚠️ Génération d'URL signée (document généré) échouée pour {chemin!r} ({e}).")
        return None


def create_document_genere(
    dossier_id: str, template_utilise: str, version: int, contenu_url: str, statut: str = "genere"
) -> Optional[dict]:
    try:
        supabase = get_supabase_client()
        payload = {
            "dossier_id": dossier_id, "template_utilise": template_utilise,
            "version": version, "contenu_url": contenu_url, "statut": statut,
        }
        response = supabase.table("documents_generes").insert(payload).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"⚠️ Création de documents_generes échouée pour dossier {dossier_id} ({e}).")
        return None


def list_documents_generes(dossier_id: str) -> list:
    """Historique des PDF générés pour un dossier, du plus récent au plus
    ancien (version décroissante) — Tâche F.5, pour afficher la dernière
    version au chargement de l'écran sans devoir régénérer."""
    try:
        supabase = get_supabase_client()
        response = (
            supabase.table("documents_generes")
            .select("*")
            .eq("dossier_id", dossier_id)
            .order("version", desc=True)
            .execute()
        )
        return response.data or []
    except Exception as e:
        print(f"⚠️ Liste des documents générés échouée pour dossier {dossier_id} ({e}).")
        return []


def update_document_genere_statut(document_genere_id: str, statut: str) -> Optional[dict]:
    """Fait avancer le statut d'un document généré (genere -> en_attente_validation_citoyen
    -> valide|corrections_demandees, cf. §3 du roadmap) — Tâche F.5."""
    try:
        supabase = get_supabase_client()
        response = (
            supabase.table("documents_generes")
            .update({"statut": statut})
            .eq("id", document_genere_id)
            .execute()
        )
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"⚠️ Mise à jour du statut du document généré {document_genere_id} échouée ({e}).")
        return None


def get_document_formulaire(form_id: str) -> Optional[dict]:
    """Relit un document_formulaire par id."""
    try:
        supabase = get_supabase_client()
        response = supabase.table("document_formulaires").select("*").eq("id", form_id).limit(1).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"⚠️ Lecture du formulaire {form_id} échouée ({e}).")
        return None


def update_champ_formulaire(formulaire: dict, nom_champ: str, valeur: Optional[str] = None, verifie: Optional[bool] = None) -> Optional[dict]:
    """
    Met à jour UN champ dans document_formulaires.champs (JSONB), sur la ligne
    déjà chargée `formulaire` (l'appelant doit avoir vérifié l'appartenance
    dossier/commune AVANT d'appeler cette fonction — elle ne fait que la
    mutation). `valeur` fourni -> source passe à "manuel" (la valeur ne vient
    plus du dialogue, même ressaisie identique). `verifie` fourni -> met à
    jour verifie_par_consultant indépendamment — une confirmation visuelle
    (bouton "Champ vérifié", Flux §2.2) n'est pas une correction de valeur.

    Retourne la ligne mise à jour, ou None si le champ n'existe pas dans ce
    formulaire ou si la mise à jour échoue.
    """
    champs = formulaire.get("champs") or []
    champ_trouve = None
    for champ in champs:
        if champ.get("nom") == nom_champ:
            champ_trouve = champ
            break
    if champ_trouve is None:
        return None

    if valeur is not None:
        champ_trouve["valeur"] = valeur
        champ_trouve["source"] = "manuel"
    if verifie is not None:
        champ_trouve["verifie_par_consultant"] = verifie

    tous_remplis = bool(champs) and all(c.get("valeur") is not None for c in champs)
    tous_verifies = bool(champs) and all(c.get("verifie_par_consultant") for c in champs)
    nouveau_statut = "verifie" if (tous_remplis and tous_verifies) else ("rempli" if tous_remplis else "a_remplir")

    try:
        supabase = get_supabase_client()
        supabase.table("document_formulaires").update({
            "champs": champs,
            "statut": nouveau_statut,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", formulaire["id"]).execute()
        return {**formulaire, "champs": champs, "statut": nouveau_statut}
    except Exception as e:
        print(f"⚠️ Mise à jour du formulaire {formulaire['id']} échouée ({e}).")
        return None


def update_champs_formulaire(formulaire: dict, nouveaux_champs: list) -> Optional[dict]:
    """
    Remplace la liste ENTIÈRE des champs d'un formulaire (Sprint K, Tâche K.4
    — fusion OCR, `dialogue_engine.fusionner_champs_ocr`, qui recalcule tous
    les champs d'un coup) — variante "en masse" de `update_champ_formulaire`
    (qui ne modifie qu'un seul champ). Même calcul de `statut` que ci-dessus.
    """
    tous_remplis = bool(nouveaux_champs) and all(c.get("valeur") is not None for c in nouveaux_champs)
    tous_verifies = bool(nouveaux_champs) and all(c.get("verifie_par_consultant") for c in nouveaux_champs)
    nouveau_statut = "verifie" if (tous_remplis and tous_verifies) else ("rempli" if tous_remplis else "a_remplir")

    try:
        supabase = get_supabase_client()
        supabase.table("document_formulaires").update({
            "champs": nouveaux_champs,
            "statut": nouveau_statut,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", formulaire["id"]).execute()
        return {**formulaire, "champs": nouveaux_champs, "statut": nouveau_statut}
    except Exception as e:
        print(f"⚠️ Mise à jour en masse du formulaire {formulaire['id']} échouée ({e}).")
        return None
