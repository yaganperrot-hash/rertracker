"""Tests de l'API : coût par incident et paramètres de référence, sans base."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.api import _serialize_incident, reference
from backend.collector import LIGNES_CIBLES, MODES_PHYSIQUES, REQUETES_ET_PAR_RELEVE
from backend.config import Settings, get_settings
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

    def test_train_supprime_duree_affichee_egale_duree_comptee(self):
        inc = _incident(is_cancelled=True, type_incident="CANCELLED", duree_minutes=5)
        dur, _ = incident_minutes_voyageurs(inc, NOW)
        assert _serialize_incident(inc, NOW, SMIC)["duree_minutes"] == dur

    async def test_reference_expose_l_offre(self):
        ref = await reference()
        assert set(ref["offre_trains_heure"]) == set(LIGNES_CIBLES.values())
        assert set(ref["offre_intervalle_min"]) == set(LIGNES_CIBLES.values())
        assert "fenetre" in ref["offre_source"]

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
        assert ref["quota_prim_jour"] == s.prim_quota_jour
        assert ref["collecte_heure_debut"] == s.collecte_heure_debut
        assert ref["frequentation"] == FREQUENTATION

    async def test_exemple_de_la_page_methode_calcule(self):
        ex = (await reference())["exemple_calcul"]
        assert ex["voyageurs"] > 0
        # Les voyageurs à quai peuvent prendre le train suivant : résultat positif et au plus
        # le pire cas (tous les voyageurs × retard brut), affiché sur la page Méthode
        assert ex["minutes_voyageurs_retard_max"] == ex["voyageurs"] * ex["retard"]
        assert 0 < ex["minutes_voyageurs_retard"] <= ex["voyageurs"] * ex["retard"]

    async def test_requetes_par_flux(self):
        ref = await reference()
        assert ref["requetes_navitia_jour"] + ref["requetes_et_jour"] == ref["requetes_prim_jour"]
        assert ref["requetes_et_jour"] <= ref["quota_prim_jour"]

    async def test_requetes_prim_par_jour(self):
        # Relevés de collecte_heure_debut à minuit : 1 appel Estimated Timetable (flux global) par relevé temps réel,
        # 2 appels Navitia (un par mode) par relevé des perturbations
        s = get_settings()
        ref = await reference()
        minutes = (24 - s.collecte_heure_debut) * 60
        assert ref["requetes_et_jour"] == minutes // s.polling_interval_minutes
        assert ref["requetes_navitia_jour"] == minutes // s.perturbations_interval_minutes * 2

    def test_reglage_par_defaut_sous_le_quota(self):
        # Quota PRIM : 1 000 req/jour par flux (en-tête x-ratelimit-limit-day). Défauts, de 6 h à minuit :
        # temps réel toutes les 5 min → 216 ; perturbations toutes les 20 min → 108
        d = Settings(_env_file=None)
        minutes = (24 - d.collecte_heure_debut) * 60
        et = minutes // d.polling_interval_minutes * REQUETES_ET_PAR_RELEVE
        navitia = minutes // d.perturbations_interval_minutes * len(MODES_PHYSIQUES)
        assert (et, navitia) == (216, 108)
        assert et <= d.prim_quota_jour and navitia <= d.prim_quota_jour

    async def test_parametres_du_calcul(self):
        # La page Méthode affiche ces valeurs : elles doivent être celles du code
        from backend.collector import FENETRE_MESURE_MINUTES, GHOST_MIN_DELAY_MINUTES, MIN_DELAY_MINUTES
        from backend.metrics import PROFILS
        s = get_settings()
        ref = await reference()
        assert ref["profils_horaires"] == PROFILS["profils"]
        assert ref["profils_lignes"] == PROFILS["lignes"]
        assert ref["retard_min_minutes"] == MIN_DELAY_MINUTES
        assert ref["suppression_minutes"] == s.cancel_default_impact_minutes
        assert ref["fantome_min_minutes"] == GHOST_MIN_DELAY_MINUTES
        assert ref["fenetre_mesure_minutes"] == FENETRE_MESURE_MINUTES


class TestMonTrajet:
    async def test_gares_de_la_ligne(self):
        from backend.api import trajet_gares
        r = await trajet_gares(ligne="RER_C")
        assert "Choisy-le-Roi" in r["gares"] and "Ivry-sur-Seine" in r["gares"]

    async def test_ligne_inconnue(self):
        import pytest
        from fastapi import HTTPException
        from backend.api import trajet, trajet_gares
        with pytest.raises(HTTPException) as e:
            await trajet_gares(ligne="METRO_1")
        assert e.value.status_code == 404
        with pytest.raises(HTTPException) as e:
            await trajet(db=None, ligne="RER_C", depart="Nulle part", arrivee="Ivry-sur-Seine", heure="08:10",
                         jours="1", periode=7)
        assert e.value.status_code == 422
