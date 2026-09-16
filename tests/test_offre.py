"""Tests de backend/offre.py — offre théorique GTFS (trains équivalents, intervalles)."""
import zipfile
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend import offre
from backend.profils import CATEGORIES

PARIS = ZoneInfo("Europe/Paris")
ROUTE_A = offre.LIGNE_ROUTE["RER_A"]

STOPS = """stop_id,stop_name,parent_station
P1,Gare Un,
P2,Gare Deux,
P3,Gare Trois,
Q1,Gare Un,P1
Q2,Gare Deux,P2
Q3,Gare Trois,P3
"""


def _gtfs(tmp_path, trips: str, stop_times: str, calendar: str, calendar_dates: str = "") -> str:
    """Mini GTFS écrit dans tmp_path : aucun binaire versionné, aucun réseau."""
    chemin = tmp_path / "gtfs.zip"
    with zipfile.ZipFile(chemin, "w") as z:
        z.writestr("stops.txt", STOPS)
        z.writestr("trips.txt", "route_id,service_id,trip_id,trip_headsign,direction_id\n" + trips)
        z.writestr("stop_times.txt", "trip_id,departure_time,stop_id,stop_sequence\n" + stop_times)
        z.writestr("calendar.txt", "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
                                   "start_date,end_date\n" + calendar)
        z.writestr("calendar_dates.txt", "service_id,date,exception_type\n" + calendar_dates)
    return str(chemin)


# Service de toute la semaine, du lundi 21 au dimanche 27 septembre 2026 (hors vacances)
SEMAINE = "S,1,1,1,1,1,1,1,20260921,20260927\n"


def _toutes_lignes(trips_a: str) -> str:
    """Un train de nuit sur chaque autre ligne : agreger exige les 13 lignes."""
    autres = "".join(f"{route},S,T_{ligne},X,0\n" for ligne, route in offre.LIGNE_ROUTE.items() if ligne != "RER_A")
    return trips_a + autres


def _dessertes_autres() -> str:
    return "".join(f"T_{ligne},03:00:00,Q1,1\n" for ligne in offre.LIGNE_ROUTE if ligne != "RER_A")


class TestAgregation:
    def test_train_a_cheval_reparti_au_prorata(self, tmp_path):
        z = _gtfs(tmp_path, _toutes_lignes(f"{ROUTE_A},S,A1,QYRO,0\n"),
                  "A1,07:50:00,Q1,1\nA1,08:10:00,Q2,2\nA1,08:30:00,Q3,3\nA1,07:55:00,Q2,0\n" + _dessertes_autres(),
                  SEMAINE)
        c = offre.agreger(z)
        t = c["trains_heure"]["RER_A"]["JOHV"]
        assert t[7] == 0.5
        assert t[8] == 0.5
        assert c["trains_jour"]["RER_A"]["JOHV"] == 1

    def test_calendar_dates_retire_et_ajoute(self, tmp_path):
        # A1 circule toute la semaine sauf le mardi 22 ; A2 seulement le samedi 26 (ajout)
        trips = f"{ROUTE_A},W,A1,QYRO,0\n{ROUTE_A},V,A2,QYRO,0\n"
        calendar = SEMAINE + "W,1,1,1,1,1,1,1,20260921,20260927\nV,0,0,0,0,0,0,0,20260921,20260927\n"
        z = _gtfs(tmp_path, _toutes_lignes(trips),
                  "A1,08:00:00,Q1,1\nA2,08:00:00,Q1,1\n" + _dessertes_autres(),
                  calendar, "W,20260922,2\nV,20260926,1\n")
        c = offre.agreger(z)
        # Semaine : 4 jours sur 5 avec A1 → 0,8 ; samedi : A1 + A2 → 2
        assert c["trains_jour"]["RER_A"]["JOHV"] == 0.8
        assert c["trains_jour"]["RER_A"]["SAHV"] == 2

    def test_heure_au_dela_de_24h(self, tmp_path):
        z = _gtfs(tmp_path, _toutes_lignes(f"{ROUTE_A},S,A1,QYRO,0\n"),
                  "A1,25:10:00,Q1,1\n" + _dessertes_autres(), SEMAINE)
        assert offre.agreger(z)["trains_heure"]["RER_A"]["JOHV"][1] == 1

    def test_intervalle_quatre_departs_par_heure(self, tmp_path):
        trips = "".join(f"{ROUTE_A},S,A{i},QYRO,0\n" for i in range(4))
        stop_times = "".join(f"A{i},08:{i * 15:02d}:00,Q1,1\n" for i in range(4))
        z = _gtfs(tmp_path, _toutes_lignes(trips), stop_times + _dessertes_autres(), SEMAINE)
        c = offre.agreger(z)
        assert c["intervalle_min"]["RER_A"]["JOHV"][8] == 15
        assert c["intervalle_min"]["RER_A"]["JOHV"][12] is None

    def test_intervalle_borne_a_60(self, tmp_path):
        # Un train tous les deux jours → 0,5 départ/heure → 120 min, borné à 60
        trips = f"{ROUTE_A},D,A1,QYRO,0\n"
        calendar = SEMAINE + "D,1,0,1,0,1,0,0,20260921,20260927\n"
        z = _gtfs(tmp_path, _toutes_lignes(trips), "A1,08:00:00,Q1,1\n" + _dessertes_autres(), calendar)
        c = offre.agreger(z)
        assert c["trains_jour"]["RER_A"]["JOHV"] == 0.6
        assert c["intervalle_min"]["RER_A"]["JOHV"][8] == offre.INTERVALLE_MAX_MIN

    def test_repli_vacances_note(self, tmp_path):
        z = _gtfs(tmp_path, _toutes_lignes(f"{ROUTE_A},S,A1,QYRO,0\n"),
                  "A1,08:00:00,Q1,1\n" + _dessertes_autres(), SEMAINE)
        c = offre.agreger(z)
        assert c["_source"]["replis"] == {"JOVS": "JOHV", "SAVS": "SAHV"}
        assert c["trains_heure"]["RER_A"]["JOVS"] == c["trains_heure"]["RER_A"]["JOHV"]

    def test_date_partielle_ecartee(self, tmp_path):
        # 10 trains chaque jour de la semaine, plus un seul train le dimanche 20 (bord de fenêtre partiel)
        trips = "".join(f"{ROUTE_A},S,A{i},QYRO,0\n" for i in range(10)) + f"{ROUTE_A},B,B1,QYRO,0\n"
        calendar = SEMAINE + "B,0,0,0,0,0,0,1,20260920,20260920\n"
        stop_times = "".join(f"A{i},08:00:00,Q1,1\n" for i in range(10)) + "B1,08:00:00,Q1,1\n"
        z = _gtfs(tmp_path, _toutes_lignes(trips), stop_times + _dessertes_autres(), calendar)
        c = offre.agreger(z)
        assert c["_source"]["fenetre"] == ["2026-09-21", "2026-09-27"]


class TestMedianePonderee:
    def test_poids_egaux(self):
        assert offre.mediane_ponderee([(1, 1), (2, 1), (3, 1)]) == 2

    def test_poids_dominant(self):
        assert offre.mediane_ponderee([(60, 1), (3, 20)]) == 3


# ─────────────── Fichier réel data/offre_theorique.json ───────────────

reel = pytest.mark.skipif(not offre.CHEMIN.exists(), reason="data/offre_theorique.json absent")


@reel
class TestFichierReel:
    def test_somme_des_heures_egale_trains_du_jour(self):
        """Invariant de la docstring : Σ trains équivalents des 24 heures = trains du jour."""
        c = offre.charger()
        for ligne in offre.LIGNE_ROUTE:
            for cat in CATEGORIES:
                somme = sum(c["trains_heure"][ligne][cat])
                jour = c["trains_jour"][ligne][cat]
                assert somme == pytest.approx(jour, rel=0.01), f"{ligne} {cat} : {somme} ≠ {jour}"

    def test_treize_lignes_cinq_jours_types(self):
        c = offre.charger()
        assert set(c["trains_heure"]) == set(offre.LIGNE_ROUTE)
        for ligne in offre.LIGNE_ROUTE:
            for table in ("trains_heure", "intervalle_min"):
                assert set(c[table][ligne]) == set(CATEGORIES)
                assert all(len(v) == 24 for v in c[table][ligne].values())

    def test_intervalles_bornes(self):
        c = offre.charger()
        for ligne, cats in c["intervalle_min"].items():
            for serie in cats.values():
                assert all(v is None or 0 < v <= offre.INTERVALLE_MAX_MIN for v in serie), ligne

    def test_rer_a_pointe_du_matin(self):
        mardi_8h = datetime(2026, 9, 22, 8, 30, tzinfo=PARIS)
        assert 30 <= offre.trains_heure("RER_A", mardi_8h) <= 80
        assert offre.intervalle_min("RER_A", mardi_8h) <= 6

    def test_ligne_inconnue(self):
        assert offre.trains_heure("METRO_1", datetime(2026, 9, 22, 8, tzinfo=PARIS)) is None
