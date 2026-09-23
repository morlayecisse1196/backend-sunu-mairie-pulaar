"""
Sortie console qui ne plante pas sur un accent.

Les consoles Windows tournent souvent en cp1252, qui ne sait pas écrire « ♪ »
ni « ✗ ». Python lève alors `UnicodeEncodeError` et le script MEURT — au
milieu d'une liste, ou pire, au milieu du message qui explique une panne.

`adoucir_sortie()` demande à Python de remplacer le caractère fautif par « ? »
au lieu de lever. On perd un symbole décoratif ; on ne perd plus la commande.
Réencoder en UTF-8 serait pire : la console afficherait du charabia sur tout
le texte accentué, pas seulement sur le symbole manquant.
"""
from __future__ import annotations

import sys


def adoucir_sortie() -> None:
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass  # flux redirigé, déjà tolérant, ou non reconfigurable
