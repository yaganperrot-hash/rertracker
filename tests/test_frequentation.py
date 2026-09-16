"""Tests de backend/frequentation.py — voyageurs montant dans un train, par gare et par heure."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend import frequentation as f
from backend.profils import CATEGORIES, LIGNE_RESEAU

PARIS = ZoneInfo("Europe/Paris")


def _offre(departs_a=None, departs_b=None):
    departs_a = departs_a or [0.0] * 6 + [10.0] * 4 + [5.0] * 14
    departs_b = departs_b or [0.0] * 6 + [4.0] * 18
    return {
        "missions": {"RER_C": {"GOTA": ["Gare Alpha", "Gare Beta"]}},
        "zdc": {"Gare Alpha": "1001", "Gare Beta": "1002"},
        "trains_gare": {"RER_C": {cat: {"Gare Alpha": departs_a, "Gare Beta": departs_b} for cat in CATEGORIES}},
    }


PROFIL_PLAT = [1 / 24] * 24


def _comptage(gare, jour, tranche, montants, date="2025-06-02"):
    return {"ligne": "C", "nom_gare": gare, "type_jour": jour, "tranche_horaire": tranche,
            "somme_de_montants": montants, "date": date, "annee": date[:4]}


class TestJetons:
    def test_meme_gare_ecritures_differentes(self):
        assert f.jetons("PARIS-GARE-DU-NORD") == f.jetons("Gare du Nord")
        assert f.jetons("AEROPORT-CHARLES-DE-GAULLE-1-(TERMINAL-3)") == f.jetons("Aéroport CDG 1 (Terminal 3)")

    def test_gares_distinctes(self):
        assert f.jetons("Massy - Palaiseau") != f.jetons("Palaiseau")


class TestRepartir:
    def test_prorata_du_profil_sur_les_heures_avec_departs(self):
        departs = [0.0] * 6 + [1.0] * 18
        profil = [0.0] * 6 + [1.0, 3.0, 0.0, 0.0] + [0.0] * 14
        assert f.repartir(400, range(6, 10), profil, departs) == {6: 100.0, 7: 300.0, 8: 0.0, 9: 0.0}

    def test_sans_depart_rien(self):
        assert f.repartir(400, range(0, 6), PROFIL_PLAT, [0.0] * 24) == {}

    def test_profil_nul_prorata_des_departs(self):
        departs = [0.0] * 6 + [1.0, 3.0, 0.0, 0.0] + [0.0] * 14
        assert f.repartir(40, range(6, 10), [0.0] * 24, departs) == {6: 10.0, 7: 30.0}


class TestAssembler:
    def test_comptage_reparti_puis_divise_par_les_departs(self):
        comptages = [_comptage("GARE-ALPHA", "JOB", "De 6h à 10h", 800)]
        t = f.assembler(_offre(), {"profils": {}}, comptages, {}, {("803", "1001"): {"JOHV": PROFIL_PLAT}}, {})
        # 800 montés de 6 h à 10 h, profil plat → 200 par heure, 10 départs par heure → 20 par train
        assert t["montees_train"]["RER_C"]["JOHV"]["Gare Alpha"][6:10] == [20.0] * 4
        assert t["montees_jour"]["RER_C"]["JOHV"]["Gare Alpha"] == 800
        assert t["origine"]["RER_C"]["Gare Alpha"] == "comptage SNCF 2025"

    def test_campagne_la_plus_recente(self):
        comptages = [_comptage("GARE-ALPHA", "JOB", "De 6h à 10h", 800, "2019-03-01"),
                     _comptage("GARE-ALPHA", "JOB", "De 6h à 10h", 400, "2025-03-01")]
        t = f.assembler(_offre(), {"profils": {}}, comptages, {}, {}, {})
        assert t["montees_jour"]["RER_C"]["JOHV"]["Gare Alpha"] == 400

    def test_vacances_rapport_mesure(self):
        comptages = [_comptage("GARE-ALPHA", "JOB", "De 6h à 10h", 800)]
        t = f.assembler(_offre(), {"profils": {}}, comptages, {}, {}, {"803": {"JOVS": 0.75}})
        assert t["montees_jour"]["RER_C"]["JOVS"]["Gare Alpha"] == 600

    def test_gare_sans_comptage_validations_partagees_entre_lignes(self):
        offre_c = _offre()
        # Une autre ligne suivie part aussi de Gare Beta, trois fois plus souvent
        offre_c["trains_gare"]["RER_D"] = {cat: {"Gare Beta": [0.0] * 6 + [12.0] * 18} for cat in CATEGORIES}
        validations = {("803", "1002"): {"JOHV": 3600.0}}
        t = f.assembler(offre_c, {"profils": {}}, [], validations, {("803", "1002"): {"JOHV": PROFIL_PLAT}}, {})
        assert t["origine"]["RER_C"]["Gare Beta"] == "validations IDFM 2025 T3"
        assert t["montees_jour"]["RER_C"]["JOHV"]["Gare Beta"] == pytest.approx(900)

    def test_gare_rattachee_par_le_nom(self):
        offre_c = _offre()
        offre_c["zdc"]["Gare Beta"] = "474151"   # id GTFS absent des validations
        validations = {("803", "71264"): {"JOHV": 1800.0}}
        noms = {("803", "71264"): "BETA"}
        t = f.assembler(offre_c, {"profils": {}}, [], validations, {}, {}, noms)
        assert t["montees_jour"]["RER_C"]["JOHV"]["Gare Beta"] == pytest.approx(1800)

    def test_invariant_montees_train_fois_departs(self):
        """Docstring du module : Σ_h montées_train × départs = montées du jour."""
        comptages = [_comptage("GARE-ALPHA", "JOB", t, 1000 + i) for i, t in enumerate(f.TRANCHES)]
        t = f.assembler(_offre(), {"profils": {}}, comptages, {}, {}, {})
        departs = _offre()["trains_gare"]["RER_C"]["JOHV"]["Gare Alpha"]
        serie = t["montees_train"]["RER_C"]["JOHV"]["Gare Alpha"]
        assert sum(m * d for m, d in zip(serie, departs)) == pytest.approx(
            t["montees_jour"]["RER_C"]["JOHV"]["Gare Alpha"], rel=1e-3)
        # « Avant 6h » sans départ : non réparti, signalé
        assert t["perdus"]["RER_C"] == 1000


reel = pytest.mark.skipif(not f.CHEMIN.exists(), reason="data/frequentation_gares.json absent")


@reel
class TestFichierReel:
    def test_toutes_les_lignes_et_jours_types(self):
        c = f.charger()
        assert set(c["montees_train"]) == set(LIGNE_RESEAU)
        for ligne in LIGNE_RESEAU:
            assert set(c["montees_train"][ligne]) == set(CATEGORIES)

    def test_invariant_sur_les_donnees_publiees(self):
        from backend import offre
        c, o = f.charger(), offre.charger()
        for ligne, cats in c["montees_train"].items():
            for cat, gares in cats.items():
                for gare, serie in gares.items():
                    departs = o["trains_gare"][ligne][cat][gare]
                    total = sum(m * d for m, d in zip(serie, departs))
                    assert total == pytest.approx(c["montees_jour"][ligne][cat][gare], rel=0.01, abs=5), (ligne, cat, gare)

    def test_toutes_les_gares_ont_une_source(self):
        c = f.charger()
        inconnues = [(l, g) for l, gares in c["origine"].items() for g, o in gares.items() if o == "inconnue"]
        assert inconnues == []

    def test_ordre_de_grandeur(self):
        mardi_8h = datetime(2026, 9, 22, 8, 30, tzinfo=PARIS)
        assert 50 <= f.montees_train("RER_A", "La Défense", mardi_8h) <= 3000
        assert f.montees_train("RER_A", "Gare inconnue", mardi_8h) is None
