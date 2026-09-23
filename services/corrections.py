"""
« Le citoyen signale une erreur sur son document » — implémentation unique.

Utilisée par l'endpoint texte (POST /mes-dossiers/{id}/demander-corrections) et
par l'endpoint vocal (…/demander-corrections/audio) : un citoyen qui ne sait
pas écrire doit pouvoir signaler un problème en parlant, exactement comme un
autre le ferait au clavier — même règle de comptage, même blocage au 3ᵉ essai.
"""
from __future__ import annotations

from typing import Optional

from dossiers_repo import create_remarque, list_documents_generes
from services import db, evenements
from services.journal import obtenir_logger

log = obtenir_logger("corrections")

# Décision Q3/Q5 : au-delà de 3 allers-retours après génération, un humain doit
# reprendre la main plutôt que de reboucler génération → rejet → génération.
SEUIL_ITERATIONS_CORRECTION_BLOQUE = 3
MOTIF_BLOCAGE = "corrections_post_generation"


class CorrectionImpossible(Exception):
    def __init__(self, message: str, code: str = "correction_impossible"):
        super().__init__(message)
        self.message = message
        self.code = code


async def enregistrer_demande(
    dossier: dict, texte: str, *, citoyen_id: str, champ_concerne: Optional[str] = None, source_audio: bool = False
) -> dict:
    """Journalise la remarque, incrémente le compteur et fait la transition de statut."""
    texte = (texte or "").strip()
    if not texte:
        raise CorrectionImpossible("Le texte de la remarque ne peut pas être vide.", "remarque_vide")
    if dossier.get("statut") != "en_attente_validation_citoyen":
        raise CorrectionImpossible(
            f"Ce dossier n'est pas en attente de validation (statut actuel : « {dossier.get('statut')} »).",
            "statut_inattendu",
        )

    documents = await db.executer(list_documents_generes, dossier["id"])
    document_genere_id = documents[0]["id"] if documents else None

    remarque = await db.executer(
        create_remarque, dossier["id"], texte, "citoyen", document_genere_id, champ_concerne
    )
    if not remarque:
        raise CorrectionImpossible("Échec de l'enregistrement de la remarque.", "enregistrement_echoue")

    iterations = int(dossier.get("nb_iterations_correction") or 0) + 1
    bloque = iterations >= SEUIL_ITERATIONS_CORRECTION_BLOQUE
    champs = {"nb_iterations_correction": iterations}
    if bloque:
        champs["motif_blocage"] = MOTIF_BLOCAGE

    apres = await evenements.transition_statut(
        dossier["id"],
        "bloque" if bloque else "corrections_demandees",
        acteur_type="citoyen",
        acteur_id=citoyen_id,
        libelle=(
            f"Bloqué : {iterations} corrections demandées après génération"
            if bloque
            else f"Correction demandée par le citoyen ({iterations}/{SEUIL_ITERATIONS_CORRECTION_BLOQUE})"
        ),
        # Jamais le texte de la remarque ici : l'historique reste consultable,
        # la remarque elle-même vit dans `remarques` (avec son champ concerné).
        details={"remarque_id": remarque.get("id"), "champ_concerne": champ_concerne, "par_la_voix": source_audio},
        champs=champs,
        dossier_actuel=dossier,
    )
    if apres is None:
        raise CorrectionImpossible("Échec de la mise à jour du statut du dossier.", "transition_echouee")

    return {"dossier": apres, "remarque": remarque, "bloque": bloque, "iterations": iterations}
