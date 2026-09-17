"""Tests de backend/trajets.py — « Mon trajet » (bêta, aller simple), sans base ni réseau."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from backend import offre, trajets
from backend.trajets import perte_du_jour, trains_du_jour, uid_incident

PARIS = ZoneInfo("Europe/Paris")
JEUDI = date(2026, 9, 17)
UUID = "00000000-0000-0000-0000-00000000000{}"


def _hm(h, m):
    return datetime(2026, 9, 17, h, m, tzinfo=PARIS)


@pytest.fixture
def horaires(monkeypatch):
    """Ligne RER_C : A → B → C. T1 prévu 8 h 13 en A, T2 omnibus 8 h 17, T3 direct A → C (sans B) 8 h 15.
    Services : 0 = tous les jours, 1 = jamais le 17."""
    monkeypatch.setattr(offre, "_cache_horaires", {
        "_source": {"fenetre": ["2026-09-14", "2026-10-16"]},
        "debut": "2026-09-14",
        "services": [list(range(30)), [0, 1]],
        "lignes": {"RER_C": {"gares": ["A", "B", "C"], "trains": [
            [f"IDFM:TN:SNCF:{UUID.format(1)}", "ZANI", 0, [0, 493, 1, 501, 2, 504]],
            [f"IDFM:TN:SNCF:{UUID.format(2)}", "GOTA", 0, [0, 497, 1, 505, 2, 508]],
            [f"IDFM:TN:SNCF:{UUID.format(3)}", "SICA", 0, [0, 495, 2, 502]],
            [f"IDFM:TN:SNCF:{UUID.format(4)}", "NORA", 1, [0, 480, 1, 488]],
        ]}},
    })


def _trains(dep="A", arr="B"):
    trains = trains_du_jour("RER_C", dep, arr, JEUDI)
    for t in trains:
        t["uid"], t["gare_depart"], t["gare_arrivee"] = uid_incident(t["trip_id"], JEUDI), dep, arr
    return trains


def _incident(n, arrets, cancelled=False):
    uid = uid_incident(f"IDFM:TN:SNCF:{UUID.format(n)}", JEUDI)
    return uid, SimpleNamespace(navitia_id=uid, arrets=arrets, is_cancelled=cancelled)


def _arret(g, h, m, r=0, s=False, k=False):
    a = {"g": g, "p": _hm(h, m).isoformat(), "r": r, "s": s, "w": None}
    return {**a, "k": True} if k else a


class TestHoraires:
    def test_trains_qui_desservent_depart_puis_arrivee(self, horaires):
        assert [t["mission"] for t in trains_du_jour("RER_C", "A", "B", JEUDI)] == ["ZANI", "GOTA"]
        assert [t["mission"] for t in trains_du_jour("RER_C", "A", "C", JEUDI)] == ["ZANI", "SICA", "GOTA"]
        assert trains_du_jour("RER_C", "B", "A", JEUDI) == []          # mauvais sens
        assert trains_du_jour("RER_C", "A", "Z", JEUDI) == []

    def test_uid_comme_la_collecte(self):
        assert uid_incident(f"IDFM:TN:SNCF:{UUID.format(1)}", JEUDI) == \
            f"rt_vehicle_journey:IDFM:TN:SNCF:{UUID.format(1)}_20260917"

    def test_gares_triees_sans_accents(self, monkeypatch):
        monkeypatch.setattr(offre, "_cache_horaires", {"lignes": {"RER_C": {"gares": ["Ivry", "Érmont", "Choisy"]}}})
        assert trajets.gares_ligne("RER_C") == ["Choisy", "Érmont", "Ivry"]


class TestPerteDuJour:
    def test_trains_a_l_heure(self, horaires):
        r = perte_du_jour(_trains(), {}, _hm(8, 10))
        assert (r["prevu"]["mission"], r["pris"]["mission"], r["perte_min"], r["mesure"]) == ("ZANI", "ZANI", 0, False)

    def test_train_prevu_en_retard(self, horaires):
        uid, inc = _incident(1, [_arret("A", 8, 13, 4), _arret("B", 8, 21, 4)])
        r = perte_du_jour(_trains(), {uid: inc}, _hm(8, 10))
        # ZANI arrive à 8 h 25 ; GOTA, à l'heure, à 8 h 25 aussi → 4 min
        assert (r["perte_min"], r["mesure"]) == (4, True)

    def test_le_train_suivant_arrive_avant(self, horaires):
        uid, inc = _incident(1, [_arret("A", 8, 13, 15), _arret("B", 8, 21, 15)])
        r = perte_du_jour(_trains(), {uid: inc}, _hm(8, 10))
        assert (r["pris"]["mission"], r["perte_min"]) == ("GOTA", 4)

    def test_train_supprime_a_l_arrivee(self, horaires):
        uid, inc = _incident(1, [_arret("A", 8, 13), _arret("B", 8, 21, s=True)])
        r = perte_du_jour(_trains(), {uid: inc}, _hm(8, 10))
        assert (r["pris"]["mission"], r["perte_min"]) == ("GOTA", 4)

    def test_train_qui_ne_dessert_pas_l_arrivee_ignore(self, horaires):
        # SICA ne dessert pas B : jamais retenu vers B
        assert all(t["mission"] != "SICA" for t in _trains())

    def test_train_en_retard_parti_avant_l_heure_du_voyageur(self, horaires):
        # ZANI prévu 8 h 13 passé en avance à 8 h 09 : le voyageur de 8 h 10 le rate
        uid, inc = _incident(1, [_arret("A", 8, 13, -4), _arret("B", 8, 21, -4)])
        r = perte_du_jour(_trains(), {uid: inc}, _hm(8, 10))
        assert (r["pris"]["mission"], r["perte_min"]) == ("GOTA", 4)

    def test_train_d_avant_en_retard_rattrape(self, horaires):
        # Voyageur à 8 h 14 : ZANI (8 h 13) passé ; il arrive en fait à 8 h 20 avec 7 min de retard
        uid, inc = _incident(1, [_arret("A", 8, 13, 7), _arret("B", 8, 21, 7)])
        r = perte_du_jour(_trains(), {uid: inc}, _hm(8, 14))
        # Prévu : GOTA → 8 h 25 ; pris : ZANI → 8 h 28 ou GOTA → 8 h 25 : GOTA, aucune perte
        assert (r["prevu"]["mission"], r["pris"]["mission"], r["perte_min"]) == ("GOTA", "GOTA", 0)

    def test_releves_incoherents_train_ecarte_et_signale(self, horaires):
        # Cas du GOTA de 8 h 02 (17/09) : +11 au départ, +2 à l'arrivée périmé → arriverait avant d'être parti
        uid, inc = _incident(1, [_arret("A", 8, 13, 11), _arret("B", 8, 21, 0)])
        r = perte_du_jour(_trains(), {uid: inc}, _hm(8, 10))
        assert (r["pris"]["mission"], r["perte_min"], r["saute"]) == ("GOTA", 4, True)

    def test_arrivee_perimee_apres_une_gare_plus_en_retard(self, horaires):
        # Cas du ZANI de 7 h 58 (17/09) : +3 au départ et à l'arrivée, mais +10 à une gare entre les deux
        # (A 8 h 13, X 8 h 17, B 8 h 21) : 7 min rattrapées en 4 min, impossible → arrivée périmée
        uid, inc = _incident(1, [_arret("A", 8, 13, 3), _arret("X", 8, 17, 10), _arret("B", 8, 21, 3)])
        r = perte_du_jour(_trains(), {uid: inc}, _hm(8, 10))
        assert (r["pris"]["mission"], r["perte_min"], r["saute"]) == ("GOTA", 4, True)

    def test_rattrapage_plausible_garde(self, horaires):
        # 2 min rattrapées sur 8 min de trajet : dans la marge (2 min + 10 % × 8 min = 2,8 min) → train gardé
        uid, inc = _incident(1, [_arret("A", 8, 13, 6), _arret("B", 8, 21, 4)])
        r = perte_du_jour(_trains(), {uid: inc}, _hm(8, 10))
        assert (r["pris"]["mission"], r["perte_min"], r["saute"]) == ("ZANI", 4, False)

    def test_arret_saute_signale_sans_changer_le_calcul(self, horaires):
        uid, inc = _incident(1, [_arret("A", 8, 13, 4), _arret("B", 8, 21, 4, k=True)])
        r = perte_du_jour(_trains(), {uid: inc}, _hm(8, 10))
        assert (r["pris"]["mission"], r["perte_min"], r["saute"]) == ("ZANI", 4, True)

    def test_aucun_train_apres_l_heure(self, horaires):
        assert perte_du_jour(_trains(), {}, _hm(23, 0)) is None


class TestHorairesGtfs:
    def test_construction(self, tmp_path):
        import zipfile
        route = offre.LIGNE_ROUTE["RER_C"]
        chemin = tmp_path / "gtfs.zip"
        with zipfile.ZipFile(chemin, "w") as z:
            z.writestr("stops.txt", "stop_id,stop_name,parent_station\nP1,Gare Un,\nP2,Gare Deux,\n"
                                    "Q1,Gare Un,P1\nQ1b,Gare Un,P1\nQ2,Gare Deux,P2\n")
            z.writestr("trips.txt", f"route_id,service_id,trip_id,trip_headsign,direction_id\n{route},S,T1,ZANI,0\n"
                                    "AUTRE,S,T2,XXXX,0\n")
            z.writestr("stop_times.txt", "trip_id,departure_time,stop_id,stop_sequence\n"
                                         "T1,08:13:10,Q1,1\nT1,08:14:00,Q1b,2\nT1,24:21:30,Q2,3\nT2,08:00:00,Q1,1\n")
            z.writestr("calendar.txt", "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
                                       "start_date,end_date\nS,0,0,1,1,0,0,0,20260916,20260917\n")
            z.writestr("calendar_dates.txt", "service_id,date,exception_type\n")
        h = offre.horaires(chemin)
        assert h["debut"] == "2026-09-16" and h["services"] == [[0, 1]]
        assert list(h["lignes"]) == ["RER_C"]
        # Deux quais de la même gare à la suite : un seul passage ; 24:21 → 1461 min
        assert h["lignes"]["RER_C"] == {"gares": ["Gare Un", "Gare Deux"], "trains": [["T1", "ZANI", 0, [0, 493, 1, 1461]]]}

    def test_fichier_versionne_lisible_et_raisonnable(self):
        assert offre.CHEMIN_HORAIRES.stat().st_size < 5_000_000
        h = offre.charger_horaires()
        assert set(h["lignes"]) == set(offre.LIGNE_ROUTE)
