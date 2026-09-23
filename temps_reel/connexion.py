"""
Gestion d'une connexion WebSocket de dialogue — commune aux protocoles v1 et v2.

Architecture d'une connexion :

  lecteur (boucle permanente)          travailleur (file de tours, un à la fois)
  ───────────────────────────          ─────────────────────────────────────────
  audio / texte  → accusé + file  →    PHASE A « comprendre » (verrou de session)
  interrupt      → annule la parole       audio → WAV → ASR → moteur → persistance
  ping           → pong                   (menée à terme même si le client part)
  auth_refresh   → nouveau jeton        PHASE B « parler » (annulable)
  nouvelle_conv. → file                   stream_fr → traduction + TTS → end

Protocole v1 (`/ws/{session_id}?token=…`, app mobile actuelle) : jeton dans
l'URL, clé de session fournie par l'app. Protocole v2 (`/ws/v2`) : jeton dans
le premier message, renouvelable, session attribuée par le serveur. Les deux
reçoivent le même sur-ensemble de messages (le client v1 ignore les types
qu'il ne connaît pas). Contrat complet : README-TEMPS-REEL-MOBILE.md.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

import conversations_repo
from asr_client import transcribe_audio
from auth import get_user_profile, verify_token
from services import db
from services.journal import obtenir_logger
from temps_reel import audio, moteur, parole
from temps_reel.etat import instantane_client
from temps_reel.moteur import ResultatTour
from temps_reel.registre import registre as registre_global
from temps_reel.sessions import ErreurPersistance, SessionEtrangere, magasin as magasin_global

log = obtenir_logger("connexion")

PROTOCOLE_V1 = 1
PROTOCOLE_V2 = 2

DELAI_AUTHENTIFICATION = 10.0
DELAI_SIGNAL_LENTEUR = 6.0
DELAI_MAX_PHASE_COMPRENDRE = 150.0
DELAI_FIN_TRAVAIL_APRES_DECONNEXION = DELAI_MAX_PHASE_COMPRENDRE + 15.0
GRACE_JETON_EXPIRE_SECONDES = 300
TAILLE_MAX_FILE = 3
TAILLE_MAX_TEXTE = 1000
TAILLE_MAX_TURN_ID = 64


class CodesFermeture:
    V1_REFUS = 1008
    AUTH_INVALIDE = 4401
    SESSION_ETRANGERE = 4403
    AUTH_DELAI = 4408
    SESSION_REMPLACEE = 4409
    INDISPONIBLE = 1011


def _enregistrer_messages_sync(etat: dict, texte_citoyen: Optional[str], reponse_fr: str) -> tuple[Optional[str], Optional[str]]:
    conversation = conversations_repo.get_or_create_conversation(
        etat["id"], etat["citoyen_id"], etat["mode"], etat.get("dossier_id"), premier_message=texte_citoyen
    )
    if not conversation:
        return None, None
    if texte_citoyen:
        conversations_repo.ajouter_message(conversation["id"], "user", texte_citoyen)
    message = conversations_repo.ajouter_message(conversation["id"], "assistant", reponse_fr, None)
    return conversation["id"], (message or {}).get("id")


def _maj_pulaar_sync(message_id: str, pulaar: str) -> None:
    conversations_repo.mettre_a_jour_pulaar(message_id, pulaar)


def _turn_id(valeur) -> str:
    if isinstance(valeur, str) and valeur.strip():
        return valeur.strip()[:TAILLE_MAX_TURN_ID]
    return uuid.uuid4().hex[:12]


class Connexion:
    def __init__(self, websocket: WebSocket, *, protocole: int, magasin=None, registre=None):
        self.ws = websocket
        self.protocole = protocole
        self.magasin = magasin or magasin_global
        self.registre = registre or registre_global
        self.citoyen_id: Optional[str] = None
        self.commune: str = "National"
        self.jeton_exp: Optional[int] = None
        self.etat: Optional[dict] = None
        self.fermee = False

        self._verrou_envoi = asyncio.Lock()
        self._file: asyncio.Queue = asyncio.Queue()
        self._travailleur: Optional[asyncio.Task] = None
        self._tache_parole: Optional[asyncio.Task] = None
        self._tour_courant: Optional[str] = None
        self._turn_id_annonce: Optional[str] = None

    # ------------------------------------------------------------------ envoi

    async def envoyer_json(self, message: dict) -> None:
        if self.fermee:
            return
        try:
            async with self._verrou_envoi:
                await self.ws.send_text(json.dumps(message, ensure_ascii=False))
        except Exception:  # noqa: BLE001 — client parti : on arrête d'émettre
            self.fermee = True

    async def envoyer_octets(self, octets: bytes) -> None:
        if self.fermee:
            return
        try:
            async with self._verrou_envoi:
                await self.ws.send_bytes(octets)
        except Exception:  # noqa: BLE001
            self.fermee = True

    async def _fermer(self, code: int, raison: str) -> None:
        self.fermee = True
        try:
            await self.ws.close(code=code, reason=raison)
        except Exception:  # noqa: BLE001
            pass

    async def _erreur(self, code: str, contenu: str, turn_id: Optional[str] = None, recuperable: bool = True) -> None:
        await self.envoyer_json({"type": "error", "code": code, "content": contenu, "recuperable": recuperable, "turn_id": turn_id})

    # --------------------------------------------------------- établissement

    async def _identifier(self, jeton: str) -> None:
        charge = await verify_token(jeton)
        if not charge.get("sub"):
            raise ValueError("jeton sans sujet")
        profil = await get_user_profile(charge["sub"])
        self.citoyen_id = charge["sub"]
        self.commune = profil.get("commune") or "National"
        self.jeton_exp = charge.get("exp")

    async def demarrer_v1(self, cle_client: str, jeton: Optional[str]) -> None:
        if not jeton:
            await self._fermer(CodesFermeture.V1_REFUS, "Token manquant")
            return
        try:
            await self._identifier(jeton)
        except Exception:  # noqa: BLE001
            await self._fermer(CodesFermeture.V1_REFUS, "Token invalide")
            return
        try:
            reprise = await self._attacher_session(cle_client=cle_client[:128])
        except SessionEtrangere:
            await self._fermer(CodesFermeture.V1_REFUS, "Session d'un autre utilisateur")
            return
        except ErreurPersistance:
            await self._fermer(CodesFermeture.INDISPONIBLE, "Service momentanément indisponible")
            return
        await self.ws.accept()
        await self._annoncer_session(reprise=reprise)
        await self._boucle()

    async def demarrer_v2(self) -> None:
        await self.ws.accept()
        try:
            brut = await asyncio.wait_for(self.ws.receive_text(), DELAI_AUTHENTIFICATION)
        except asyncio.TimeoutError:
            await self._fermer(CodesFermeture.AUTH_DELAI, "Authentification attendue")
            return
        except Exception:  # noqa: BLE001 — déconnexion ou premier message binaire
            await self._fermer(CodesFermeture.AUTH_INVALIDE, "Premier message attendu : auth")
            return

        try:
            donnees = json.loads(brut)
        except json.JSONDecodeError:
            donnees = {}
        if not isinstance(donnees, dict) or donnees.get("type") != "auth" or not donnees.get("token"):
            await self._fermer(CodesFermeture.AUTH_INVALIDE, "Premier message attendu : auth")
            return
        try:
            await self._identifier(str(donnees["token"]))
        except Exception:  # noqa: BLE001
            await self._fermer(CodesFermeture.AUTH_INVALIDE, "Jeton invalide ou expiré")
            return

        cle = donnees.get("session_id")
        try:
            reprise = await self._attacher_session(
                cle_client=str(cle)[:128] if cle else None, nouvelle=bool(donnees.get("nouvelle_conversation"))
            )
        except SessionEtrangere:
            await self._fermer(CodesFermeture.SESSION_ETRANGERE, "Session d'un autre utilisateur")
            return
        except ErreurPersistance:
            await self._fermer(CodesFermeture.INDISPONIBLE, "Service momentanément indisponible")
            return

        await self.envoyer_json({"type": "auth_ok", "protocole": PROTOCOLE_V2, "exp": self.jeton_exp})
        await self._annoncer_session(reprise=reprise)
        await self._boucle()

    async def _attacher_session(self, *, cle_client: Optional[str], nouvelle: bool = False) -> bool:
        etat, reprise = await self.magasin.ouvrir(
            citoyen_id=self.citoyen_id, commune_profil=self.commune, cle_client=cle_client, nouvelle=nouvelle
        )
        self._adopter(etat)
        return reprise

    def _adopter(self, etat: dict) -> None:
        if self.etat is not None:
            self.registre.retirer(self, self.etat["id"])
        self.etat = etat
        remplacee = self.registre.enregistrer(self)
        if remplacee is not None:
            asyncio.ensure_future(remplacee.remplacer())

    async def remplacer(self) -> None:
        """Une autre connexion a pris cette session (autre appareil, reconnexion)."""
        await self.envoyer_json({"type": "session_remplacee"})
        await self._fermer(CodesFermeture.SESSION_REMPLACEE, "Session reprise par une autre connexion")

    async def adopter_session_externe(self, etat: dict) -> None:
        """Session changée hors WebSocket (ex. POST /conversations)."""
        await self._interrompre()
        self._adopter(etat)
        await self._annoncer_session(reprise=False, nouvelle=True)

    async def _annoncer_session(self, *, reprise: bool, nouvelle: bool = False) -> None:
        etat = self.etat
        await self.envoyer_json({"type": "session", "protocole": self.protocole, "reprise": reprise, "nouvelle": nouvelle, **instantane_client(etat)})
        if etat.get("document_en_attente"):
            await self.envoyer_json({"type": "attente_upload", "document_type": etat["document_en_attente"], "dossier_id": etat.get("dossier_id")})
        reponse_en_attente = etat.pop("reponse_en_attente", None)
        if reponse_en_attente:
            self.pousser(ResultatTour(reponse_en_attente, document_attendu=etat.get("document_en_attente")))
        else:
            await self.envoyer_json({"type": "status", "state": "listening"})

    # ---------------------------------------------------------------- lecture

    async def _boucle(self) -> None:
        self._travailleur = asyncio.create_task(self._travailler())
        try:
            while not self.fermee:
                message = await self.ws.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    await self._recevoir_audio(message["bytes"])
                elif message.get("text") is not None:
                    await self._recevoir_texte(message["text"])
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            self.fermee = True
            await self._interrompre(signaler=False)
            self._file.put_nowait(None)
            # La phase A en cours va jusqu'au bout (état et base cohérents), dans une limite de temps.
            termine, _ = await asyncio.wait({self._travailleur}, timeout=DELAI_FIN_TRAVAIL_APRES_DECONNEXION)
            if not termine:
                self._travailleur.cancel()
            if self.etat is not None:
                self.registre.retirer(self, self.etat["id"])

    async def _recevoir_audio(self, octets: bytes) -> None:
        turn_id = self._turn_id_annonce or _turn_id(None)
        self._turn_id_annonce = None
        await self.envoyer_json({"type": "audio_recu", "turn_id": turn_id, "octets": len(octets)})
        await self._mettre_en_file("audio", turn_id, octets)

    async def _recevoir_texte(self, brut: str) -> None:
        try:
            donnees = json.loads(brut)
        except json.JSONDecodeError:
            donnees = None
        if not isinstance(donnees, dict):
            await self._erreur("message_invalide", "Message illisible.")
            return

        genre = donnees.get("type")
        if genre == "ping":
            await self.envoyer_json({"type": "pong", "t": donnees.get("t")})
        elif genre == "audio_debut":
            self._turn_id_annonce = _turn_id(donnees.get("turn_id"))
        elif genre == "texte":
            texte = str(donnees.get("texte") or "").strip()[:TAILLE_MAX_TEXTE]
            if texte:
                await self._mettre_en_file("texte", _turn_id(donnees.get("turn_id")), texte)
        elif genre == "interrupt":
            await self._interrompre()
            await self.envoyer_json({"type": "status", "state": "listening", "turn_id": self._tour_courant})
        elif genre == "auth_refresh":
            await self._renouveler_jeton(donnees.get("token"))
        elif genre == "nouvelle_conversation":
            await self._interrompre()
            self._file.put_nowait(("nouvelle", _turn_id(donnees.get("turn_id")), None))
        else:
            await self._erreur("type_inconnu", f"Type de message non géré : {genre!r}")

    async def _mettre_en_file(self, genre: str, turn_id: str, contenu) -> None:
        # Parler par-dessus l'agent l'interrompt (barge-in) : on n'attend pas la fin de sa phrase.
        await self._interrompre()
        if self._file.qsize() >= TAILLE_MAX_FILE:
            await self._erreur("file_pleine", "Un message est déjà en cours de traitement, patientez un instant.", turn_id)
            return
        self._file.put_nowait((genre, turn_id, contenu))

    async def _interrompre(self, signaler: bool = True) -> None:
        tache = self._tache_parole
        if tache is not None and not tache.done():
            tache.cancel()
            if signaler:
                await self.envoyer_json({"type": "interrompu", "turn_id": self._tour_courant})

    async def _renouveler_jeton(self, jeton) -> None:
        if not jeton:
            await self._erreur("auth_refresh_invalide", "Jeton manquant.")
            return
        ancien_citoyen = self.citoyen_id
        try:
            charge = await verify_token(str(jeton))
        except Exception:  # noqa: BLE001
            await self._erreur("auth_refresh_invalide", "Jeton invalide ou expiré.")
            return
        if charge.get("sub") != ancien_citoyen:
            await self._fermer(CodesFermeture.SESSION_ETRANGERE, "Le jeton appartient à un autre utilisateur")
            return
        self.jeton_exp = charge.get("exp")
        await self.envoyer_json({"type": "auth_ok", "protocole": self.protocole, "exp": self.jeton_exp})

    def pousser(self, resultat: ResultatTour) -> bool:
        """Parole initiée par le serveur (relance après upload, consigne photo), sérialisée avec les tours."""
        if self.fermee or self._file.qsize() >= TAILLE_MAX_FILE:
            return False
        self._file.put_nowait(("pousse", None, resultat))
        return True

    # ------------------------------------------------------------ traitement

    async def _travailler(self) -> None:
        while True:
            element = await self._file.get()
            if element is None:
                return
            genre, turn_id, contenu = element
            try:
                if genre == "nouvelle":
                    await self._nouvelle_conversation()
                elif genre == "pousse":
                    message_id = await self._enregistrer_messages(None, contenu.reponse_fr)
                    await self._emettre(contenu, turn_id=None, message_id=message_id, question="(document reçu)")
                else:
                    await self._traiter_tour(genre, turn_id, contenu)
            except Exception as exc:  # noqa: BLE001
                log.error("Tour en échec (session=%s, erreur=%s)", (self.etat or {}).get("id"), type(exc).__name__)
                await self._erreur("erreur_interne", "Une erreur est survenue. Vous pouvez réessayer.", turn_id)
                await self.envoyer_json({"type": "status", "state": "listening", "turn_id": turn_id})

    async def _avec_signal_lenteur(self, attente, turn_id: str, etape: str):
        tache = asyncio.ensure_future(attente)
        termine, _ = await asyncio.wait({tache}, timeout=DELAI_SIGNAL_LENTEUR)
        if not termine:
            await self.envoyer_json({"type": "lent", "turn_id": turn_id, "etape": etape})
        return await tache

    async def _traiter_tour(self, genre: str, turn_id: str, contenu) -> None:
        self._tour_courant = turn_id
        if self.protocole == PROTOCOLE_V2 and self.jeton_exp and time.time() > self.jeton_exp + GRACE_JETON_EXPIRE_SECONDES:
            await self._erreur("jeton_expire", "Session expirée : renouvelez le jeton (auth_refresh).", turn_id)
            await self.envoyer_json({"type": "status", "state": "listening", "turn_id": turn_id})
            return

        etat = self.etat
        await self.envoyer_json({"type": "status", "state": "thinking", "turn_id": turn_id})

        async with self.magasin.verrou(etat["id"]):
            if genre == "audio":
                try:
                    wav = await audio.preparer_pour_asr(contenu)
                except audio.ErreurAudio as exc:
                    await self._erreur(exc.code, exc.message_fr, turn_id)
                    await self.envoyer_json({"type": "status", "state": "listening", "turn_id": turn_id})
                    return
                await self.envoyer_json({"type": "etape", "turn_id": turn_id, "etape": "transcription"})
                asr = await self._avec_signal_lenteur(transcribe_audio(wav), turn_id, "transcription")
                texte = (asr.get("transcription") or "").strip() if asr.get("success") else ""
                if not asr.get("success"):
                    await self._erreur("transcription_indisponible", "Je n'ai pas pu écouter votre message. Réessayez dans un instant.", turn_id)
                    await self.envoyer_json({"type": "status", "state": "listening", "turn_id": turn_id})
                    return
                if not texte:
                    await self._erreur("transcription_vide", "Je n'ai rien entendu. Appuyez sur le micro et parlez.", turn_id)
                    await self.envoyer_json({"type": "status", "state": "listening", "turn_id": turn_id})
                    return
            else:
                texte = contenu

            await self.envoyer_json({"type": "transcription", "turn_id": turn_id, "texte": texte})
            await self.envoyer_json({"type": "etape", "turn_id": turn_id, "etape": "reflexion"})
            try:
                resultat = await self._avec_signal_lenteur(
                    asyncio.wait_for(moteur.traiter_message(etat, texte), DELAI_MAX_PHASE_COMPRENDRE), turn_id, "reflexion"
                )
            except Exception as exc:  # noqa: BLE001
                log.error("Moteur en échec (session=%s, erreur=%s)", etat["id"], type(exc).__name__)
                await self.magasin.enregistrer(etat)
                await self._erreur("reflexion_indisponible", "Je n'arrive pas à répondre pour le moment. Réessayez dans un instant.", turn_id)
                await self.envoyer_json({"type": "status", "state": "listening", "turn_id": turn_id})
                return

            message_id = await self._enregistrer_messages(texte, resultat.reponse_fr)
            await self.magasin.enregistrer(etat)

        await self._emettre(resultat, turn_id=turn_id, message_id=message_id, question=texte)

    async def _enregistrer_messages(self, texte_citoyen: Optional[str], reponse_fr: str) -> Optional[str]:
        etat = self.etat
        try:
            conversation_id, message_id = await db.executer(_enregistrer_messages_sync, etat, texte_citoyen, reponse_fr)
        except Exception as exc:  # noqa: BLE001
            log.warning("Historique de conversation non enregistré (%s)", type(exc).__name__)
            return None
        if conversation_id:
            etat["conversation_id"] = conversation_id
        return message_id

    async def _emettre(self, resultat: ResultatTour, *, turn_id: Optional[str], message_id: Optional[str], question: str) -> None:
        etat = self.etat
        if resultat.dossier_mis_a_jour:
            await self.envoyer_json({"type": "dossier_mis_a_jour", **resultat.dossier_mis_a_jour})
        if resultat.document_attendu:
            await self.envoyer_json({"type": "attente_upload", "document_type": resultat.document_attendu, "dossier_id": etat.get("dossier_id"), "turn_id": turn_id})
        await self.envoyer_json({"type": "stream_fr", "content": resultat.reponse_fr, "turn_id": turn_id, "message_id": message_id})

        if resultat.reponse_fr and not self.fermee:
            premier_tour = sum(1 for h in etat.get("historique", []) if h.get("role") == "assistant") <= 1
            self._tache_parole = asyncio.create_task(
                self._parler(resultat.reponse_fr, question, premier_tour, turn_id, message_id, resultat.reponse)
            )
            tache = self._tache_parole
            await asyncio.wait({tache})
            self._tache_parole = None
            if not tache.cancelled() and tache.exception() is not None:
                log.warning("Parole en échec (%s)", type(tache.exception()).__name__)
                await self._erreur("parole_indisponible", "Je n'arrive pas à vous répondre à voix haute. La réponse est affichée à l'écran.", turn_id)

        if resultat.session_a_clore:
            await self._rotation("demarche_bloquee" if etat.get("phase") == "bloque" else "demarche_envoyee")

        await self.envoyer_json({"type": "end", "turn_id": turn_id})
        await self.envoyer_json({"type": "status", "state": "listening", "turn_id": turn_id})

    async def _parler(
        self,
        texte_fr: str,
        question: str,
        premier_tour: bool,
        turn_id: Optional[str],
        message_id: Optional[str],
        reponse=None,
    ) -> None:
        pulaar = await parole.dire(
            self, texte_fr=texte_fr, contexte_question=question,
            premier_tour=premier_tour, turn_id=turn_id, reponse=reponse,
        )
        if message_id and pulaar:
            await db.executer(_maj_pulaar_sync, message_id, pulaar)

    async def _rotation(self, raison: str) -> None:
        ancien = self.etat
        await self.magasin.clore(ancien, raison)
        cle = ancien["cle_client"] if self.protocole == PROTOCOLE_V1 else None
        nouvel, _ = await self.magasin.ouvrir(citoyen_id=self.citoyen_id, commune_profil=self.commune, cle_client=cle)
        self._adopter(nouvel)
        await self.envoyer_json({"type": "session", "protocole": self.protocole, "reprise": False, "nouvelle": True, **instantane_client(nouvel)})

    async def _nouvelle_conversation(self) -> None:
        cle = self.etat["cle_client"] if self.protocole == PROTOCOLE_V1 else None
        nouvel, _ = await self.magasin.ouvrir(citoyen_id=self.citoyen_id, commune_profil=self.commune, cle_client=cle, nouvelle=True)
        self._adopter(nouvel)
        await self._annoncer_session(reprise=False, nouvelle=True)
