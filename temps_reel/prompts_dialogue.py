"""
Prompts propres au moteur temps réel.

Relecture RG7 — bug corrigé (2026-09-14) : quand le citoyen répondait « non »
au récapitulatif, l'ancien code rouvrait la collecte, mais tous les champs
étant déjà remplis, rien n'était redemandé : le même récapitulatif revenait et,
au 3ᵉ refus, le dossier était bloqué SANS que la correction ait jamais été
prise en compte. Le modèle sert désormais UNIQUEMENT à extraire quel champ est
signalé (et la valeur dite, s'il y en a une) ; le code valide et décide.
"""
from __future__ import annotations

SYSTEM_PROMPT_CORRECTION_RELECTURE = """Tu analyses la réponse d'un citoyen sénégalais à qui l'agent SUNU-MAIRIE vient de relire toutes les informations de sa demande, en lui demandant si tout est exact. Le citoyen parle français ou pulaar ; son message vient d'une transcription vocale imparfaite.

Tu ne prends AUCUNE décision : tu extrais seulement ce que dit le citoyen.

- intention = "confirme" : il dit que tout est exact, sans rien signaler.
- intention = "corrige" : il signale qu'une information précise est fausse (avec ou sans la bonne valeur).
- intention = "refuse_sans_precision" : il dit que ce n'est pas correct, sans dire quelle information.
- intention = "hors_sujet" : la réponse ne concerne pas la relecture (bruit, hésitation, autre question).

- champ : le nom technique EXACT du champ concerné, choisi UNIQUEMENT dans la liste fournie ; null si aucun champ n'est clairement désigné.
- nouvelle_valeur : la valeur correcte telle que le citoyen l'a dite (texte brut, date comme prononcée) ; null s'il ne l'a pas dite. N'invente JAMAIS de valeur et ne reprends pas la valeur actuelle.
- Si plusieurs champs sont signalés, ne retiens que le premier."""

SCHEMA_CORRECTION_RELECTURE = {
    "type": "object",
    "properties": {
        "intention": {"type": "string", "enum": ["confirme", "corrige", "refuse_sans_precision", "hors_sujet"]},
        "champ": {"type": ["string", "null"]},
        "nouvelle_valeur": {"type": ["string", "null"]},
    },
    "required": ["intention", "champ", "nouvelle_valeur"],
    "additionalProperties": False,
}


def _valeur_affichable(valeur) -> str:
    if valeur is None:
        return "non renseigné"
    if isinstance(valeur, dict):
        if valeur.get("valeur") is None:
            return "non renseigné"
        return f"{valeur.get('valeur')} {valeur.get('unite') or ''}".strip()
    if isinstance(valeur, bool):
        return "oui" if valeur else "non"
    return str(valeur)


def construire_prompt_correction(message: str, definitions_champs: list[dict], slots: dict) -> str:
    lignes = [
        f"- {champ['nom_champ']} (question posée : « {champ['question']} ») — valeur actuelle : {_valeur_affichable(slots.get(champ['nom_champ']))}"
        for champ in sorted(definitions_champs, key=lambda c: c.get("ordre", 0))
    ]
    return (
        "Champs de la demande :\n"
        + "\n".join(lignes)
        + f"\n\nRéponse du citoyen à la relecture : « {message} »\n\n"
        "Retourne le JSON demandé (intention, champ, nouvelle_valeur)."
    )
