"""
Script ponctuel — Sprint F, Tâche F.3 : prépare un dossier de test réaliste
pour la vérification manuelle en navigateur (pas un test automatisé
permanent) :
  - slots du dialogue remplis (comme un vrai dossier "tardif" en_traitement),
    pour que les champs `dateNaissance`, `lieuNaissance`, `nomDeclarant`,
    `parentsMaries` du formulaire apparaissent bien pré-remplis, source
    "dialogue" (cf. _MAPPING_CHAMP_VERS_SLOT dans dialogue_engine.py) ;
  - une VRAIE image (PNG généré avec Pillow, pas les faux octets JPEG des
    autres tests) uploadée comme certificat_naissance, pour valider le zoom
    sur "un document réel" (critère de validation explicite de F.3) ;
  - un second document (cni_declarant) sans image utilisable, pour valider
    la navigation par miniatures entre plusieurs documents.
"""
import io
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

import main  # noqa: E402
from test_bascule_administratif import TEST_CITOYEN_ID

TOKEN = "override-dependance-pas-de-vrai-jwt-necessaire"
main.app.dependency_overrides[main.get_current_user] = lambda: {"id": TEST_CITOYEN_ID, "commune": "Ross-Béthio"}
client = TestClient(main.app)


def generer_image_certificat() -> bytes:
    """Reproduit visuellement, en très simplifié, un certificat de naissance
    manuscrit — assez pour tester zoom/pan sur un vrai contenu lisible."""
    img = Image.new("RGB", (1200, 1600), color=(250, 246, 235))
    draw = ImageDraw.Draw(img)
    try:
        police_titre = ImageFont.truetype("arial.ttf", 42)
        police_texte = ImageFont.truetype("arial.ttf", 28)
    except Exception:
        police_titre = ImageFont.load_default()
        police_texte = ImageFont.load_default()

    draw.rectangle([20, 20, 1180, 1580], outline=(60, 60, 60), width=3)
    draw.text((60, 60), "RÉPUBLIQUE DU SÉNÉGAL", font=police_titre, fill=(20, 20, 20))
    draw.text((60, 120), "CERTIFICAT DE NAISSANCE", font=police_titre, fill=(20, 20, 20))
    draw.line([60, 190, 1140, 190], fill=(60, 60, 60), width=2)

    lignes = [
        "Nom de l'enfant : Marya NDOYE",
        "Née le : 14 octobre 1967",
        "Lieu de naissance : Ross-Béthio",
        "Nom du père (déclarant) : Babacar DIOP",
        "Nom de la mère : Salimata DIOP",
        "Sexe : Féminin",
        "",
        "Structure de santé : Poste de santé de Ross-Béthio",
        "Cachet et signature de l'agent d'état civil : (illisible, zoomer ici)",
    ]
    y = 260
    for ligne in lignes:
        draw.text((60, y), ligne, font=police_texte, fill=(30, 30, 30))
        y += 70

    # Petit détail volontairement fin, pour vérifier utilement le zoom.
    draw.text((80, y + 40), "N° registre local (petit texte, zoomer pour lire) : 0451/1967", font=police_texte, fill=(80, 80, 80))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def main_test():
    commune_id = main.resoudre_commune_id("Ross-Béthio")
    slots = dict(main.SLOTS_VIDES_EXTRAIT_NAISSANCE)
    slots.update({
        "nom_enfant": "Marya Ndoye",
        "date_naissance_enfant": "1967-10-14",
        "commune_naissance": "Ross-Béthio",
        "nom_declarant": "Babacar Diop",
        "nom_mere": "Salimata Diop",
        "date_naissance_mere": "1940-01-01",
        "parents_maries": True,
        "age_enfant": {"valeur": 58, "unite": "annees"},
    })
    dossier = main.create_dossier(
        citoyen_id=TEST_CITOYEN_ID, type_demarche="extrait_naissance",
        slots=slots, cas_legal="tardif", commune_id=commune_id, statut="en_traitement",
    )
    assert dossier
    dossier_id = dossier["id"]
    print(f"📁 Dossier de test F.3 : {dossier_id}")

    image_reelle = generer_image_certificat()
    r1 = client.post(
        f"/dossiers/{dossier_id}/documents",
        data={"type": "certificat_naissance"},
        files={"fichier": ("certificat_naissance.png", image_reelle, "image/png")},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert r1.status_code == 200, r1.text
    print(f"🖼️  Image réelle uploadée (certificat_naissance) : {len(image_reelle)} octets")

    r2 = client.post(
        f"/dossiers/{dossier_id}/documents",
        data={"type": "cni_declarant"},
        files={"fichier": ("cni_declarant.png", generer_image_certificat(), "image/png")},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert r2.status_code == 200, r2.text
    print("🖼️  Second document uploadé (cni_declarant) — pour tester la navigation par miniatures")

    print(f"\n✅ Dossier prêt pour vérification manuelle F.3 : {dossier_id}")
    print(f"   URL : http://localhost:3000/consultant/dossiers/{dossier_id}")


if __name__ == "__main__":
    main_test()
