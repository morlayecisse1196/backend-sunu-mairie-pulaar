"""
Test manuel — correctif du 2026-09-11 (retour terrain avatar 3D) :
tts_service.synthesize_stream() doit désormais précharger la synthèse de la
phrase N+1 PENDANT l'envoi/traitement de la phrase N, au lieu de synthétiser
chaque phrase l'une après l'autre (chaque `await synthesize_remote(...)`
attendant la précédente avant même de démarrer).

Remplace `synthesize_remote` par une doublure à délai artificiel FIXE et
mesure les horodatages réels de début/fin de chaque appel — sans ça,
impossible de distinguer "pipeliné" de "séquentiel" juste en regardant le
résultat final (le texte joué est identique dans les deux cas, seul le TIMING
change, ce qui est précisément ce qui causait le bug remonté par
l'utilisateur : l'avatar visible "s'arrêtant" entre deux phrases).
"""
import asyncio
import sys
import time
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import tts_service as ts

DELAIS_PAR_PHRASE = [0.30, 0.22, 0.35, 0.18]  # secondes, volontairement variés (une vraie synthèse
# distante n'a jamais une latence parfaitement identique phrase après phrase — un délai uniforme
# produirait un artefact de test où deux tâches démarrées à un tick d'écart finissent exactement au
# même instant, ce qui les fait "résonner" par paires plutôt que de rester décalées d'une phrase.


class FauxWebSocket:
    def __init__(self):
        self.envois = []

    async def send_bytes(self, data):
        self.envois.append(("bytes", data))

    async def send_text(self, data):
        self.envois.append(("text", data))


async def main_test():
    appels = []  # (index, debut, fin)

    async def fausse_synthese_remote(text, timeout=None):
        idx = int(text.rstrip(".!?").split()[-1])
        debut = time.monotonic()
        await asyncio.sleep(DELAIS_PAR_PHRASE[idx])
        fin = time.monotonic()
        appels.append((idx, debut, fin))
        return f"audio-{idx}".encode()

    # Monkeypatch au niveau du module tts_service (c'est bien le nom importé
    # là-bas, `from tts_client import synthesize_remote`, qu'il faut remplacer
    # — remplacer tts_client.synthesize_remote directement n'aurait aucun
    # effet ici, tts_service a déjà sa propre référence liée à l'import).
    ts.synthesize_remote = fausse_synthese_remote

    texte = "phrase 0. phrase 1. phrase 2. phrase 3."
    service = ts.PulaarTTSService()
    ws = FauxWebSocket()

    t0 = time.monotonic()
    await service.synthesize_stream(texte, ws)
    duree_totale = time.monotonic() - t0

    print(f"Durée totale : {duree_totale:.2f}s (4 phrases, délais {DELAIS_PAR_PHRASE}s)")
    for idx, debut, fin in sorted(appels):
        print(f"  phrase {idx} : synthèse de t={debut - t0:.2f}s à t={fin - t0:.2f}s")

    # --- Critère 1 : chevauchement réel (au moins un) entre synthèses ---
    # Avec un pool à concurrence bornée (TTS_PREFETCH_CONCURRENCY=2), TOUTES
    # les frontières ne montrent pas forcément un chevauchement : dès que les
    # 2 places sont occupées, la phrase suivante démarre exactement quand une
    # place se libère (ni avant, ni après) — c'est optimal, pas un défaut.
    # Ce qui distingue réellement "pipeliné" de l'ancien code séquentiel,
    # c'est qu'AU MOINS un chevauchement existe (les 2 premières phrases
    # démarrent ensemble) — l'ancien code n'en produisait STRUCTURELLEMENT
    # aucun (chaque synthèse suivante ne démarrait qu'après la fin complète
    # de la précédente, vérifié par une version antérieure de ce test).
    appels_tries = sorted(appels)
    chevauchements = 0
    for i in range(len(appels_tries) - 1):
        _, _, fin_n = appels_tries[i]
        _, debut_n1, _ = appels_tries[i + 1]
        if debut_n1 < fin_n - 0.01:  # marge pour le bruit de scheduling
            chevauchements += 1
    print(f"\nChevauchements détectés : {chevauchements}/{len(appels_tries) - 1}")
    assert chevauchements >= 1, (
        "aucun chevauchement détecté — toujours séquentiel, le pool de préchargement ne fonctionne pas"
    )
    print("OK - au moins une synthèse suivante démarre bien AVANT la fin de la précédente (pipeliné).")

    # --- Critère 2 : durée totale proche du délai MAX rencontré (le goulot),
    # pas de la SOMME des délais (ce que donnerait l'ancien code séquentiel).
    duree_sequentielle_attendue = sum(DELAIS_PAR_PHRASE)
    print(f"\nDurée séquentielle qu'aurait pris l'ancien code : ~{duree_sequentielle_attendue:.2f}s")
    assert duree_totale < duree_sequentielle_attendue * 0.6, (
        f"durée totale ({duree_totale:.2f}s) trop proche du séquentiel "
        f"({duree_sequentielle_attendue:.2f}s) — le chevauchement n'accélère pas réellement"
    )
    print(f"OK - durée totale ({duree_totale:.2f}s) très inférieure au séquentiel — le pipelining réduit bien le silence entre phrases.")

    # --- Critère 3 : le contenu envoyé au WebSocket reste correct et dans l'ordre ---
    envois_bytes = [e for t, e in ws.envois if t == "bytes"]
    assert envois_bytes == [b"audio-0", b"audio-1", b"audio-2", b"audio-3"], envois_bytes
    print("OK - l'audio de chaque phrase est bien envoyé dans le bon ordre malgré le chevauchement des synthèses.")

    print("\n✅ Correctif de pipelining TTS validé : silence entre phrases réduit, ordre et contenu inchangés.")


if __name__ == "__main__":
    asyncio.run(main_test())
