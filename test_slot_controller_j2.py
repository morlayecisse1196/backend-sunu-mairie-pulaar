"""
Test manuel — Sprint J, Tâche J.2 (validateurs déterministes, slot_controller.py).

Critère de validation explicite (SUNU_MAIRIE_PROMPTS.md, Tâche J.2) : tests
unitaires (sans LLM, sans réseau) couvrant au moins un cas valide et un cas
invalide par type — notamment une date de naissance de mère postérieure à
celle de l'enfant, rejetée.

Aucun import de main.py / supabase_client.py / réseau ici : uniquement
slot_controller + dialogue_engine (déjà eux-mêmes sans dépendance réseau).
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from slot_controller import valider_valeur


def test_texte():
    valide, valeur, raison = valider_valeur("texte", "Ibrahima Diallo", None)
    assert valide and valeur == "Ibrahima Diallo" and raison is None

    valide, valeur, raison = valider_valeur("texte", "   ", None)
    assert not valide and raison
    print("OK - texte : valide 'Ibrahima Diallo', invalide '   ' ->", raison)


def test_date_passee():
    valide, valeur, raison = valider_valeur("date", "1998-03-12", "passee")
    assert valide and valeur == "1998-03-12" and raison is None

    valide, valeur, raison = valider_valeur("date", "2099-01-01", "passee")
    assert not valide and raison
    print("OK - date/passee : valide '1998-03-12', invalide '2099-01-01' (futur) ->", raison)


def test_date_format_texte_francais():
    # Forme telle que dite à l'oral par le citoyen (Exemple 2.1 : "Le 9 août 2020").
    # Sans règle de validation ici : on vérifie uniquement que le PARSING
    # français ("le 9 août 2020") produit bien la valeur normalisée ISO.
    valide, valeur, raison = valider_valeur("date", "le 9 août 2020", None)
    assert valide and valeur == "2020-08-09" and raison is None
    print("OK - date : format oral français '9 août 2020' -> normalisé", valeur)


def test_date_coherence_mere_apres_enfant():
    """Le cas explicitement demandé par le critère de validation de J.2."""
    # Enfant né en 2020 (volontairement dans le passé, pour isoler la règle
    # "avant:" de la règle "passee" — sinon une mère "postérieure" tomberait
    # de toute façon dans le futur et le test ne prouverait rien de spécifique
    # à la cohérence croisée).
    valeurs_connues = {"date_naissance_enfant": "2020-01-01"}

    # Mère née AVANT l'enfant (normal) -> valide.
    valide, valeur, raison = valider_valeur(
        "date", "1998-03-12", "passee|avant:date_naissance_enfant", valeurs_connues
    )
    assert valide and valeur == "1998-03-12" and raison is None

    # Mère "née" APRÈS l'enfant, mais toujours dans le passé par rapport à
    # aujourd'hui (donc "passee" seule laisserait passer) -> "avant:" doit
    # rejeter à elle seule cette incohérence.
    valide, valeur, raison = valider_valeur(
        "date", "2021-06-01", "passee|avant:date_naissance_enfant", valeurs_connues
    )
    assert not valide and valeur is None and raison
    print("OK - cohérence croisée : mère née après l'enfant REJETÉE (même sans être dans le futur) ->", raison)


def test_nombre():
    valide, valeur, raison = valider_valeur("nombre", "3", None)
    assert valide and valeur == 3.0

    valide, valeur, raison = valider_valeur("nombre", "trois", None)
    assert not valide and raison

    valide, valeur, raison = valider_valeur("nombre", "200", "0:150")
    assert not valide and raison
    print("OK - nombre : valide '3', invalide 'trois', invalide '200' hors plage 0:150 ->", raison)


def test_booleen():
    valide, valeur, raison = valider_valeur("booleen", "oui", None)
    assert valide and valeur is True

    valide, valeur, raison = valider_valeur("booleen", "peut-être", None)
    assert not valide and raison
    print("OK - booleen : valide 'oui'=True, invalide 'peut-être' (ambigu) ->", raison)


def test_age():
    valide, valeur, raison = valider_valeur("age", {"valeur": 7, "unite": "jours"}, None)
    assert valide and valeur == {"valeur": 7, "unite": "jours"}

    valide, valeur, raison = valider_valeur("age", {"valeur": 5, "unite": "lunaisons"}, None)
    assert not valide and raison

    valide, valeur, raison = valider_valeur("age", {"valeur": -3, "unite": "jours"}, None)
    assert not valide and raison
    print("OK - age : valide 7 jours, invalide unité inconnue, invalide âge négatif ->", raison)


def test_enum():
    valide, valeur, raison = valider_valeur("enum", "masculin", "masculin|feminin")
    assert valide and valeur == "masculin"

    valide, valeur, raison = valider_valeur("enum", "autre", "masculin|feminin")
    assert not valide and raison
    print("OK - enum : valide 'masculin', invalide 'autre' (hors liste) ->", raison)


def test_type_inconnu():
    try:
        valider_valeur("inconnu", "x", None)
        assert False, "aurait dû lever ValueError"
    except ValueError:
        print("OK - type_valeur inconnu -> ValueError levée comme attendu")


if __name__ == "__main__":
    test_texte()
    test_date_passee()
    test_date_format_texte_francais()
    test_date_coherence_mere_apres_enfant()
    test_nombre()
    test_booleen()
    test_age()
    test_enum()
    test_type_inconnu()
    print("\nTâche J.2 validée : validateurs déterministes couverts (valide + invalide par type, sans LLM ni réseau).")
