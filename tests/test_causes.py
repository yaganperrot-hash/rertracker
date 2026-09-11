"""Tests unitaires pour backend/causes.py"""
import pytest

from backend.causes import CATEGORIES, categoriser_cause, normaliser, resume_perturbation, texte_lisible

# Message complet de la ligne J affiché brut sur l'accueil le 2026-09-11 (balises de traduction incluses)
MESSAGE_J = (
    '<p _msttexthash="367651089" _msthash="20045" _mstvisible="3">P&#233;riode : en journ&#233;e la semaine'
    '<br _istranslated="1" _mstvisible="4"><br _istranslated="1" _mstvisible="4">Dates : du 7 au 11 septembre'
    '<br _istranslated="1" _mstvisible="4"> <br _istranslated="1" _mstvisible="4">Le trafic est interrompu entre '
    'Tournan et Coulommiers de 10h20 &#224; 15h30. <br _istranslated="1" _mstvisible="4">'
    '<br _istranslated="1" _mstvisible="4">Itin&#233;raires recommand&#233;s :<br _istranslated="1">- Pour '
    'rejoindre les gares interm&#233;diaires : bus de remplacement ; <br _istranslated="1">- Pour vos '
    'correspondances : des trains PITA et TITU circulent entre Paris-Est et Tournan. '
    '<br _istranslated="1" _mstvisible="4"><br _istranslated="1" _mstvisible="4">Les horaires du calculateur '
    'd&#8217;itin&#233;raire tiennent compte des travaux. <br _istranslated="1" _mstvisible="4">'
    '<br _istranslated="1" _mstvisible="4">Motif : travaux sur le r&#233;seau ferroviaire (des travaux de '
    'maintenance des voies et de signalisation sont effectu&#233;s afin de rajeunir l&#8217;infrastructure et '
    'd&#8217;apporter une meilleure r&#233;gularit&#233; des circulations. Des op&#233;rations de traitement de '
    'la v&#233;g&#233;tation sont &#233;galement pr&#233;vues aux abords des voies).</p>'
)


# Motifs réels relevés en base (perturbations PRIM, 2026-08-31 → 2026-09-11)
EXEMPLES_REELS = [
    ("<p>P&#233;riode : en semaine, le soir &#224; partir de 23h.<br><br>Dates : du lundi 07 au "
     "vendredi 11 septembre.<br><br>La gare de Clamart en direction de Paris", "Travaux"),
    ("<p>P&#233;riode : du lundi au vendredi<br><br>Dates : du 24/08 au 18/09<br><br>Les horaires "
     "de d&#233;part ou de passage en gare des derniers trains de la ligne", "Travaux"),
    ("Trafic interrompu entre Sarcelles – Persan/Luzarches", "Non précisé"),
    ("Ligne P : Paris Est - Provins 7/09 - 11/12", "Travaux"),
    ("RER D : Combs-la-Ville <-> Melun interrompu du 31/08-18/09", "Travaux"),
    ("Trafic perturbé", "Non précisé"),
    ("RER E : Nanterre - Villiers 7 - 11/09", "Travaux"),
    ("RER C : Bibliothèque <-> Chaville - Vélizy trafic perturbé", "Non précisé"),
    ("<p>La gare de Clamart en direction de Paris Montparnasse n'est pas desservie jusqu'à 11h36."
     "<br><br>Pour plus d'informations sur cette perturbation, consultez le", "Non précisé"),
    # Motif explicite de l'opérateur, lu en priorité
    ("<p>La gare de Clamart en direction de Paris Montparnasse n'est pas desservie jusqu'&#224; 11h30."
     "<br><br>Pour plus d'informations sur cette perturbation, consultez le fil X de la ligne N."
     "<br><br>Motif : incident affectant la voie dans le secteur de S&#232;vres", "Signalisation / infrastructure"),
    ("<p>Le trafic est perturb&#233; de Versailles Ch&#226;teau vers Invalides.<br><br>Pour plus "
     "d'informations sur cette perturbation, consultez le fil X du RER C.<br><br>Motif : malaise "
     "voyageur dans un train en gare de Bouray (incident termin&#233;).", "Incident voyageur"),
    # Avis planifié qui cite la signalisation : ce sont des travaux
    ("<p>P&#233;riode : en journ&#233;e la semaine<br><br>Dates : du 7 au 11 septembre<br><br>Le trafic "
     "est interrompu entre Tournan et Coulommiers de 10h20 à 15h30 (travaux de signalisation).", "Travaux"),
]


class TestCategoriserCause:
    @pytest.mark.parametrize("texte,attendu", EXEMPLES_REELS)
    def test_exemples_reels(self, texte, attendu):
        assert categoriser_cause(texte) == attendu

    @pytest.mark.parametrize("texte,attendu", [
        ("Malaise voyageur à Châtelet", "Incident voyageur"),
        ("Panne de signalisation à Gare du Nord", "Signalisation / infrastructure"),
        ("Train en panne à Juvisy", "Panne matériel"),
        ("Mouvement social local", "Mouvement social"),
        ("Chute d'arbre sur les voies", "Météo"),
        ("Travaux de modernisation", "Travaux"),
    ])
    def test_une_phrase_par_categorie(self, texte, attendu):
        assert categoriser_cause(texte) == attendu

    def test_motif_sans_mot_cle_retombe_sur_le_texte(self):
        assert categoriser_cause("Travaux de nuit. Motif : raison indéterminée") == "Travaux"

    def test_formule_type_voyageurs_n_est_pas_un_incident_voyageur(self):
        assert categoriser_cause("Les voyageurs sont invités à emprunter la ligne P") != "Incident voyageur"

    @pytest.mark.parametrize("texte", [None, "", "<p></p>"])
    def test_vide_non_precise(self, texte):
        assert categoriser_cause(texte) == "Non précisé"

    def test_resultat_toujours_dans_categories(self):
        for texte, _ in EXEMPLES_REELS:
            assert categoriser_cause(texte) in CATEGORIES


class TestMessageAffiche:
    def test_motif_travaux_citant_la_signalisation(self):
        assert categoriser_cause(MESSAGE_J) == "Travaux"

    def test_texte_lisible_sans_html(self):
        t = texte_lisible(MESSAGE_J)
        assert "<" not in t and "&#" not in t and "_mst" not in t
        assert t.split("\n")[0] == "Période : en journée la semaine"
        assert "Les horaires du calculateur d’itinéraire tiennent compte des travaux." in t.split("\n")

    def test_resume_premiere_ligne_informative(self):
        assert resume_perturbation(MESSAGE_J) == "Le trafic est interrompu entre Tournan et Coulommiers de 10h20 à 15h30."

    def test_resume_message_court(self):
        assert resume_perturbation("Trafic perturbé") == "Trafic perturbé"

    def test_fleche_conservee(self):
        assert texte_lisible("RER D : Combs-la-Ville <-> Melun interrompu") == "RER D : Combs-la-Ville <-> Melun interrompu"

    def test_vide(self):
        assert texte_lisible(None) == "" and resume_perturbation(None) == ""


class TestNormaliser:
    def test_entites_balises_accents(self):
        assert normaliser("P&#233;riode <br>") == "periode"

    def test_none(self):
        assert normaliser(None) == ""
