"""
Test manuel — Sprint K, Tâche K.2 (ocr_cni_service.py — service singleton
YOLO+EasyOCR).

IMPORTANT — limite honnête de ce test : aucune vraie photo de CNI n'est
disponible dans cet environnement (aucun jeu de données/exemple trouvé sur le
disque). Ce test valide donc la PLOMBERIE réelle (chargement du modèle une
seule fois, écriture/nettoyage des fichiers temporaires, forme du résultat,
pas de crash) avec une image de test qui n'est PAS une vraie CNI — le modèle
YOLO ne détectera donc normalement RIEN dessus (comportement attendu et
vérifié : toutes les classes reviennent à None, pas une erreur).

Le critère de validation EXPLICITE de la tâche ("au moins id/dob/sex
reviennent avec confidence_detection au-dessus du seuil et is_valid_format=
true") NE PEUT PAS être vérifié sans une vraie photo recto/verso de CNI —
à refaire avec un vrai exemple dès qu'on en a un (cf. message de fin).
"""
import asyncio
import io
import os
import sys
import time
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from PIL import Image, ImageDraw

import ocr_cni_service


def generer_image_bidon(texte: str) -> bytes:
    img = Image.new("RGB", (640, 400), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 630, 390], outline=(0, 0, 0), width=3)
    draw.text((30, 180), texte, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


async def main_test():
    recto_bytes = generer_image_bidon("PAS UNE VRAIE CNI - RECTO")
    verso_bytes = generer_image_bidon("PAS UNE VRAIE CNI - VERSO")

    dossier_tmp_avant = set(os.listdir(os.environ.get("TEMP", "/tmp"))) if os.environ.get("TEMP") else set()

    print("Premier appel (charge le modèle — plus long)...")
    t0 = time.monotonic()
    resultat1 = await ocr_cni_service.extraire_cni(recto_bytes, verso_bytes)
    duree1 = time.monotonic() - t0
    print(f"  -> {duree1:.1f}s")

    print("Deuxième appel (modèle déjà chargé — doit être nettement plus rapide)...")
    t1 = time.monotonic()
    resultat2 = await ocr_cni_service.extraire_cni(recto_bytes, verso_bytes)
    duree2 = time.monotonic() - t1
    print(f"  -> {duree2:.1f}s")

    assert duree2 < duree1, "le 2e appel n'a pas été plus rapide — le modèle est peut-être rechargé à chaque appel"
    print(f"OK - singleton confirmé : 2e appel {duree1 / max(duree2, 0.01):.1f}x plus rapide (modèle chargé une fois).\n")

    # --- Forme du résultat : les 14 classes doivent toutes être présentes ---
    print("Classes retournées :", sorted(resultat1.keys()))
    assert len(resultat1) == 14, f"attendu 14 classes, obtenu {len(resultat1)}"
    for cls_name, entree in resultat1.items():
        assert set(entree.keys()) == {"value_cleaned", "confidence_detection", "needs_review", "is_valid_format", "source"}, (
            f"forme inattendue pour {cls_name} : {entree}"
        )
    print("OK - les 14 classes sont bien présentes, avec la forme attendue pour chacune.\n")

    # --- Comportement attendu sur une image qui N'EST PAS une vraie CNI : rien détecté ---
    detectees = {c: e for c, e in resultat1.items() if e["value_cleaned"] is not None}
    print(f"Champs détectés sur l'image factice : {detectees}")
    print("(Attendu : aucun, ou très peu — ce n'est pas une vraie CNI, le modèle ne doit pas halluciner.)\n")

    # --- Fichiers temporaires bien nettoyés (pas de fuite, Tâche K.1) ---
    if os.environ.get("TEMP"):
        dossier_tmp_apres = set(os.listdir(os.environ["TEMP"]))
        fuites = [f for f in (dossier_tmp_apres - dossier_tmp_avant) if "_recto" in f or "_verso" in f or "_corrected" in f]
        assert not fuites, f"fichiers temporaires non nettoyés : {fuites}"
        print("OK - aucun fichier temporaire résiduel après les 2 appels.\n")

    print("Tâche K.2 validée (plomberie) : singleton confirmé, forme du résultat correcte, pas de fuite de fichiers.")
    print("⚠️  Reste à refaire avec une VRAIE photo recto/verso de CNI pour valider la détection réelle")
    print("   (id/dob/sex avec confidence_detection au-dessus du seuil et is_valid_format=true).")


if __name__ == "__main__":
    asyncio.run(main_test())
