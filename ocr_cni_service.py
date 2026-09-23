"""
ocr_cni_service.py — Sprint K, Tâche K.2 (MEMOIR2/SUNU_MAIRIE_PROMPTS.md).

Service singleton pour le pipeline OCR CNI (YOLOv8s + EasyOCR,
model_OCR/cni_extraction_package/cni_pipeline.py, corrigé Tâche K.1). Chargé
UNE SEULE FOIS au premier appel (singleton, même pattern que
supabase_client.get_supabase_client()/tts_service.py) — charger le modèle
YOLO + le Reader EasyOCR à chaque requête serait beaucoup trop lent.

Décision actée : intégré IN-PROCESS dans backend-agent (pas un nouveau
Hugging Face Space séparé comme l'ASR/TTS) — plus simple à déployer, rien de
nouveau à héberger. L'inférence (bloquante, CPU — pas de GPU garanti sur le
VPS) est lancée via asyncio.to_thread pour ne jamais geler l'event loop
WebSocket pendant l'extraction.
"""
import asyncio
import os
import sys
import tempfile
import time

_MODEL_OCR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model_OCR", "cni_extraction_package")
if _MODEL_OCR_DIR not in sys.path:
    sys.path.insert(0, _MODEL_OCR_DIR)

_modele = None
_reader = None


def _charger():
    """Charge le modèle YOLO + le Reader EasyOCR une seule fois (singleton)."""
    global _modele, _reader
    if _modele is not None and _reader is not None:
        return _modele, _reader

    from ultralytics import YOLO
    import easyocr

    t0 = time.monotonic()
    chemin_modele = os.path.join(_MODEL_OCR_DIR, "model", "cni_yolov8s.pt")
    modele = YOLO(chemin_modele)
    # gpu=False : pas de GPU garanti sur le VPS de prod (à ajuster si un GPU
    # est confirmé disponible en prod, cf. Tâche K.2 du roadmap).
    reader = easyocr.Reader(["fr"], gpu=False)
    print(f"🔎 Modèle OCR CNI chargé en {time.monotonic() - t0:.1f}s (singleton, une seule fois par process)")

    _modele, _reader = modele, reader
    return _modele, _reader


def _extraire_sync(recto_bytes: bytes, verso_bytes: bytes) -> dict:
    """Partie bloquante (I/O fichiers temporaires + inférence) — exécutée dans un thread."""
    from cni_pipeline import process_cni, CLASS_NAMES

    modele, reader = _charger()

    with tempfile.NamedTemporaryFile(suffix="_recto.jpg", delete=False) as f_recto:
        f_recto.write(recto_bytes)
        chemin_recto = f_recto.name
    with tempfile.NamedTemporaryFile(suffix="_verso.jpg", delete=False) as f_verso:
        f_verso.write(verso_bytes)
        chemin_verso = f_verso.name

    try:
        return process_cni(chemin_recto, chemin_verso, modele, CLASS_NAMES, reader)
    finally:
        for chemin in (chemin_recto, chemin_verso):
            try:
                os.remove(chemin)
            except OSError:
                pass


async def extraire_cni(recto_bytes: bytes, verso_bytes: bytes) -> dict:
    """
    Lance le pipeline OCR CNI (YOLO + EasyOCR) sur les deux photos (recto,
    verso) réellement uploadées — jamais bloquant pour l'event loop
    (asyncio.to_thread : le calcul, bloquant, tourne dans un thread séparé).

    Retourne un dict `{classe_yolo: {value_cleaned, confidence_detection,
    needs_review, is_valid_format, source}}` pour les 14 classes possibles
    (cf. model_OCR/CLASSES_CNI.md) — une entrée à `value_cleaned: None` pour
    toute classe non détectée sous le seuil de confiance.
    """
    return await asyncio.to_thread(_extraire_sync, recto_bytes, verso_bytes)
