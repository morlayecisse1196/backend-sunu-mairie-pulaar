# Pipeline extraction CNI (YOLO + EasyOCR)

## Contenu
- model/cni_yolov8s.pt : modèle YOLOv8s entraîné (14 classes, run3)
- cni_pipeline.py : pipeline complet (orientation, détection, OCR, nettoyage, validation)

## Installation
pip install ultralytics easyocr opencv-python

## Utilisation
from cni_pipeline import process_cni, CLASS_NAMES
from ultralytics import YOLO
import easyocr

model = YOLO("model/cni_yolov8s.pt")
reader = easyocr.Reader(["fr"], gpu=True)
result = process_cni("recto.jpg", "verso.jpg", model, CLASS_NAMES, reader)

## Notes
- Champs recto: ['bp', 'dob', 'fname', 'id', 'lname', 'sex']
- Champs verso: ['annot', 'bureau', 'com', 'dp', 'lieu', 'nin', 'numero', 'region']
- Champs fragiles (needs_review systématique): bp, lieu, fname, lname
- Champs non détectés retournent value_cleaned=null (à compléter manuellement côté app)
