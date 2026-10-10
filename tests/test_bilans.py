"""Tests unitaires pour backend/bilans.py (fonctions pures, sans base)"""
from datetime import date, datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from backend.bilans import (
    LIGNES,
    construire_annee,
    construire_statistiques,
    cout_eur,
    delta_pct,
    journee_paris,
    repartition_causes,
)

SMIC = 12.31
GENERE_A = datetime(2026, 9, 11, 14, 10, tzinfo=ZoneInfo("Europe/Paris"))
AUJ = date(2026, 9, 11)


def row(d: date, line: str, mv: int, inc: int = 1, rt=0, canc=0, disr=0):
    return SimpleNamespace(date=d, line_id=line, minutes_voyageurs=mv, nb_incidents=inc,
                           nb_rt_delays=rt, nb_cancelled=canc, nb_disruptions=disr)


def stats(periode, rows, debut, cats=None):
    return construire_statistiques(periode, AUJ, rows, cats or [], debut, SMIC, GENERE_A)


def ligne(bilan, line_id):
    return next(l for l in bilan["lignes"] if l["id"] == line_id)


class TestUtilitaires:
    def test_cout_arrondi_inferieur(self):
        assert cout_eur(97, SMIC) == 19          # 97 × 12,31 / 60 = 19,90

    def test_cout_sans_erreur_flottante(self):
        assert cout_eur(6000, SMIC) == 1231      # valeur exacte, pas 1230

    def test_delta_pct(self):
        assert delta_pct(118, 100) == 18.0
        assert delta_pct(50, 100) == -50.0

    def test_delta_pct_sans_reference(self):
        assert delta_pct(5, None) is None
        assert delta_pct(5, 0) is None

    def test_repartition_somme_100(self):
        r = repartition_causes(["Travaux", "Météo", "Panne matériel"])
        assert r["total"] == 3
        assert sum(x["pct"] for x in r["repartition"]) == 100
        # À égalité, ordre de CATEGORIES
        assert [x["categorie"] for x in r["repartition"]] == ["Panne matériel", "Météo", "Travaux"]

    def test_repartition_triee_par_nombre(self):
        r = repartition_causes(["Météo"] + ["Travaux"] * 3)
        assert [(x["categorie"], x["pct"]) for x in r["repartition"]] == [("Travaux", 75), ("Météo", 25)]

    def test_repartition_vide(self):
        assert repartition_causes([]) == {"total": 0, "repartition": []}

    def test_journee_commence_a_la_reprise_des_releves(self):
        # 03:59 UTC = 05:59 Paris → veille ; 04:30 UTC = 06:30 Paris (premier relevé du matin) → jour même
        assert journee_paris(datetime(2026, 9, 11, 3, 59, tzinfo=timezone.utc)) == date(2026, 9, 10)
        assert journee_paris(datetime(2026, 9, 11, 4, 30, tzinfo=timezone.utc)) == date(2026, 9, 11)


class TestStatistiques:
    def test_pas_de_comparaison_avec_une_semaine_d_avant_les_donnees_fiables(self):
        # Début des données fiables le 07/09 : la semaine précédente (29/08 → 04/09) n'est pas comparée,
        # même si la base contient des jours plus anciens
        rows = [row(date(2026, 9, 1), "RER_A", 10), row(date(2026, 9, 10), "RER_A", 5000)]
        b = stats(7, rows, date(2026, 9, 7))
        assert b["meta"]["precedente_complete"] is False
        assert b["delta_pct"] is None and b["total_prec"] is None

    def test_total_egal_somme_des_lignes_avec_arrondis(self):
        rows = [
            row(date(2026, 9, 10), "RER_A", 97),
            row(date(2026, 9, 11), "RER_A", 97),
            row(date(2026, 9, 11), "RER_B", 1234, 3),
            row(date(2026, 9, 5), "TRANSILIEN_H", 55, 2),
        ]
        s = stats(30, rows, date(2026, 9, 1))
        for k in ("cout_eur", "minutes", "incidents"):
            assert s["total"][k] == sum(l[k] for l in s["lignes"])
        # Coût arrondi par jour puis sommé : 19 + 19, et non floor(194 × 12,31 / 60) = 39
        assert ligne(s, "RER_A")["cout_eur"] == 38
        assert cout_eur(194, SMIC) == 39

    def test_lignes_triees_ligne_inconnue_ignoree(self):
        rows = [
            row(AUJ, "RER_C", 500),
            row(AUJ, "TRANSILIEN_U", 900),
            row(AUJ, "TRAM_1", 99999),
        ]
        s = stats(7, rows, date(2026, 9, 1))
        ids = [l["id"] for l in s["lignes"]]
        assert len(ids) == len(LIGNES) and set(ids) == set(LIGNES)
        assert ids[:2] == ["TRANSILIEN_U", "RER_C"]
        assert ids[2:] == [l for l in LIGNES if l not in ("TRANSILIEN_U", "RER_C")]
        assert s["total"]["minutes"] == 1400

    def test_pire_ligne(self):
        s = stats(7, [row(AUJ, "RER_B", 800, 4), row(AUJ, "RER_A", 300)], date(2026, 9, 1))
        assert s["pire_ligne"]["id"] == "RER_B"
        assert s["pire_ligne"]["minutes"] == 800
        assert s["pire_ligne"]["incidents"] == 4

    def test_table_vide(self):
        s = stats(30, [], None)
        assert s["total"] == {"cout_eur": 0, "minutes": 0, "incidents": 0,
                              "nb_rt_delays": 0, "nb_cancelled": 0, "nb_disruptions": 0}
        assert s["pire_ligne"] is None
        assert s["total_prec"] is None and s["delta_pct"] is None
        assert len(s["lignes"]) == len(LIGNES)
        assert s["meta"]["jours_couverts"] == 0

    def test_precedente_incomplete(self):
        s = stats(7, [row(AUJ, "RER_A", 100)], date(2026, 9, 10))
        assert s["meta"]["jours_couverts"] == 2
        assert s["meta"]["precedente_complete"] is False
        assert s["total_prec"] is None and s["delta_pct"] is None
        assert all(l["delta_pct_minutes"] is None for l in s["lignes"])
        assert s["pire_ligne"]["delta_pct_minutes"] is None

    def test_precedente_complete_et_bornes(self):
        # 7 j : courante 05/09 → 11/09, précédente 29/08 → 04/09
        rows = [
            row(AUJ, "RER_A", 120),
            row(date(2026, 9, 1), "RER_A", 100),
            row(date(2026, 8, 28), "RER_A", 999),   # veille de la période précédente : nulle part
        ]
        s = stats(7, rows, date(2026, 8, 1))
        assert s["meta"]["precedente"] == {"du": "2026-08-29", "au": "2026-09-04"}
        assert s["total"]["minutes"] == 120
        assert s["total_prec"]["minutes"] == 100
        assert s["delta_pct"]["minutes"] == 20.0
        assert ligne(s, "RER_A")["delta_pct_minutes"] == 20.0

    def test_causes_reparties(self):
        s = stats(7, [], date(2026, 9, 1), ["Travaux", "Travaux", "Non précisé"])
        assert s["causes"]["total"] == 3
        assert s["causes"]["repartition"][0] == {"categorie": "Travaux", "n": 2, "pct": 67}


def annee(rows, debut, aujourdhui=AUJ, causes=None, an=2026):
    return construire_annee(an, aujourdhui, rows, causes or {}, debut, SMIC, GENERE_A)


class TestAnnee:
    def test_total_egal_somme_mois_et_lignes(self):
        rows = [row(date(2026, m, 10), l, 97 * m, m)
                for m in range(1, 10) for l in ("RER_A", "RER_D", "TRANSILIEN_K")]
        a = annee(rows, date(2026, 1, 1))
        for k in ("cout_eur", "minutes", "incidents"):
            assert a["total"][k] == sum(m[k] for m in a["mois"] if m[k] is not None)
            assert a["total"][k] == sum(l[k] for l in a["lignes"])

    def test_mois_hors_donnees_nuls_et_partiels(self):
        a = annee([row(date(2026, 3, 20), "RER_A", 100)], date(2026, 3, 15))
        assert len(a["mois"]) == 12
        assert a["mois"][1]["cout_eur"] is None                  # février : avant les données
        assert a["mois"][2]["partiel"] and a["mois"][2]["jours_couverts"] == 17
        assert a["mois"][8]["partiel"] and a["mois"][8]["jours_couverts"] == 11
        assert all(m["cout_eur"] is None for m in a["mois"][9:])  # octobre → décembre : futur
        assert a["meta"]["mois_renseignes"] == list(range(3, 10))
        assert a["meta"]["en_cours"] is True

    def test_pire_mois_et_creux(self):
        # Janvier → mai complets, juin en cours
        minutes = {1: 6000, 2: 6000, 3: 6000, 4: 3000, 5: 4200, 6: 100}
        rows = [row(date(2026, m, 5), "RER_A", mv) for m, mv in minutes.items()]
        a = annee(rows, date(2026, 1, 1), aujourdhui=date(2026, 6, 10))
        assert a["pire_mois"] == 1                               # égalité → le plus ancien
        # Moyenne des mois complets 1033,8 € : avril (615 €, < 60 %) est un creux, mai (861 €) non,
        # juin est partiel donc jamais creux malgré son faible coût
        assert a["creux"] == [4]

    def test_pas_de_creux_avec_moins_de_trois_mois_complets(self):
        rows = [row(date(2026, 7, 5), "RER_A", 6000), row(date(2026, 8, 5), "RER_A", 100)]
        a = annee(rows, date(2026, 7, 1))
        assert a["creux"] == []

    def test_meilleure_progression_a_date_equivalente(self):
        rows = [
            row(date(2025, 3, 1), "RER_A", 1000), row(date(2026, 3, 1), "RER_A", 600),    # −40 %
            row(date(2025, 3, 1), "RER_B", 1000), row(date(2026, 3, 1), "RER_B", 900),    # −10 %
            row(date(2025, 3, 1), "RER_C", 1000), row(date(2026, 3, 1), "RER_C", 1200),   # +20 %
            row(date(2025, 10, 1), "RER_B", 100000),   # après le 11/09/2025 : hors comparaison
        ]
        a = annee(rows, date(2024, 6, 1))
        assert a["meta"]["annee_prec_disponible"] is True
        assert ligne(a, "RER_B")["delta_pct_minutes"] == -10.0
        assert a["meilleure_progression"] == {"id": "RER_A", "delta_pct_minutes": -40.0, "nb_lignes_en_recul": 2}

    def test_sans_annee_precedente(self):
        a = annee([row(date(2026, 3, 1), "RER_A", 600)], date(2026, 1, 1))
        assert a["meta"]["annee_prec_disponible"] is False
        assert a["meilleure_progression"] is None
        assert all(l["delta_pct_minutes"] is None for l in a["lignes"])

    def test_cause_principale_ignore_non_precise(self):
        causes = {3: ["Non précisé", "Non précisé", "Travaux"], 4: ["Non précisé"]}
        a = annee([], date(2026, 1, 1), causes=causes)
        assert a["mois"][2]["cause_principale"] == "Travaux"
        assert a["mois"][3]["cause_principale"] == "Non précisé"
        assert a["mois"][4]["cause_principale"] is None

    def test_table_vide(self):
        a = annee([], None)
        assert a["total"] == {"cout_eur": 0, "minutes": 0, "incidents": 0,
                              "nb_rt_delays": 0, "nb_cancelled": 0, "nb_disruptions": 0}
        assert a["pire_mois"] is None and a["meilleure_progression"] is None
        assert all(m["cout_eur"] is None for m in a["mois"])


class TestHallOfShame:
    """Périodes calendaires, comme le panneau de ligne : semaine depuis lundi, mois depuis le 1er."""

    def test_semaine_et_mois_calendaires(self):
        from backend.bilans import construire_hall_of_shame
        vendredi = date(2026, 9, 18)
        rows = [row(date(2026, 8, 31), "RER_A", 1000), row(date(2026, 9, 1), "RER_A", 100),
                row(date(2026, 9, 13), "RER_A", 10), row(date(2026, 9, 14), "RER_A", 1)]
        h = construire_hall_of_shame(vendredi, rows, {}, {}, SMIC, GENERE_A, date(2026, 9, 16))
        cout = ligne(h, "RER_A")["cout"]
        assert cout["semaine"]["minutes"] == 1            # lundi 14 → vendredi 18
        assert cout["mois"]["minutes"] == 111             # 1er → 18 septembre
        assert h["meta"]["periodes"] == {"semaine": "2026-09-14", "mois": "2026-09-01", "annee": "2026-01-01"}
        assert h["meta"]["debut_donnees"] == "2026-09-16"

    def test_totaux_et_compteurs(self):
        from backend.bilans import construire_hall_of_shame
        vendredi = date(2026, 9, 18)
        rows = [
            row(date(2026, 9, 15), "RER_A", 500, 2, rt=5, canc=1, disr=3),
            row(date(2026, 9, 16), "RER_B", 300, 1, rt=2, canc=0, disr=1),
        ]
        h = construire_hall_of_shame(vendredi, rows, {}, {}, SMIC, GENERE_A, date(2026, 9, 1))

        # Compteurs dans cout par ligne
        ca = ligne(h, "RER_A")["cout"]
        assert ca["semaine"]["nb_rt_delays"] == 5
        assert ca["semaine"]["nb_cancelled"] == 1
        assert ca["semaine"]["nb_disruptions"] == 3

        # Totaux réseau
        assert "totaux" in h
        assert h["totaux"]["semaine"]["nb_rt_delays"] == 7
        assert h["totaux"]["semaine"]["nb_cancelled"] == 1
        assert h["totaux"]["semaine"]["nb_disruptions"] == 4
        assert h["totaux"]["semaine"]["minutes"] == 800

    def test_delta_present(self):
        from backend.bilans import construire_hall_of_shame
        # Vendredi 18/09, données depuis le 1er sept
        vendredi = date(2026, 9, 18)
        rows = [
            row(date(2026, 9, 8), "RER_A", 1000, 5, rt=10, canc=2, disr=4),  # semaine précédente
            row(date(2026, 9, 15), "RER_A", 500, 2, rt=5, canc=1, disr=3),    # semaine courante
        ]
        h = construire_hall_of_shame(vendredi, rows, {}, {}, SMIC, GENERE_A, date(2026, 9, 1))
        d = ligne(h, "RER_A")["delta"]
        assert d["semaine"] is not None
        assert d["semaine"]["nb_rt_delays"] == -50.0
