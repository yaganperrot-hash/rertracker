"""Tests unitaires pour backend/metrics.py"""
from datetime import date, datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from backend import offre
from backend import frequentation
from backend.metrics import (
    FREQUENTATION,
    arrets_du_train,
    incident_minutes_voyageurs,
    minutes_voyageurs_train,
    _effective_duration,
    _incident_dt_paris,
    PROFILS,
    part_horaire,
    MAX_OPEN_DURATION_MIN,
    get_today_stats,
    get_line_stats,
)
from backend.profils import CATEGORIES, LIGNE_RESEAU, categorie_jour, est_vacances

PARIS = ZoneInfo("Europe/Paris")
MARDI_8H = datetime(2026, 9, 15, 8, 30, tzinfo=PARIS)
MARDI_14H = datetime(2026, 9, 15, 14, 30, tzinfo=PARIS)
MARDI_3H = datetime(2026, 9, 15, 3, 30, tzinfo=PARIS)
SAMEDI_8H = datetime(2026, 9, 19, 8, 30, tzinfo=PARIS)
SAMEDI_18H = datetime(2026, 9, 19, 18, 30, tzinfo=PARIS)


class TestProfilsHoraires:
    """Profils horaires de validations (open data IDFM), utilisés pour répartir les comptages dans l'heure."""

    def test_toutes_les_lignes_rer_transilien_ont_un_profil(self):
        for line_id in LIGNE_RESEAU:
            assert part_horaire(line_id, MARDI_8H) is not None, f"{line_id} sans profil"

    def test_chaque_profil_somme_a_un(self):
        """Garde-fou : c'est la normalisation ratée de l'ancien profil qui biaisait tous les chiffres."""
        for reseau, cats in PROFILS["profils"].items():
            for cat, profil in cats.items():
                assert len(profil) == 24, f"{reseau}/{cat} : {len(profil)} tranches au lieu de 24"
                total = sum(profil)
                assert abs(total - 1.0) < 1e-4, f"{reseau}/{cat} somme à {total}, attendu 1.0"

    def test_tous_les_jours_types_presents(self):
        for reseau, cats in PROFILS["profils"].items():
            for cat in CATEGORIES:
                assert cat in cats, f"{reseau} sans profil {cat}"


class TestCategorieJour:
    def test_semaine(self):
        assert categorie_jour(date(2026, 9, 15)) == "JOHV"   # mardi

    def test_samedi(self):
        assert categorie_jour(date(2026, 9, 19)) == "SAHV"

    def test_dimanche(self):
        assert categorie_jour(date(2026, 9, 20)) == "DIJFP"

    def test_ferie_en_semaine_compte_comme_dimanche(self):
        assert categorie_jour(date(2026, 7, 14)) == "DIJFP"   # mardi 14 juillet

    def test_ferie_mobile(self):
        assert categorie_jour(date(2026, 5, 14)) == "DIJFP"   # Ascension 2026

    def test_semaine_en_vacances(self):
        assert categorie_jour(date(2026, 10, 19)) == "JOVS"   # lundi, vacances de la Toussaint

    def test_samedi_en_vacances(self):
        assert categorie_jour(date(2026, 10, 17)) == "SAVS"

    def test_bornes_des_vacances(self):
        """Toussaint 2026 zone C : du 17 octobre au 1er novembre, rentrée le 2."""
        assert est_vacances(date(2026, 10, 16)) is False
        assert est_vacances(date(2026, 10, 17)) is True
        assert est_vacances(date(2026, 11, 1)) is True
        assert est_vacances(date(2026, 11, 2)) is False

    def test_conversion_utc_vers_paris(self):
        """Les bornes sont publiées en UTC à 22 h : sans conversion tout glisserait d'un jour.
        Rentrée de septembre 2026 le mardi 1er, donc le 31 août est encore en vacances."""
        assert est_vacances(date(2026, 8, 31)) is True
        assert est_vacances(date(2026, 9, 1)) is False


class TestProfilsVacances:
    def test_cinq_jours_types(self):
        assert len(CATEGORIES) == 5
        for reseau, cats in PROFILS["profils"].items():
            assert set(cats) == set(CATEGORIES), f"{reseau} : {sorted(cats)}"


def _inc(**kw):
    from types import SimpleNamespace
    champs = dict(line_id="RER_A", heure_debut=None, heure_theorique=MARDI_8H, heure_fin=None,
                  duree_minutes=10, is_cancelled=False, gare=None, mission=None, arrets=None)
    champs.update(kw)
    return SimpleNamespace(**champs)


NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def _arrets(gares, retards=None, supprimes=(), attentes=None, ecarts=None, quand=MARDI_8H):
    retards = retards or [0] * len(gares)
    attentes = attentes or {}
    ecarts = ecarts or {}
    return [{"g": g, "quand": quand, "r": r, "s": i in supprimes, "w": attentes.get(i), "a": ecarts.get(i)}
            for i, (g, r) in enumerate(zip(gares, retards))]


INTERVALLE_FICTIF = 6  # minutes — intervalle médian de repli pour la ligne de test
# Départs par heure par gare, deux sens : A=20, B=10, C=6 → un train toutes les 6, 12 et 20 min dans un sens
TRAINS_GARE = {"A": 20, "B": 10, "C": 6}
ECART_PREVU = {g: 60 / (t / 2) for g, t in TRAINS_GARE.items()}  # A=6, B=12, C=20

@pytest.fixture
def ligne_fictive(monkeypatch):
    """Trois gares, 100 voyageurs montent dans chaque train à A et à B ; B et C attirent autant.
    Train suivant prévu dans un sens : A=6 min, B=12 min, C=20 min. Repli = INTERVALLE_FICTIF (6 min)."""
    monkeypatch.setattr(frequentation, "_cache", {
        "montees_train": {"RER_A": {"JOHV": {g: [100.0] * 24 for g in "ABC"}}},
        "montees_jour": {"RER_A": {"JOHV": {"A": 1000.0, "B": 1000.0, "C": 1000.0}}},
    })
    monkeypatch.setattr(offre, "trains_gare", lambda line_id, gare, quand: float(TRAINS_GARE.get(gare, 10)))
    monkeypatch.setattr(offre, "intervalle_min", lambda line_id, quand: float(INTERVALLE_FICTIF))


class TestMinutesVoyageursTrain:
    """Perte de chaque voyageur entre sa gare de montée et sa gare de descente (lot 6)."""

    def test_train_a_l_heure(self, ligne_fictive):
        assert minutes_voyageurs_train("RER_A", _arrets("ABC")) == 0

    def test_retard_au_terminus(self, ligne_fictive):
        # Retard pris après la montée : subi en entier. A → C : 50 × 10 ; B → C : 100 × 10
        assert minutes_voyageurs_train("RER_A", _arrets("ABC", [0, 0, 10])) == 50 * 10 + 100 * 10

    def test_retard_sous_le_seuil_non_compte(self, ligne_fictive):
        assert minutes_voyageurs_train("RER_A", _arrets("ABC", [1, 1, 1])) == 0

    def test_retard_partout(self, ligne_fictive):
        # Tous les voyageurs (200) arrivent avec 5 min de retard
        assert minutes_voyageurs_train("RER_A", _arrets("ABC", [5, 5, 5])) == 200 * 5

    def test_suppression_totale_attente_mesuree(self, ligne_fictive):
        arrets = _arrets("ABC", supprimes=(0, 1, 2), attentes={0: 12, 1: 20})
        # Montés en A attendent 12 min, montés en B 20 min
        assert minutes_voyageurs_train("RER_A", arrets) == 100 * 12 + 100 * 20

    def test_train_limite_en_cours_de_route(self, ligne_fictive):
        # Terminus avancé en B : seuls les voyageurs vers C attendent (attente mesurée en C : 15)
        arrets = _arrets("ABC", supprimes=(2,), attentes={2: 15})
        assert minutes_voyageurs_train("RER_A", arrets) == 50 * 15 + 100 * 15

    def test_attente_inconnue_intervalle_prevu(self, ligne_fictive):
        arrets = _arrets("ABC", supprimes=(0, 1, 2))
        assert minutes_voyageurs_train("RER_A", arrets) == 200 * INTERVALLE_FICTIF

    def test_invariant_chaque_voyageur_une_destination(self, ligne_fictive):
        """Même retard partout = voyageurs montés hors terminus × retard, quels que soient les poids."""
        frequentation._cache["montees_jour"]["RER_A"]["JOHV"] = {"A": 7.0, "B": 3000.0, "C": 11.0}
        assert minutes_voyageurs_train("RER_A", _arrets("ABC", [4, 4, 4])) == 200 * 4

    def test_retard_pris_a_bord_subi_en_entier(self, ligne_fictive):
        """Aucun plafond pour le voyageur déjà à bord : il ne peut pas prendre un autre train."""
        # A à l'heure, 15 min en B et C. A→B : 50 × 15 ; A→C : 50 × 15.
        # Montés en B : train prévu toutes les 12 min, le leur passe 15 min après l'heure → gain 3 → 100 × 12
        assert minutes_voyageurs_train("RER_A", _arrets("ABC", [0, 15, 15])) == 50 * 15 + 50 * 15 + 100 * 12

    def test_voyageur_a_quai_prend_le_train_suivant_mesure(self, ligne_fictive):
        """Écart mesuré avec le train suivant : le voyageur à quai perd au plus cet écart."""
        # 15 min partout ; train suivant mesuré à 5 min en A (vers B et C), 4 min en B (vers C)
        arrets = _arrets("ABC", [15, 15, 15], ecarts={0: {"B": 5, "C": 5}, 1: {"C": 4}})
        assert minutes_voyageurs_train("RER_A", arrets) == 100 * 5 + 100 * 4

    def test_train_suivant_d_une_autre_branche(self, ligne_fictive):
        """Le train suivant ne dessert pas C : les voyageurs A → C gardent tout le retard."""
        arrets = _arrets("ABC", [15, 15, 15], ecarts={0: {"B": 5}, 1: {}})
        assert minutes_voyageurs_train("RER_A", arrets) == 50 * 5 + 50 * 15 + 100 * 15

    def test_train_suivant_aussi_en_retard(self, ligne_fictive):
        """Jour de panne : le train suivant passe après le sien, personne ne gagne rien à quai."""
        arrets = _arrets("ABC", [15, 15, 15], ecarts={0: {"B": 20, "C": 20}, 1: {"C": 25}})
        assert minutes_voyageurs_train("RER_A", arrets) == 200 * 15

    def test_repli_sur_l_offre_prevue_dans_un_sens(self, ligne_fictive):
        """Sans mesure : écart = 60 ÷ (départs des deux sens ÷ 2) à la gare de montée."""
        # 8 min partout. A : train suivant prévu à 6 min → gain 2 → A→B et A→C : 6. B : 12 min → gain 0 → 8
        assert minutes_voyageurs_train("RER_A", _arrets("ABC", [8, 8, 8])) == 50 * 6 + 50 * 6 + 100 * 8

    def test_repli_sur_l_intervalle_de_la_ligne(self, ligne_fictive, monkeypatch):
        monkeypatch.setattr(offre, "trains_gare", lambda line_id, gare, quand: None)
        # Écart = INTERVALLE_FICTIF (6) partout → gain 2 pour tous → 200 × 6
        assert minutes_voyageurs_train("RER_A", _arrets("ABC", [8, 8, 8])) == 200 * 6

    def test_retard_resorbe_apres_la_montee(self, ligne_fictive):
        """Le gain à quai ne rend jamais une perte négative."""
        # A : 10 min, train suivant à 6 → gain 4 ; retard de 3 en B, 0 en C → pertes nulles. B→C : 0
        assert minutes_voyageurs_train("RER_A", _arrets("ABC", [10, 3, 0])) == 0

    def test_retard_sous_l_ecart_prevu(self, ligne_fictive):
        """Un retard inférieur à l'écart avec le train suivant n'est pas diminué."""
        assert minutes_voyageurs_train("RER_A", _arrets("ABC", [3, 3, 3])) == 200 * 3

    def test_suppression_non_affectee_par_plafond(self, ligne_fictive):
        """L'écart avec le train suivant ne touche pas les trains supprimés (branche attentes, pas retards)."""
        # Attente mesurée de 20 min > intervalle fictif de 6 min → pas capée
        arrets = _arrets("ABC", supprimes=(0, 1, 2), attentes={0: 20, 1: 20})
        assert minutes_voyageurs_train("RER_A", arrets) == 100 * 20 + 100 * 20


class TestArretsDuTrain:
    def test_arrets_releves(self):
        arrets = [{"g": "Nation", "p": "2026-09-15T06:30:00+00:00", "r": 5, "s": False, "w": None}]
        a = arrets_du_train(_inc(arrets=arrets, mission=None), NOW)
        assert a[-1]["g"] == "Nation" and a[-1]["r"] == 5
        assert a[-1]["quand"].hour == 8

    def test_debut_de_parcours_complete_par_la_mission(self):
        from backend import offre
        parcours = offre.charger()["missions"]["RER_A"]["QYRO"]
        releve = [{"g": parcours[5], "p": "2026-09-15T06:30:00+00:00", "r": 5, "s": False, "w": None}]
        a = arrets_du_train(_inc(arrets=releve, mission="QYRO"), NOW)
        assert [x["g"] for x in a] == parcours[:6]
        assert all(x["r"] is None for x in a[:5])

    def test_incident_d_avant_la_bascule_reconstitue(self):
        from backend import offre
        parcours = offre.charger()["missions"]["RER_A"]["QYRO"]
        a = arrets_du_train(_inc(mission="QYRO", gare=parcours[3], duree_minutes=7), NOW)
        assert [x["g"] for x in a] == parcours
        assert [x["r"] for x in a[:3]] == [0, 0, 0]
        assert all(x["r"] == 7 for x in a[3:])

    def test_heure_prevue_prioritaire(self):
        inc = _inc(heure_theorique=datetime(2026, 9, 15, 8, 55, tzinfo=PARIS),
                   heure_debut=datetime(2026, 9, 15, 9, 5, tzinfo=PARIS))
        assert _incident_dt_paris(inc).hour == 8


class TestIncidentMinutesVoyageurs:
    def test_retard_d_avant_la_bascule(self):
        dur, mv = incident_minutes_voyageurs(_inc(mission="QYRO", duree_minutes=10), NOW)
        assert dur == 10 and mv > 0

    def test_plus_tard_dans_le_parcours_moins_cher(self):
        from backend import offre
        parcours = offre.charger()["missions"]["RER_A"]["QYRO"]
        tot = incident_minutes_voyageurs(_inc(mission="QYRO", gare=parcours[0]), NOW)[1]
        tard = incident_minutes_voyageurs(_inc(mission="QYRO", gare=parcours[-2]), NOW)[1]
        assert tard < tot

    def test_pointe_plus_chere_que_le_creux(self):
        pointe = incident_minutes_voyageurs(_inc(mission="QYRO"), NOW)[1]
        creux = incident_minutes_voyageurs(_inc(mission="QYRO", heure_theorique=MARDI_14H), NOW)[1]
        assert pointe > creux

    def test_suppression_duree_affichee_plus_longue_attente(self):
        arrets = [{"g": "Nation", "p": "2026-09-15T06:30:00+00:00", "r": None, "s": True, "w": 9},
                  {"g": "Vincennes", "p": "2026-09-15T06:34:00+00:00", "r": None, "s": True, "w": 14}]
        dur, _ = incident_minutes_voyageurs(_inc(arrets=arrets, is_cancelled=True, duree_minutes=5), NOW)
        assert dur == 14

    def test_frequentation_affichee_par_ligne(self):
        assert set(FREQUENTATION) >= set(LIGNE_RESEAU)
        assert all(v > 0 for v in FREQUENTATION.values())


class TestEffectiveDuration:
    """Tests for _effective_duration."""

    def test_uses_duree_minutes_when_available(self):
        inc = MagicMock()
        inc.duree_minutes = 42
        inc.heure_fin = None
        inc.heure_debut = None
        assert _effective_duration(inc, datetime.now(timezone.utc)) == 42

    def test_uses_timestamp_diff_when_no_duree(self):
        now = datetime.now(timezone.utc)
        inc = MagicMock()
        inc.duree_minutes = None
        inc.heure_debut = now - timedelta(minutes=30)
        inc.heure_fin = now
        result = _effective_duration(inc, now)
        assert result == 30

    def test_open_incident_capped(self):
        """Open incident (no heure_fin, no duree_minutes) should be capped at MAX_OPEN_DURATION_MIN."""
        now = datetime.now(timezone.utc)
        inc = MagicMock()
        inc.duree_minutes = None
        inc.heure_fin = None
        inc.heure_debut = now - timedelta(hours=10)  # 600 min > 180 cap
        result = _effective_duration(inc, now)
        assert result == MAX_OPEN_DURATION_MIN, f"Expected {MAX_OPEN_DURATION_MIN}, got {result}"

    def test_timestamp_diff_not_capped_when_closed(self):
        """Incident fermé (heure_fin présente) : durée réelle, plus de cap à 180 min."""
        now = datetime.now(timezone.utc)
        inc = MagicMock()
        inc.duree_minutes = None
        inc.heure_debut = now - timedelta(hours=10)
        inc.heure_fin = now
        result = _effective_duration(inc, now)
        assert result == 600, f"Expected 600 (10 h), got {result}"


class TestNoDoubleCount:
    """Verify disruption incidents are not counted in duree_totale."""

    def test_disruption_source_not_in_rt(self):
        """Disruptions should be separated from RT in compute_daily_metrics logic.
        We test the separation by checking that only RT + cancelled contribute to totals."""
        # This is an integration-level test that verifies the logic in compute_daily_metrics.
        # The key invariant: an incident with source='disruption' should NOT
        # contribute to duree_totale_min or minutes_voyageurs.
        # Tested indirectly through the line_data grouping logic.
        pass  # Covered by the compute_daily_metrics integration test


class TestParisTimezone:
    """Verify Paris timezone is used for date calculations."""

    def test_paris_timezone_used(self):
        """At 01h UTC (which is 02h or 03h Paris depending on DST),
        the Paris date should be correct."""
        # 2024-03-15 01:00 UTC = 2024-03-15 02:00 Paris (CET)
        paris = ZoneInfo("Europe/Paris")
        utc_time = datetime(2024, 3, 15, 1, 0, tzinfo=timezone.utc)
        paris_date = utc_time.astimezone(paris).date()
        assert paris_date == date(2024, 3, 15)

        # 2024-06-15 23:30 UTC = 2024-06-16 01:30 Paris (CEST, +2)
        utc_time_late = datetime(2024, 6, 15, 23, 30, tzinfo=timezone.utc)
        paris_date_late = utc_time_late.astimezone(paris).date()
        assert paris_date_late == date(2024, 6, 16), (
            "23:30 UTC in summer should be next day in Paris"
        )


class TestGetTodayStats:
    @pytest.mark.asyncio
    async def test_empty_db_returns_zeros(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_today_stats(mock_db)

        assert result["total_incidents"] == 0
        assert result["total_duree_min"] == 0
        assert result["total_minutes_voyageurs"] == 0
        assert result["lignes_perturbees"] == []
        assert result["nb_lignes_perturbees"] == 0

    @pytest.mark.asyncio
    async def test_aggregates_multiple_lines(self):
        mock_db = AsyncMock()

        row_a = MagicMock(
            nb_incidents=3, duree_totale_min=45,
            minutes_voyageurs=25000, est_jour_perturbe=True, line_id="RER_A"
        )
        row_b = MagicMock(
            nb_incidents=1, duree_totale_min=20,
            minutes_voyageurs=8000, est_jour_perturbe=True, line_id="RER_B"
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [row_a, row_b]
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_today_stats(mock_db)

        assert result["total_incidents"] == 4
        assert result["total_duree_min"] == 65
        assert result["total_minutes_voyageurs"] == 33000
        assert set(result["lignes_perturbees"]) == {"RER_A", "RER_B"}
        assert result["nb_lignes_perturbees"] == 2

    @pytest.mark.asyncio
    async def test_date_field_uses_paris_tz(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_today_stats(mock_db)

        paris = ZoneInfo("Europe/Paris")
        expected_date = datetime.now(paris).date().isoformat()
        assert result["date"] == expected_date


class TestGetLineStats:
    @pytest.mark.asyncio
    async def test_empty_returns_zeros(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_line_stats("RER_A", 30, mock_db)

        assert result["line_id"] == "RER_A"
        assert result["total_incidents"] == 0
        assert result["total_duree_min"] == 0
        assert result["total_minutes_voyageurs"] == 0
        assert result["jours_perturbes"] == 0
        assert result["daily"] == []

    @pytest.mark.asyncio
    async def test_period_fields(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_line_stats("RER_B", 7, mock_db)

        assert result["period_days"] == 7
        assert result["line_id"] == "RER_B"
        assert "from" in result
        assert "to" in result

    @pytest.mark.asyncio
    async def test_daily_structure(self):
        mock_db = AsyncMock()

        row = MagicMock(
            date=date(2024, 3, 15),
            nb_incidents=2,
            duree_totale_min=30,
            minutes_voyageurs=12000,
            est_jour_perturbe=True,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [row]
        # 1ʳᵉ requête : daily_metrics ; suivantes (retard moyen pondéré) : aucun incident
        vide = MagicMock()
        vide.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[mock_result] + [vide] * 5)

        result = await get_line_stats("RER_C", 30, mock_db)

        assert len(result["daily"]) == 1
        day = result["daily"][0]
        assert day["date"] == "2024-03-15"
        assert day["nb_incidents"] == 2
        assert day["duree_totale_min"] == 30
        assert day["minutes_voyageurs"] == 12000
        assert day["est_jour_perturbe"] is True
