"""Tests de l'API : coût par incident et paramètres de référence, sans base."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.api import _serialize_incident, reference
from backend.collector import LIGNES_CIBLES
from backend.config import get_settings
from backend.metrics import FREQUENTATION, cout_eur, incident_minutes_voyageurs

NOW = datetime(2026, 9, 11, 6, 30, tzinfo=timezone.utc)  # 8 h 30 à Paris
SMIC = 12.31


def _incident(**kw):
    champs = dict(
        id=1, navitia_id="rt_x_20260911", line_id="RER_A", type_incident="DELAY_REALTIME",
        cause="Retard de 10 min à Châtelet", heure_debut=NOW - timedelta(minutes=5),
        heure_fin=NOW + timedelta(minutes=5), duree_minutes=10, source="realtime",
        heure_theorique=None, is_cancelled=False, gare=None, direction=None, mission=None,
    )
    champs.update(kw)
    return SimpleNamespace(**champs)


class TestCoutIncident:
    def test_retard_meme_calcul_que_les_metriques_du_jour(self):
        inc = _incident()
        _, mv = incident_minutes_voyageurs(inc, NOW)
        d = _serialize_incident(inc, NOW, SMIC)
        assert mv > 0
        assert d["minutes_voyageurs"] == mv
        assert d["cout_eur"] == cout_eur(mv, SMIC)

    def test_train_supprime_a_un_cout(self):
        inc = _incident(is_cancelled=True, type_incident="CANCELLED", duree_minutes=5)
        assert _serialize_incident(inc, NOW, SMIC)["cout_eur"] > 0

    def test_perturbation_declaree_sans_cout(self):
        inc = _incident(source="disruption", type_incident="SIGNIFICANT_DELAYS", cause="Trafic perturbé")
        d = _serialize_incident(inc, NOW, SMIC)
        assert d["minutes_voyageurs"] is None
        assert d["cout_eur"] is None


class TestReference:
    async def test_valeurs_lues_dans_la_config(self):
        s = get_settings()
        ref = await reference()
        assert ref["smic_horaire"] == s.smic_horaire
        assert "quota_prim_jour" not in ref  # quota PRIM réel inconnu : jamais affiché
        assert ref["frequentation"] == FREQUENTATION

    async def test_requetes_prim_par_jour(self):
        # À chaque relevé : 2 appels perturbations (RER, Transilien) + 1 appel départs par ligne
        s = get_settings()
        ref = await reference()
        assert ref["requetes_prim_jour"] == (1440 // s.polling_interval_minutes) * (2 + len(LIGNES_CIBLES))

    async def test_parametres_du_calcul(self):
        # La page Méthode affiche ces valeurs : elles doivent être celles du code
        from backend.collector import GHOST_MIN_DELAY_MINUTES, MIN_DELAY_MINUTES
        from backend.metrics import HOURLY_WEIGHTS
        s = get_settings()
        ref = await reference()
        assert ref["poids_horaires"] == HOURLY_WEIGHTS
        assert ref["retard_min_minutes"] == MIN_DELAY_MINUTES
        assert ref["suppression_minutes"] == s.cancel_default_impact_minutes
        assert ref["fantome_min_minutes"] == GHOST_MIN_DELAY_MINUTES
