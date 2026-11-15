"""
admin_repo.py — Sprint C, Tâche C.4.

Accès Supabase pour les besoins admin : communes, consultants (comptes Auth +
profils, DSF A2), templates, supervision (DSF A4). Utilise le client
service_role (get_supabase_client) — les endpoints appelants sont déjà
protégés par get_current_admin (auth.py) ; pas de vérification de rôle ici,
ce module suppose l'appelant déjà autorisé.
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from dossiers_repo import resoudre_commune_id
from supabase_client import get_supabase_client

# ---------------------------------------------------------------------------
# Communes — table `communes` (distincte de demarches_repo.list_communes(),
# qui liste seulement des noms distincts issus du RAG informationnel citoyen).
# ---------------------------------------------------------------------------

def list_communes_admin() -> list:
    try:
        supabase = get_supabase_client()
        response = supabase.table("communes").select("*").order("nom").execute()
        return response.data or []
    except Exception as e:
        print(f"⚠️ Liste des communes (admin) échouée ({e}).")
        return []


def create_commune(
    nom: str, region: Optional[str], departement: Optional[str], arrondissement: Optional[str],
    latitude: Optional[float] = None, longitude: Optional[float] = None,
) -> Optional[dict]:
    """
    Les coordonnées sont facultatives et par défaut absentes : une commune
    sans coordonnées n'est simplement jamais proposée par `GET
    /communes/proche` (migration 015). Mieux vaut ne rien proposer que
    d'envoyer vers la mauvaise mairie quelqu'un qui ne peut pas relire la
    liste.
    """
    try:
        supabase = get_supabase_client()
        payload = {"nom": nom, "region": region, "departement": departement, "arrondissement": arrondissement}
        if latitude is not None:
            payload["latitude"] = latitude
        if longitude is not None:
            payload["longitude"] = longitude
        response = supabase.table("communes").insert(payload).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"⚠️ Création de la commune {nom!r} échouée ({e}) — nom déjà pris ?")
        return None


def update_commune(commune_id: str, **champs) -> Optional[dict]:
    if not champs:
        return None
    try:
        supabase = get_supabase_client()
        response = supabase.table("communes").update(champs).eq("id", commune_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"⚠️ Mise à jour de la commune {commune_id} échouée ({e}).")
        return None


# ---------------------------------------------------------------------------
# Tampon numérique — Sprint G, Tâche G.1 (§5.4 du roadmap : proposition
# technique V2, AUCUNE valeur légale confirmée à ce stade, cf. mise en garde
# reprise mot pour mot côté frontend). Stockage privé (bucket dédié, jamais
# d'URL publique — même principe que documents/documents-generes, B.5/D.3) +
# journal append-only (tampon_confirmations, migration 006) distinct du champ
# `communes.tampon_numerique_url` qui ne garde que le tampon ACTUELLEMENT actif.
# ---------------------------------------------------------------------------

BUCKET_TAMPONS = "tampons-numeriques"


def ensure_bucket_tampons() -> None:
    supabase = get_supabase_client()
    try:
        supabase.storage.get_bucket(BUCKET_TAMPONS)
    except Exception:
        try:
            supabase.storage.create_bucket(
                BUCKET_TAMPONS,
                options={"public": False, "file_size_limit": 5 * 1024 * 1024, "allowed_mime_types": ["image/png", "image/jpeg"]},
            )
        except Exception as e:
            print(f"⚠️ Création du bucket {BUCKET_TAMPONS} échouée ({e}).")


def upload_tampon(commune_id: str, fichier_bytes: bytes, extension: str, content_type: str) -> Optional[str]:
    """Stocke l'image du tampon, retourne son chemin dans le bucket (pas une
    URL — bucket privé). Un nom de fichier unique par upload (horodatage dans
    le nom) : un tampon remplacé ne supprime pas l'ancien fichier, cohérent
    avec le journal append-only de tampon_confirmations ci-dessous."""
    ensure_bucket_tampons()
    chemin = f"{commune_id}/{datetime.now().strftime('%Y%m%d%H%M%S')}.{extension}"
    try:
        supabase = get_supabase_client()
        supabase.storage.from_(BUCKET_TAMPONS).upload(chemin, fichier_bytes, file_options={"content-type": content_type})
        return chemin
    except Exception as e:
        print(f"⚠️ Upload du tampon échoué pour commune {commune_id} ({e}).")
        return None


def get_tampon_signed_url(chemin: str, expires_in: int = 3600) -> Optional[str]:
    try:
        supabase = get_supabase_client()
        result = supabase.storage.from_(BUCKET_TAMPONS).create_signed_url(chemin, expires_in)
        return result.get("signedURL") or result.get("signedUrl")
    except Exception as e:
        print(f"⚠️ Génération d'URL signée (tampon) échouée pour {chemin!r} ({e}).")
        return None


def telecharger_tampon(chemin: str) -> Optional[bytes]:
    """
    L'image du tampon elle-même, pour l'apposer sur un document généré.

    Le contenu, pas une URL signée : celle-ci expire au bout d'une heure, et un
    PDF qui perdrait son tampon quelques heures après avoir été produit serait
    pire qu'un PDF sans tampon — il aurait l'air d'un document trafiqué.
    """
    try:
        supabase = get_supabase_client()
        return supabase.storage.from_(BUCKET_TAMPONS).download(chemin)
    except Exception as e:
        print(f"⚠️ Téléchargement du tampon échoué pour {chemin!r} ({e}).")
        return None


def confirmer_tampon(commune_id: str, admin_id: str, fichier_url: str) -> Optional[dict]:
    """
    Enregistre la confirmation (journal append-only, jamais écrasé) ET fait
    du fichier uploadé le tampon ACTIF de la commune (communes.tampon_numerique_url).
    Retourne la ligne du journal créée, ou None si l'une des deux écritures échoue
    — dans ce cas l'appelant ne doit pas prétendre que la confirmation a été
    journalisée (cf. critère de validation explicite de G.1).
    """
    supabase = get_supabase_client()
    try:
        confirmation = supabase.table("tampon_confirmations").insert({
            "commune_id": commune_id, "admin_id": admin_id, "fichier_url": fichier_url,
        }).execute()
        if not confirmation.data:
            return None
    except Exception as e:
        print(f"⚠️ Journalisation de la confirmation de tampon échouée pour commune {commune_id} ({e}).")
        return None

    try:
        supabase.table("communes").update({"tampon_numerique_url": fichier_url}).eq("id", commune_id).execute()
    except Exception as e:
        print(f"⚠️ Mise à jour de communes.tampon_numerique_url échouée pour {commune_id} ({e}) — confirmation journalisée quand même.")

    return confirmation.data[0]


def list_tampon_confirmations(commune_id: str) -> list:
    """Historique des confirmations pour une commune, la plus récente d'abord,
    enrichi de l'email de l'admin ayant confirmé (comme list_consultants —
    `tampon_confirmations` ne stocke que admin_id, l'email vient de Auth)."""
    try:
        supabase = get_supabase_client()
        confirmations = (
            supabase.table("tampon_confirmations")
            .select("*")
            .eq("commune_id", commune_id)
            .order("confirme_le", desc=True)
            .execute()
        ).data or []
        if not confirmations:
            return []
        utilisateurs = {u.id: u for u in supabase.auth.admin.list_users()}
        for confirmation in confirmations:
            utilisateur = utilisateurs.get(confirmation["admin_id"])
            confirmation["admin_email"] = utilisateur.email if utilisateur else None
        return confirmations
    except Exception as e:
        print(f"⚠️ Liste des confirmations de tampon échouée pour commune {commune_id} ({e}).")
        return []


# ---------------------------------------------------------------------------
# Consultants — compte Supabase Auth + profil (DSF A2 : "créer/désactiver des
# comptes consultants, leur rattacher une commune").
# ---------------------------------------------------------------------------

def _horodatage(valeur) -> Optional[str]:
    """Supabase Auth renvoie des datetime ; le JSON de l'API attend des chaînes ISO."""
    if valeur is None:
        return None
    return valeur.isoformat() if hasattr(valeur, "isoformat") else str(valeur)


def _upsert_profil(payload: dict, payload_minimal: dict) -> bool:
    """Écrit le profil ; rejoue sans les colonnes de la migration 012 si elle n'est pas appliquée."""
    supabase = get_supabase_client()
    try:
        supabase.table("profiles").upsert(payload, on_conflict="id").execute()
        return True
    except Exception as e:
        print(f"⚠️ Profil complet non écrit ({e}) — nouvel essai sans les colonnes de la migration 012.")
    try:
        supabase.table("profiles").upsert(payload_minimal, on_conflict="id").execute()
        return True
    except Exception as e:
        print(f"⚠️ Écriture du profil échouée ({e}).")
        return False


def list_consultants() -> list:
    """
    Profils role='consultant', enrichis avec email + statut actif/désactivé —
    la table `profiles` ne stocke pas l'email, il vient de Supabase Auth.
    """
    try:
        supabase = get_supabase_client()
        # select("*") plutôt qu'une liste figée : les colonnes ajoutées par la
        # migration 012 (nom_complet, téléphone, drapeau mot de passe) sont
        # renvoyées si elles existent, sans casser sur une base pas à jour.
        profils = supabase.table("profiles").select("*").eq("role", "consultant").execute().data or []
        if not profils:
            return []
        utilisateurs = {u.id: u for u in supabase.auth.admin.list_users()}
        resultat = []
        for profil in profils:
            utilisateur = utilisateurs.get(profil["id"])
            resultat.append({
                "id": profil["id"],
                "commune": profil["commune"],
                "email": utilisateur.email if utilisateur else None,
                "actif": (utilisateur.banned_until is None) if utilisateur else None,
                "nom_complet": profil.get("nom_complet"),
                "telephone": profil.get("telephone"),
                "doit_changer_mot_de_passe": profil.get("doit_changer_mot_de_passe"),
                "derniere_connexion": _horodatage(getattr(utilisateur, "last_sign_in_at", None)),
                "cree_le": _horodatage(getattr(utilisateur, "created_at", None)),
            })
        return resultat
    except Exception as e:
        print(f"⚠️ Liste des consultants échouée ({e}).")
        return []


def create_consultant(email: str, commune_nom: str, nom_complet: Optional[str] = None) -> Optional[dict]:
    """
    Crée un compte consultant (DSF A2) : utilisateur Supabase Auth (email
    confirmé d'office — c'est l'admin qui vouche pour ce compte, pas une
    inscription publique) + profil role='consultant' rattaché à la commune.

    Mot de passe temporaire généré aléatoirement avec `secrets` (pas
    `random` : c'est un secret d'authentification, contrairement au
    numero_suivi de dossiers_repo.py) et retourné UNE SEULE FOIS dans la
    réponse — jamais reloggé/restockable en clair ensuite. À communiquer au
    consultant par un canal sûr, hors de ce système.
    """
    supabase = get_supabase_client()
    mot_de_passe_temporaire = secrets.token_urlsafe(12)
    try:
        reponse_auth = supabase.auth.admin.create_user({
            "email": email,
            "password": mot_de_passe_temporaire,
            "email_confirm": True,
            # Drapeau lu par le web : tant qu'il est vrai, l'espace est bloqué
            # par la demande de changement du mot de passe temporaire.
            "app_metadata": {"must_change_password": True},
        })
    except Exception as e:
        print(f"⚠️ Création du compte Auth pour {email!r} échouée ({e}).")
        return None

    user_id = reponse_auth.user.id
    # upsert : robuste qu'un trigger DB ait déjà créé une ligne `profiles`
    # stub à la création du user Auth ou non.
    complet = {"id": user_id, "commune": commune_nom, "role": "consultant", "doit_changer_mot_de_passe": True}
    if nom_complet:
        complet["nom_complet"] = nom_complet
    if not _upsert_profil(complet, {"id": user_id, "commune": commune_nom, "role": "consultant"}):
        print(f"⚠️ Compte Auth créé mais profil absent pour {user_id} — à corriger manuellement.")
        return None

    return {
        "id": user_id,
        "email": email,
        "commune": commune_nom,
        "nom_complet": nom_complet,
        "mot_de_passe_temporaire": mot_de_passe_temporaire,
    }


def reinitialiser_mot_de_passe_consultant(user_id: str) -> Optional[dict]:
    """
    Nouveau mot de passe temporaire pour un consultant (DSF A2, support
    quotidien). L'ancien cesse immédiatement de fonctionner et le drapeau
    « à changer » est reposé. Retourne None si l'utilisateur n'est pas un
    consultant connu.
    """
    supabase = get_supabase_client()
    try:
        profil = supabase.table("profiles").select("id, role").eq("id", user_id).limit(1).execute().data
        if not profil or profil[0].get("role") != "consultant":
            return None
    except Exception as e:
        print(f"⚠️ Lecture du profil {user_id} échouée ({e}).")
        return None

    mot_de_passe_temporaire = secrets.token_urlsafe(12)
    try:
        reponse = supabase.auth.admin.update_user_by_id(
            user_id, {"password": mot_de_passe_temporaire, "app_metadata": {"must_change_password": True}}
        )
    except Exception as e:
        print(f"⚠️ Réinitialisation du mot de passe échouée pour {user_id} ({e}).")
        return None

    try:
        supabase.table("profiles").update({"doit_changer_mot_de_passe": True}).eq("id", user_id).execute()
    except Exception as e:
        print(f"⚠️ Drapeau 'doit changer son mot de passe' non posé pour {user_id} ({e}) — mot de passe bien réinitialisé.")

    email = getattr(getattr(reponse, "user", None), "email", None)
    return {"id": user_id, "email": email, "mot_de_passe_temporaire": mot_de_passe_temporaire}


def list_dossiers_admin(inclure_en_cours: bool = False) -> list:
    """Tous les dossiers, toutes communes, enrichis du nom de la commune et du citoyen."""
    try:
        supabase = get_supabase_client()
        requete = supabase.table("dossiers").select("*")
        if not inclure_en_cours:
            requete = requete.neq("statut", "en_cours")
        dossiers = requete.order("created_at", desc=True).execute().data or []
    except Exception as e:
        print(f"⚠️ Liste des dossiers (admin) échouée ({e}).")
        return []

    try:
        communes = {c["id"]: c["nom"] for c in supabase.table("communes").select("id, nom").execute().data or []}
    except Exception:
        communes = {}
    try:
        citoyens = {
            p["id"]: p.get("nom_complet")
            for p in supabase.table("profiles").select("id, nom_complet").eq("role", "citoyen").execute().data or []
        }
    except Exception:
        citoyens = {}

    for dossier in dossiers:
        dossier["commune_nom"] = communes.get(dossier.get("commune_id"))
        dossier["citoyen_nom"] = citoyens.get(dossier.get("citoyen_id"))
    return dossiers


def set_consultant_actif(user_id: str, actif: bool) -> bool:
    """Active/désactive un compte consultant (DSF A2) via le mécanisme de ban de Supabase Auth."""
    try:
        supabase = get_supabase_client()
        supabase.auth.admin.update_user_by_id(
            user_id, {"ban_duration": "none" if actif else "876000h"}  # ~100 ans = désactivation de fait
        )
        return True
    except Exception as e:
        print(f"⚠️ Changement de statut actif du consultant {user_id} échoué ({e}).")
        return False


def update_consultant_commune(user_id: str, commune_nom: str) -> bool:
    try:
        supabase = get_supabase_client()
        supabase.table("profiles").update({"commune": commune_nom}).eq("id", user_id).execute()
        return True
    except Exception as e:
        print(f"⚠️ Changement de commune du consultant {user_id} échoué ({e}).")
        return False


# ---------------------------------------------------------------------------
# Templates — table `templates` (cf. §5.5 du roadmap, registre extensible).
# ---------------------------------------------------------------------------

def list_templates() -> list:
    try:
        supabase = get_supabase_client()
        return supabase.table("templates").select("*").execute().data or []
    except Exception as e:
        print(f"⚠️ Liste des templates échouée ({e}).")
        return []


def create_template(
    type_demarche: str, nom_fichier_xml: str, nom_fichier_html: str, version: int = 1
) -> Optional[dict]:
    try:
        supabase = get_supabase_client()
        payload = {
            "type_demarche": type_demarche,
            "nom_fichier_xml": nom_fichier_xml,
            "nom_fichier_html": nom_fichier_html,
            "version": version,
        }
        response = supabase.table("templates").insert(payload).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"⚠️ Création du template {type_demarche!r} échouée ({e}) — type_demarche déjà pris ?")
        return None


def update_template(type_demarche: str, **champs) -> Optional[dict]:
    if not champs:
        return None
    try:
        supabase = get_supabase_client()
        response = supabase.table("templates").update(champs).eq("type_demarche", type_demarche).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"⚠️ Mise à jour du template {type_demarche!r} échouée ({e}).")
        return None


# ---------------------------------------------------------------------------
# Supervision — DSF A4.
# ---------------------------------------------------------------------------

# Même définition que STATUTS_A_TRAITER côté web : ce qui attend une action
# d'un agent (un dossier `genere` n'est pas fini tant qu'il n'est pas envoyé).
STATUTS_A_TRAITER = ("recu", "en_traitement", "corrections_demandees", "genere")
JOURS_EVOLUTION = 30


def _jour(horodatage: Optional[str]) -> Optional[str]:
    """Date ISO (AAAA-MM-JJ) d'un horodatage Supabase, ou None s'il est illisible."""
    if not horodatage:
        return None
    try:
        return datetime.fromisoformat(horodatage).date().isoformat()
    except ValueError:
        return horodatage[:10] if len(horodatage) >= 10 else None


def _duree_traitement_heures(dossier: dict) -> Optional[float]:
    if dossier.get("statut") != "finalise" or not dossier.get("created_at") or not dossier.get("updated_at"):
        return None
    try:
        debut = datetime.fromisoformat(dossier["created_at"])
        fin = datetime.fromisoformat(dossier["updated_at"])
    except ValueError:
        return None
    return (fin - debut).total_seconds() / 3600


def _supervision_par_commune(dossiers: list, communes: dict) -> list:
    par_commune: dict = {}
    for dossier in dossiers:
        commune_id = dossier.get("commune_id")
        ligne = par_commune.setdefault(
            commune_id,
            {
                "commune_id": commune_id,
                "commune_nom": communes.get(commune_id),
                "total": 0,
                "a_traiter": 0,
                "finalises": 0,
                "bloques": 0,
                "delai_moyen_heures": None,
                "nb_consultants_actifs": 0,
                "_delais": [],
            },
        )
        ligne["total"] += 1
        statut = dossier.get("statut")
        if statut in STATUTS_A_TRAITER:
            ligne["a_traiter"] += 1
        elif statut == "finalise":
            ligne["finalises"] += 1
        elif statut == "bloque":
            ligne["bloques"] += 1
        duree = _duree_traitement_heures(dossier)
        if duree is not None:
            ligne["_delais"].append(duree)

    try:
        for consultant in list_consultants():
            if not consultant.get("actif"):
                continue
            commune_id = resoudre_commune_id(consultant.get("commune") or "")
            if commune_id in par_commune:
                par_commune[commune_id]["nb_consultants_actifs"] += 1
    except Exception as e:
        print(f"⚠️ Comptage des consultants actifs par commune échoué ({e}).")

    lignes = []
    for ligne in par_commune.values():
        delais = ligne.pop("_delais")
        ligne["delai_moyen_heures"] = (sum(delais) / len(delais)) if delais else None
        lignes.append(ligne)
    return sorted(lignes, key=lambda l: l["total"], reverse=True)


def _evolution_30_jours(dossiers: list) -> list:
    """
    30 points, un par jour, jours creux inclus à 0 — sans quoi une courbe
    front sauterait les jours sans dossier et donnerait une fausse tendance.

    `recus` vient de `created_at` (les dialogues encore `en_cours` ne comptent
    pas : ils ne sont pas déposés) et `finalises` de `updated_at` des dossiers
    finalisés — approximation assumée tant que `dossier_evenements` n'a pas
    assez d'historique.
    """
    aujourdhui = datetime.now(timezone.utc).date()
    jours = [(aujourdhui - timedelta(days=decalage)).isoformat() for decalage in range(JOURS_EVOLUTION - 1, -1, -1)]
    compteurs = {jour: {"date": jour, "recus": 0, "finalises": 0} for jour in jours}

    for dossier in dossiers:
        if dossier.get("statut") != "en_cours":
            jour = _jour(dossier.get("created_at"))
            if jour in compteurs:
                compteurs[jour]["recus"] += 1
        if dossier.get("statut") == "finalise":
            jour = _jour(dossier.get("updated_at"))
            if jour in compteurs:
                compteurs[jour]["finalises"] += 1

    return [compteurs[jour] for jour in jours]


def get_supervision() -> dict:
    """
    Volumes de dossiers par statut, délai moyen de traitement (dossiers
    'finalise' : updated_at - created_at), liste des dossiers 'bloque' (cf.
    décision Q3/Q5, §1 du roadmap), enrichie du nom de la commune.

    Le statut 'bloque' existe dans le schéma depuis la migration 004, mais
    rien ne le déclenchait avant la Tâche G.3 (main.py, boucle WS mode
    administratif) : 3 relectures RG7 rouvertes par une correction sans
    jamais aboutir (SEUIL_ITERATIONS_CORRECTION_BLOQUE) -> statut 'bloque'.

    Agrégation faite en Python (pas de vue/RPC SQL dédiée) : volume de
    dossiers attendu pour un pilote municipal, pas justifié de complexifier
    le schéma pour ça pour l'instant.
    """
    try:
        supabase = get_supabase_client()
        # select("*") : `motif_blocage` (migration 012) est renvoyé s'il existe,
        # sans faire échouer la requête sur une base pas encore migrée.
        dossiers = supabase.table("dossiers").select("*").execute().data or []
    except Exception as e:
        print(f"⚠️ Récupération des dossiers pour supervision échouée ({e}).")
        return {"volumes_par_statut": {}, "delai_moyen_traitement_heures": None, "dossiers_bloques": []}

    volumes = {}
    for d in dossiers:
        volumes[d["statut"]] = volumes.get(d["statut"], 0) + 1

    delais = []
    for d in dossiers:
        duree = _duree_traitement_heures(d)
        if duree is not None:
            delais.append(duree)
    delai_moyen = (sum(delais) / len(delais)) if delais else None

    try:
        communes = {c["id"]: c["nom"] for c in supabase.table("communes").select("id, nom").execute().data or []}
    except Exception as e:
        print(f"⚠️ Résolution des noms de commune échouée ({e}).")
        communes = {}

    dossiers_bloques = [d for d in dossiers if d["statut"] == "bloque"]
    for d in dossiers_bloques:
        d["commune_nom"] = communes.get(d.get("commune_id"))

    return {
        "volumes_par_statut": volumes,
        "delai_moyen_traitement_heures": delai_moyen,
        "dossiers_bloques": dossiers_bloques,
        "par_commune": _supervision_par_commune(dossiers, communes),
        "evolution_30_jours": _evolution_30_jours(dossiers),
    }
