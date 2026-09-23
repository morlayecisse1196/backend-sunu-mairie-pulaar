"""
Atelier pulaar, côté service (plan maître, étape 4.2).

Cette logique vivait dans un script, donc sans test : c'est là qu'un gabarit
est resté invisible à la relecture pendant deux étapes. Ce qui est verrouillé
ici :

  * TOUTES les familles de phrases sont proposées à la relecture — questions,
    relances, pièces, rappels, gabarits, phrases système ;
  * un identifiant inconnu n'écrit RIEN, nulle part : une traduction rangée au
    mauvais endroit ne se découvre qu'en dialogue ;
  * une relance corrigée ne détruit pas ses voisines dans le tableau ;
  * valider une phrase efface l'audio, qui ne dit plus ce texte-là ;
  * une case cochée sur du vide ne vaut pas relecture.
"""
from __future__ import annotations

import pytest

from services import atelier, demarche

CHAMPS = [
    {"type_demarche": "extrait_naissance", "nom_champ": "nom_enfant", "ordre": 10,
     "type_valeur": "texte", "question": "Quel est le nom de l'enfant ?",
     "question_pulaar": "Innde ɓiɗɗo ko honɗum?", "pulaar_valide": True,
     "relances": ["Je n'ai pas compris. Le nom ?", "Reprenons. Le nom ?"],
     "relances_pulaar": ["Mi faamaani.", "En fuɗɗitto."]},
    {"type_demarche": "extrait_naissance", "nom_champ": "nom_mere", "ordre": 20,
     "type_valeur": "texte", "question": "Quel est le nom de la maman ?",
     "question_pulaar": "", "pulaar_valide": False, "relances": [], "relances_pulaar": []},
]
DOCUMENTS = [
    {"type_demarche": "extrait_naissance", "type_document": "cni_declarant", "ordre": 10,
     "message_demande": "J'ai besoin d'une photo de votre carte d'identité.",
     "message_demande_pulaar": "", "pulaar_valide": False,
     "messages_rappel": ["Je n'ai pas reçu la photo."], "messages_rappel_pulaar": []},
]
GABARITS = [
    {"type_demarche": "extrait_naissance", "cle": "recapitulatif",
     "francais": "{nom_enfant}, est-ce exact ?", "pulaar": "", "pulaar_valide": False,
     "contexte": "Relecture obligatoire"},
]
SYSTEME = [
    {"cle": "confirmation_reponse", "francais": "C'est noté.", "pulaar": "Winndaama.",
     "pulaar_valide": False, "contexte": "Après une réponse acceptée."},
]

TABLES = {
    "demarche_champs": CHAMPS,
    "demarche_documents": DOCUMENTS,
    "demarche_gabarits": GABARITS,
    "phrases_systeme": SYSTEME,
}


class _Table:
    """Mémorise les écritures au lieu de les envoyer à Supabase."""

    def __init__(self, journal: list, nom: str):
        self.journal, self.nom, self._donnees = journal, nom, None

    def update(self, donnees):
        self._donnees = donnees
        return self

    def insert(self, lignes):
        self.journal.append((self.nom, "insert", lignes))
        return self

    def eq(self, colonne, valeur):
        self._filtre = (colonne, valeur)
        return self

    def execute(self):
        if self._donnees is not None:
            self.journal.append((self.nom, self._filtre, self._donnees))
        return type("R", (), {"data": []})()


@pytest.fixture
def base(monkeypatch):
    journal: list = []

    def lire(nom, **filtres):
        lignes = TABLES.get(nom, [])
        for colonne, valeur in filtres.items():
            lignes = [l for l in lignes if l.get(colonne) == valeur]
        return lignes

    monkeypatch.setattr(demarche, "_table", lire)
    monkeypatch.setattr(atelier, "get_supabase_client",
                        lambda: type("C", (), {"table": lambda _s, nom: _Table(journal, nom)})())
    demarche.vider_cache()
    return journal


class TestCollecte:
    def test_toutes_les_familles_de_phrases_sont_proposees(self, base):
        identifiants = [p.identifiant for p in atelier.collecter()]
        assert "champ:nom_enfant:question" in identifiants
        assert "champ:nom_enfant:relance0" in identifiants
        assert "document:cni_declarant:demande" in identifiants
        assert "document:cni_declarant:rappel0" in identifiants
        assert "gabarit:recapitulatif" in identifiants, "le récapitulatif doit être relu"
        assert "systeme:confirmation_reponse" in identifiants

    def test_une_phrase_sans_francais_n_est_pas_proposee(self, base):
        # Rien à traduire : la proposer ferait perdre du temps au relecteur.
        assert all(p.francais.strip() for p in atelier.collecter())

    def test_le_contexte_accompagne_toujours_la_phrase(self, base):
        # « C'est noté » se traduit autrement selon qu'on confirme une réponse
        # ou qu'on clôt un dossier : sans contexte, traduire est un pari.
        assert all(p.contexte.strip() for p in atelier.collecter())

    def test_le_relecteur_est_averti_pour_un_gabarit(self, base):
        gabarit = next(p for p in atelier.collecter() if p.identifiant == "gabarit:recapitulatif")
        assert "{nom_champ}" in gabarit.contexte

    def test_l_avancement_distingue_relu_depose_et_vide(self, base):
        etat = atelier.avancement()
        assert etat["total"] == len(atelier.collecter())
        # nom_enfant n'a pas de drapeaux par rang : sa question ET ses deux
        # relances héritent donc du `pulaar_valide` de la ligne. C'est le
        # repli de la migration 024, et c'est le comportement d'avant elle.
        assert etat["relues"] == 3
        assert etat["deposees"] >= 1, "une traduction déposée mais non relue"
        assert etat["relues"] + etat["deposees"] + etat["vides"] == etat["total"]


class TestEnregistrement:
    def test_un_identifiant_inconnu_n_ecrit_rien(self, base):
        # Une traduction rangée au mauvais endroit ne se découvre qu'en
        # dialogue, devant un citoyen.
        with pytest.raises(ValueError, match="inconnu"):
            atelier.enregistrer({"champ:nom_enfnat:question": "Faute de frappe"})
        assert base == [], "aucune écriture, même partielle"

    def test_une_traduction_simple_est_rangee_au_bon_endroit(self, base):
        atelier.enregistrer({"champ:nom_mere:question": "Innde neene ko honɗum?"})
        table, filtre, donnees = base[0]
        assert table == "demarche_champs"
        assert filtre == ("nom_champ", "nom_mere")
        assert donnees["question_pulaar"] == "Innde neene ko honɗum?"

    def test_une_relance_corrigee_ne_detruit_pas_ses_voisines(self, base):
        # Le tableau est écrit en entier : oublier les autres rangs les
        # effacerait, et le citoyen entendrait deux fois la même relance.
        atelier.enregistrer({"champ:nom_enfant:relance1": "Corrigée."})
        _table, _filtre, donnees = base[0]
        assert donnees["relances_pulaar"] == ["Mi faamaani.", "Corrigée."]

    def test_valider_efface_l_audio_qui_ne_dit_plus_ce_texte(self, base):
        atelier.enregistrer({"champ:nom_mere:question": "Nouveau texte."}, valider=True)
        _t, _f, donnees = base[0]
        assert donnees["pulaar_valide"] is True
        assert donnees["question_audio"] is None

    def test_un_gabarit_n_a_pas_de_colonne_audio_a_effacer(self, base):
        # Son texte final dépend du dossier : il n'est jamais pré-généré.
        atelier.enregistrer({"gabarit:recapitulatif": "{nom_enfant}, ko goonga?"})
        _t, _f, donnees = base[0]
        assert "audio" not in donnees

    def test_une_traduction_vide_ne_vaut_pas_relecture(self, base):
        # Sinon une case cochée sur du vide ferait perdre à `pulaar_valide`
        # le seul sens qu'il a.
        resultat = atelier.enregistrer({"champ:nom_mere:question": "   "}, valider=True)
        assert resultat["phrases"] == 0
        assert base == []

    def test_plusieurs_phrases_d_une_meme_ligne_font_une_seule_ecriture(self, base):
        atelier.enregistrer({
            "champ:nom_enfant:question": "Q.",
            "champ:nom_enfant:relance0": "R0.",
        })
        ecritures = [e for e in base if e[1] != "insert"]
        assert len(ecritures) == 1


class TestHistorique:
    def test_une_relecture_laisse_une_trace_avec_le_texte_d_avant(self, base):
        atelier.enregistrer(
            {"champ:nom_enfant:question": "Version corrigée."}, valider=True, par="moussa@mairie.sn"
        )
        inserts = [e for e in base if e[1] == "insert"]
        assert len(inserts) == 1
        ligne = inserts[0][2][0]
        assert ligne["identifiant"] == "champ:nom_enfant:question"
        assert ligne["pulaar_avant"] == "Innde ɓiɗɗo ko honɗum?"
        assert ligne["pulaar_apres"] == "Version corrigée."
        assert ligne["par"] == "moussa@mairie.sn"

    def test_un_texte_inchange_et_deja_valide_ne_pollue_pas_l_historique(self, base):
        atelier.enregistrer({"champ:nom_enfant:question": "Innde ɓiɗɗo ko honɗum?"}, valider=True)
        assert [e for e in base if e[1] == "insert"] == []

    def test_l_historique_ne_bloque_jamais_l_enregistrement(self, base, monkeypatch):
        # Perdre une ligne d'historique ne doit pas faire perdre une traduction.
        class _Casse:
            def table(self, nom):
                if nom == "atelier_historique":
                    raise RuntimeError("migration 023 pas appliquée")
                return _Table(base, nom)

        monkeypatch.setattr(atelier, "get_supabase_client", _Casse)
        resultat = atelier.enregistrer({"champ:nom_mere:question": "Texte."})
        assert resultat["phrases"] == 1


class TestRelectureAuRang:
    """
    Une ligne porte plusieurs phrases ; les valider ensemble ferait dire au
    citoyen des phrases que personne n'a lues (migration 024).
    """

    CHAMP_PAR_RANG = {
        "type_demarche": "extrait_naissance", "nom_champ": "date_naissance", "ordre": 30,
        "type_valeur": "date", "question": "Quelle est sa date de naissance ?",
        "question_pulaar": "Ñalnde jibineede?", "pulaar_valide": False,
        "relances": ["Première relance.", "Deuxième relance."],
        "relances_pulaar": ["Relue par un locuteur.", "Déposée par la machine."],
        "relances_pulaar_valide": [True, False],
    }

    @pytest.fixture
    def base_par_rang(self, monkeypatch):
        journal: list = []
        monkeypatch.setattr(demarche, "_table", lambda nom, **f: (
            [self.CHAMP_PAR_RANG] if nom == "demarche_champs" else []))
        monkeypatch.setattr(atelier, "get_supabase_client",
                            lambda: type("C", (), {"table": lambda _s, nom: _Table(journal, nom)})())
        demarche.vider_cache()
        return journal

    def test_chaque_relance_porte_sa_propre_relecture(self, base_par_rang):
        par_id = {p.identifiant: p for p in atelier.collecter()}
        assert par_id["champ:date_naissance:relance0"].valide is True
        assert par_id["champ:date_naissance:relance1"].valide is False
        assert par_id["champ:date_naissance:question"].valide is False

    def test_seule_la_relance_relue_est_dite_au_citoyen(self, base_par_rang):
        # Le point qui compte vraiment : ce que le dialogue prononce.
        assert demarche.relance_champ(self.CHAMP_PAR_RANG, 0).pulaar_pret() == "Relue par un locuteur."
        assert demarche.relance_champ(self.CHAMP_PAR_RANG, 1).pulaar_pret() is None

    def test_valider_une_relance_ne_valide_pas_la_question(self, base_par_rang):
        atelier.enregistrer({"champ:date_naissance:relance1": "Corrigée."}, valider=True)
        _table, _filtre, donnees = base_par_rang[0]
        assert donnees["relances_pulaar_valide"] == [True, True]
        assert "pulaar_valide" not in donnees, "la question n'a pas été relue"

    def test_valider_une_relance_ne_retire_pas_sa_voisine_du_circuit(self, base_par_rang):
        # Sinon corriger la deuxième relance ferait silencieusement repasser
        # la première par le traducteur.
        atelier.enregistrer({"champ:date_naissance:relance1": "Corrigée."}, valider=True)
        _t, _f, donnees = base_par_rang[0]
        assert donnees["relances_pulaar_valide"][0] is True

    def test_valider_la_question_ne_valide_pas_les_relances(self, base_par_rang):
        atelier.enregistrer({"champ:date_naissance:question": "Question relue."}, valider=True)
        _t, _f, donnees = base_par_rang[0]
        assert donnees["pulaar_valide"] is True
        assert "relances_pulaar_valide" not in donnees

    def test_sans_drapeaux_par_rang_le_comportement_est_celui_d_avant(self):
        # Repli de la migration 024 : un tableau vide laisse la ligne décider.
        ancien = {**self.CHAMP_PAR_RANG, "relances_pulaar_valide": [], "pulaar_valide": True}
        assert demarche.relance_champ(ancien, 0).pulaar_pret() == "Relue par un locuteur."
        assert demarche.relance_champ(ancien, 1).pulaar_pret() == "Déposée par la machine."


class TestRelectureRetiree:
    """
    Un texte changé sans être revalidé perd sa relecture.

    Le relecteur avait approuvé l'ancien texte ; celui-ci n'existe plus. Le
    laisser marqué « relu » ferait dire au citoyen une phrase que personne n'a
    jamais lue. C'est exactement ce qui est arrivé : trois lignes d'un fichier
    mal formé ont mis du FRANÇAIS dans la colonne pulaar de deux questions du
    dialogue, validé, prêt à être lu par la synthèse.
    """

    def test_corriger_un_texte_relu_en_retire_la_relecture(self, base):
        atelier.enregistrer({"champ:nom_enfant:question": "Texte tout autre."})
        _t, _f, donnees = base[0]
        assert donnees["pulaar_valide"] is False

    def test_revalider_explicitement_reste_possible(self, base):
        atelier.enregistrer({"champ:nom_enfant:question": "Texte tout autre."}, valider=True)
        _t, _f, donnees = base[0]
        assert donnees["pulaar_valide"] is True

    def test_un_texte_identique_garde_sa_relecture(self, base):
        # Réimporter le même fichier ne doit pas défaire le travail fait.
        atelier.enregistrer({"champ:nom_enfant:question": "Innde ɓiɗɗo ko honɗum?"})
        _t, _f, donnees = base[0]
        assert "pulaar_valide" not in donnees

    def test_corriger_une_relance_relue_en_retire_la_relecture_au_rang(self, base):
        atelier.enregistrer({"champ:nom_enfant:relance0": "Relance réécrite."})
        _t, _f, donnees = base[0]
        # Rang 0 corrigé donc retiré ; rang 1 intact donc conservé.
        assert donnees["relances_pulaar_valide"] == [False, True]


class TestRetractationContenue:
    """
    La rétractation ne doit pas déborder sur les phrases voisines.

    Une relance sans drapeau par rang se rabat sur le drapeau de LIGNE
    (migration 024). Quand la question change et perd sa relecture, la ligne
    tombe — et les relances tombaient avec elle, sans que leur texte ait bougé
    et sans que personne ne l'ait demandé. Six phrases déjà relues ont ainsi
    été silencieusement remises au travail.
    """

    def test_corriger_la_question_ne_retire_pas_la_relecture_des_relances(self, base):
        atelier.enregistrer({"champ:nom_enfant:question": "Question réécrite."})
        _t, _f, donnees = base[0]
        assert donnees["pulaar_valide"] is False, "la question perd bien sa relecture"
        assert donnees["relances_pulaar_valide"] == [True, True], (
            "les relances gardent la leur : leur texte n'a pas changé"
        )

    def test_la_relance_dont_le_texte_change_est_seule_retiree(self, base):
        atelier.enregistrer({
            "champ:nom_enfant:question": "Question réécrite.",
            "champ:nom_enfant:relance0": "Relance réécrite.",
        })
        _t, _f, donnees = base[0]
        assert donnees["relances_pulaar_valide"] == [False, True]


class TestHistoriqueSansBruit:
    def test_reimporter_le_meme_fichier_n_ecrit_aucune_ligne(self, base):
        # Réimporter à l'identique consignait 53 non-événements, noyant les
        # vraies corrections au milieu.
        atelier.enregistrer({"champ:nom_enfant:question": "Innde ɓiɗɗo ko honɗum?"})
        assert [e for e in base if e[1] == "insert"] == []

    def test_une_premiere_validation_est_bien_consignee(self, base):
        atelier.enregistrer({"champ:nom_mere:question": "Innde neene?"}, valider=True)
        inserts = [e for e in base if e[1] == "insert"]
        assert len(inserts) == 1
        assert inserts[0][2][0]["valide"] is True


class TestDemarcheDeLaPhrase:
    """
    Une phrase demandée dans la mauvaise démarche (étape 5).

    Le web envoyait l'identifiant sans dire de quelle démarche il venait : le
    backend cherchait dans la démarche par défaut et répondait « identifiant
    inconnu » pour toutes les phrases du mariage et du décès.
    """

    def test_l_erreur_dit_dans_quelle_demarche_on_a_cherche(self, base):
        with pytest.raises(ValueError, match="extrait_naissance"):
            atelier.enregistrer({"champ:prenoms_epoux:question": "Inɗe gorko oo?"},
                                valider=False, par="a@b.sn", type_demarche="extrait_naissance")

    def test_l_erreur_dit_ou_la_phrase_se_trouve(self, base, monkeypatch):
        autre = type("D", (), {"type_demarche": "constatation_mariage"})()
        monkeypatch.setattr(atelier.demarche, "demarches_traitables", lambda: [autre])
        monkeypatch.setattr(atelier, "collecter", lambda t: (
            [] if t == "extrait_naissance"
            else [atelier.Phrase("champ:prenoms_epoux:question", "Prénoms ?", "", False, "",
                                 atelier.Cible("demarche_champs", "nom_champ", "prenoms_epoux",
                                               "question_pulaar"), False)]))
        with pytest.raises(ValueError, match="constatation_mariage"):
            atelier.enregistrer({"champ:prenoms_epoux:question": "Inɗe gorko oo?"},
                                valider=False, par="a@b.sn", type_demarche="extrait_naissance")

    def test_un_diagnostic_en_panne_ne_masque_pas_l_erreur(self, base, monkeypatch):
        # Le diagnostic est un confort ; l'erreur utile reste « identifiant
        # inconnu », et l'appelant doit la recevoir telle quelle (404, pas 500).
        def en_panne():
            raise RuntimeError("base injoignable")
        monkeypatch.setattr(atelier.demarche, "demarches_traitables", en_panne)
        with pytest.raises(ValueError, match="Identifiant"):
            atelier.enregistrer({"inconnu": "x"}, valider=False, par="a@b.sn")
