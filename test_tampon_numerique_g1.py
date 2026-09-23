"""
Test manuel — Sprint G, Tâche G.1 (tampon numérique + confirmation journalisée).

Critère de validation explicite : enregistrer un tampon de test, vérifier
qu'il est bien lié à la BONNE commune et que la confirmation est journalisée.

Vérifie aussi les deux repli explicites :
  - upload SANS cocher la confirmation -> 400, rien n'est enregistré.
  - upload avec un format de fichier invalide -> 415.
"""
import io
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import main  # noqa: E402
from test_bascule_administratif import TEST_CITOYEN_ID  # profil réel existant, sert de FK admin_id

client = TestClient(main.app)
main.app.dependency_overrides[main.get_current_admin] = lambda: {"id": TEST_CITOYEN_ID, "commune": "National"}


def generer_image_tampon() -> bytes:
    img = Image.new("RGBA", (300, 300), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([10, 10, 290, 290], outline=(180, 30, 30, 255), width=8)
    draw.text((70, 140), "MAIRIE DE TEST", fill=(180, 30, 30, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def main_test():
    commune_rb = main.resoudre_commune_id("Ross-Béthio")
    commune_dakar = main.resoudre_commune_id("Dakar")
    assert commune_rb and commune_dakar

    image = generer_image_tampon()

    # --- 1. Sans confirmation cochée -> 400, rien d'enregistré ------------------
    print("=== 1. Upload SANS confirmation (attendu : 400) ===")
    r_sans_confirmation = client.post(
        f"/admin/communes/{commune_rb}/tampon",
        files={"fichier": ("tampon.png", image, "image/png")},
        data={"confirmation": "false"},
    )
    assert r_sans_confirmation.status_code == 400, r_sans_confirmation.text
    print("✅ Refusé sans confirmation :", r_sans_confirmation.json()["detail"])

    # --- 2. Format invalide -> 415 ----------------------------------------------
    print("\n=== 2. Format invalide (attendu : 415) ===")
    r_format_invalide = client.post(
        f"/admin/communes/{commune_rb}/tampon",
        files={"fichier": ("tampon.pdf", b"%PDF-1.4 pas une image", "application/pdf")},
        data={"confirmation": "true"},
    )
    assert r_format_invalide.status_code == 415, r_format_invalide.text
    print("✅ Format invalide rejeté :", r_format_invalide.json()["detail"])

    # --- 3. Upload réel, confirmé -------------------------------------------------
    print("\n=== 3. Upload confirmé pour Ross-Béthio (attendu : 200) ===")
    r = client.post(
        f"/admin/communes/{commune_rb}/tampon",
        files={"fichier": ("tampon.png", image, "image/png")},
        data={"confirmation": "true"},
    )
    assert r.status_code == 200, r.text
    corps = r.json()
    print("Réponse :", corps)
    assert corps["commune_id"] == commune_rb
    assert corps["fichier_url"].startswith(commune_rb + "/"), "Le chemin de stockage ne rattache pas le fichier à la bonne commune !"
    assert corps["confirmation"]["commune_id"] == commune_rb
    assert corps["confirmation"]["admin_id"] == TEST_CITOYEN_ID
    print("✅ Tampon lié à la bonne commune (chemin de stockage préfixé par commune_id).")

    # --- 4. Vérifie EN BASE que communes.tampon_numerique_url pointe dessus -----
    print("\n=== 4. GET /admin/communes — vérifie le lien en base ===")
    r_communes = client.get("/admin/communes")
    assert r_communes.status_code == 200
    commune_rb_relue = next(c for c in r_communes.json()["communes"] if c["id"] == commune_rb)
    assert commune_rb_relue["tampon_numerique_url"] == corps["fichier_url"]
    assert commune_rb_relue.get("tampon_url_signee"), "URL signée manquante — le fichier n'est peut-être pas dans Storage"
    print(f"✅ communes.tampon_numerique_url en base = {commune_rb_relue['tampon_numerique_url']!r}")

    # Vérifie que Dakar (une AUTRE commune) n'a PAS été affectée.
    commune_dakar_relue = next(c for c in r_communes.json()["communes"] if c["id"] == commune_dakar)
    assert commune_dakar_relue["tampon_numerique_url"] != corps["fichier_url"], "Le tampon de Ross-Béthio s'est retrouvé sur Dakar !"
    print("✅ La commune de Dakar n'est pas affectée (isolation par commune confirmée).")

    # --- 5. Téléchargement réel du fichier stocké --------------------------------
    print("\n=== 5. Téléchargement réel via l'URL signée ===")
    import httpx
    r_fichier = httpx.get(commune_rb_relue["tampon_url_signee"])
    assert r_fichier.status_code == 200
    assert r_fichier.headers.get("content-type") == "image/png"
    print(f"✅ Fichier réel téléchargé : {len(r_fichier.content)} octets, image/png.")

    # --- 6. LA CONFIRMATION EST JOURNALISÉE (critère de validation explicite) ---
    print("\n=== 6. GET /admin/communes/{id}/tampon-confirmations — vérifie le journal ===")
    r_journal = client.get(f"/admin/communes/{commune_rb}/tampon-confirmations")
    assert r_journal.status_code == 200
    confirmations = r_journal.json()["confirmations"]
    assert confirmations, "Aucune confirmation journalisée !"
    derniere = confirmations[0]  # la plus récente d'abord
    print("Dernière confirmation journalisée :", derniere)
    assert derniere["commune_id"] == commune_rb
    assert derniere["admin_id"] == TEST_CITOYEN_ID
    assert derniere["fichier_url"] == corps["fichier_url"]
    assert derniere["confirme_le"], "confirme_le (horodatage) manquant !"
    assert derniere["admin_email"], "L'email de l'admin n'a pas été résolu (enrichissement Auth) !"
    print(f"✅ Confirmation journalisée : admin={derniere['admin_email']!r}, horodatée à {derniere['confirme_le']!r}.")

    print("\n✅ Tâche G.1 : tampon numérique + confirmation journalisée — OK")


if __name__ == "__main__":
    main_test()
