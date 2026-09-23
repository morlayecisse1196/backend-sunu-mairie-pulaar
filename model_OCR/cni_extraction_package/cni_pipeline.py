
import cv2
import re
import os
import tempfile
import time
import json
from ultralytics import YOLO
import easyocr

CLASS_NAMES = ['annot', 'bp', 'bureau', 'com', 'dob', 'dp', 'fname', 'id', 'lieu', 'lname', 'nin', 'numero', 'region', 'sex']

RECTO_CLASSES = {"fname", "lname", "dob", "sex", "id", "bp"}
VERSO_CLASSES = {"region", "annot", "com", "dp", "bureau", "nin", "numero", "lieu"}
ALL_CLASSES = set(CLASS_NAMES)

CONFIDENCE_THRESHOLDS = {
    "sex": 0.4, "dp": 0.4, "region": 0.4, "bureau": 0.4,
    "nin": 0.4, "numero": 0.4, "annot": 0.4, "dob": 0.4, "id": 0.4, "com": 0.4,
    "bp": 0.25, "lieu": 0.25, "fname": 0.25, "lname": 0.25,
}
FRAGILE_CLASSES = {"bp", "lieu", "fname", "lname"}
# Bug réel corrigé (Sprint K, Tâche K.1, 2026-09) : les 5 regex ci-dessous
# étaient doublement échappées (r"\\d" au lieu de r"\d") — dans une chaîne
# RAW Python, "\\d" représente DEUX caractères backslash littéraux suivis de
# "d", pas la classe regex \d. Conséquence réelle : le nettoyage d'un numéro
# de CNI/NIN (re.sub(r"[^\\d\\s]", ...)) supprimait TOUS les chiffres au lieu
# de ne garder qu'eux, et la validation de date ne matchait jamais une vraie
# date "12/03/1998" (is_valid_format restait toujours False). Voir
# test_cni_pipeline_regex_k1.py pour la preuve avec de vraies valeurs.
DATE_PATTERN = re.compile(r"\d{2}/\d{2}/\d{4}")


def clean_field(cls_name, raw_text):
    text = raw_text.strip()
    if cls_name == "sex":
        match = re.search(r"\b([MF])\b", text.upper())
        return match.group(1) if match else text
    if cls_name in ("dob", "dp"):
        match = DATE_PATTERN.search(text)
        return match.group(0) if match else text
    if cls_name in ("id", "bureau", "numero", "nin"):
        cleaned = re.sub(r"[^\d\s]", "", text).strip()
        return cleaned if cleaned else text
    if cls_name in ("fname", "lname", "lieu", "bp", "region", "com", "annot"):
        return text.upper().strip()
    return text


def validate_field(cls_name, value):
    textual_fields = ("fname", "lname", "lieu", "bp", "region", "com", "annot", "dp")
    if cls_name in textual_fields:
        if DATE_PATTERN.search(value):
            return False
        return len(value) > 0
    if cls_name == "dob":
        return bool(re.match(r"^\d{2}/\d{2}/\d{4}$", value))
    if cls_name == "sex":
        return value in ("M", "F")
    if cls_name == "id":
        return len(re.sub(r"\s", "", value)) >= 10
    return len(value) > 0


def detect_and_correct_orientation(image_path, reader):
    img = cv2.imread(image_path)
    best_config = None
    best_score = -1
    for flip in [False, True]:
        base = cv2.flip(img, 1) if flip else img
        for angle in [0, 90, 180, 270]:
            if angle == 0:
                rotated = base
            elif angle == 90:
                rotated = cv2.rotate(base, cv2.ROTATE_90_CLOCKWISE)
            elif angle == 180:
                rotated = cv2.rotate(base, cv2.ROTATE_180)
            else:
                rotated = cv2.rotate(base, cv2.ROTATE_90_COUNTERCLOCKWISE)
            ocr_result = reader.readtext(rotated, detail=1)
            avg_conf = sum(r[2] for r in ocr_result) / len(ocr_result) if ocr_result else 0
            if avg_conf > best_score:
                best_score = avg_conf
                best_config = (flip, angle)

    flip, angle = best_config
    base = cv2.flip(img, 1) if flip else img
    if angle == 90:
        corrected = cv2.rotate(base, cv2.ROTATE_90_CLOCKWISE)
    elif angle == 180:
        corrected = cv2.rotate(base, cv2.ROTATE_180)
    elif angle == 270:
        corrected = cv2.rotate(base, cv2.ROTATE_90_COUNTERCLOCKWISE)
    else:
        corrected = base

    base_name = os.path.splitext(os.path.basename(image_path))[0]
    # Bug réel corrigé (Tâche K.1) : "/tmp" codé en dur n'existe pas sur
    # Windows (environnement de dev) — tempfile.gettempdir() est portable.
    output_path = os.path.join(tempfile.gettempdir(), f"_corrected_{base_name}_{int(time.time()*1000)}.jpg")
    cv2.imwrite(output_path, corrected)
    return output_path


def extract_fields(image_path, model, class_names, reader):
    img = cv2.imread(image_path)
    results = model.predict(image_path, conf=0.15, save=False, verbose=False)
    extracted = {}
    for box in results[0].boxes:
        cls_id = int(box.cls[0])
        cls_name = class_names[cls_id]
        conf = float(box.conf[0])
        threshold = CONFIDENCE_THRESHOLDS.get(cls_name, 0.4)
        if conf < threshold:
            continue
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        crop = img[y1:y2, x1:x2]
        ocr_result = reader.readtext(crop, detail=0)
        text = " ".join(ocr_result).strip()
        entry = {
            "value": text,
            "confidence_detection": round(conf, 2),
            "needs_review": cls_name in FRAGILE_CLASSES or conf < 0.5
        }
        if cls_name not in extracted or conf > extracted[cls_name]["confidence_detection"]:
            extracted[cls_name] = entry
    return extracted


def merge_recto_verso(result_recto, result_verso):
    merged = {}
    for cls_name, entry in result_recto.items():
        merged[cls_name] = {**entry, "source": "recto"}
    for cls_name, entry in result_verso.items():
        if cls_name in merged:
            if entry["confidence_detection"] > merged[cls_name]["confidence_detection"]:
                merged[cls_name] = {**entry, "source": "verso"}
        else:
            merged[cls_name] = {**entry, "source": "verso"}
    return merged


def process_cni(recto_path, verso_path, model, class_names, reader):
    recto_corrected = detect_and_correct_orientation(recto_path, reader)
    verso_corrected = detect_and_correct_orientation(verso_path, reader)

    try:
        result_recto = extract_fields(recto_corrected, model, class_names, reader)
        result_verso = extract_fields(verso_corrected, model, class_names, reader)
    finally:
        # Bug réel corrigé (Tâche K.1) : les fichiers corrigés (orientation)
        # n'étaient jamais supprimés — une fuite de fichiers temporaires à
        # chaque appel (2 fichiers/appel, jamais nettoyés).
        for chemin in (recto_corrected, verso_corrected):
            try:
                os.remove(chemin)
            except OSError:
                pass

    for res in (result_recto, result_verso):
        for cls_name, entry in res.items():
            cleaned = clean_field(cls_name, entry["value"])
            entry["value_cleaned"] = cleaned
            entry["is_valid_format"] = validate_field(cls_name, cleaned)

    merged = merge_recto_verso(result_recto, result_verso)

    final = {}
    for cls_name in ALL_CLASSES:
        if cls_name in merged:
            final[cls_name] = merged[cls_name]
        else:
            final[cls_name] = {
                "value_cleaned": None, "confidence_detection": None,
                "needs_review": True, "is_valid_format": False, "source": None
            }
    return final


if __name__ == "__main__":
    model = YOLO("model/cni_yolov8s.pt")
    reader = easyocr.Reader(["fr"], gpu=True)
    result = process_cni("recto.jpg", "verso.jpg", model, CLASS_NAMES, reader)
    print(json.dumps(result, indent=2, ensure_ascii=False))
