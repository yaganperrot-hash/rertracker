"""Tests des bilans du dimanche : périodes, agrégats, texte, publication, liste /api/publications."""
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend import api
from backend.bot import _compose_recap_periode, post_recaps_periode
from backend.metrics import cout_eur
from backend.periodes import agreger, est_dernier_dimanche, evolution_pct, mois_de, semaine_de

SMIC = 12.31


def _row(jour, line="RER_A", mv=1000, inc=3, rt=2, sup=1, perturbe=True):
    return SimpleNamespace(date=jour, line_id=line, minutes_voyageurs=mv, nb_incidents=inc,
                           nb_rt_delays=rt, nb_cancelled=sup, est_jour_perturbe=perturbe)


# ── Périodes ──────────────────────────────────────────────

def test_semaine_du_lundi_au_dimanche():
    assert semaine_de(date(2026, 11, 8)) == (date(2026, 11, 2), date(2026, 11, 8))
    with pytest.raises(ValueError):
        semaine_de(date(2026, 11, 7))


@pytest.mark.parametrize("jour, attendu", [
    (date(2026, 11, 29), True),    # dernier dimanche de novembre (le 30 est un lundi)
    (date(2026, 11, 22), False),
    (date(2026, 5, 31), True),     # dernier jour du mois et dimanche
    (date(2026, 11, 28), False),   # samedi
])
def test_dernier_dimanche(jour, attendu):
    assert est_dernier_dimanche(jour) is attendu


def test_mois_du_premier_au_dernier_dimanche():
    assert mois_de(date(2026, 11, 29)) == (date(2026, 11, 1), date(2026, 11, 29))
    with pytest.raises(ValueError):
        mois_de(date(2026, 11, 22))


# ── Agrégats ──────────────────────────────────────────────

def test_cout_arrondi_par_ligne_et_par_jour():
    # 97 mv → 19 € par ligne × jour ; arrondir la somme (388 mv) donnerait 79 €, pas 76
    du, au = date(2026, 11, 2), date(2026, 11, 8)
    rows = [_row(du, "RER_A", 97), _row(du, "RER_B", 97), _row(au, "RER_A", 97), _row(au, "RER_B", 97)]
    agg = agreger(rows, du, au, SMIC)
    assert agg["cout_eur"] == 4 * cout_eur(97, SMIC) == 76
    assert agg["cout_eur"] == sum(l["cout_eur"] for l in agg["lignes"])


def test_bornes_incluses_et_lignes_hors_perimetre_ignorees():
    du, au = date(2026, 11, 2), date(2026, 11, 8)
    rows = [_row(du - timedelta(days=1)), _row(du), _row(au), _row(au + timedelta(days=1)),
            _row(du, "METRO_1")]
    agg = agreger(rows, du, au, SMIC)
    assert agg["total_incidents"] == 6
    assert [l["line_id"] for l in agg["lignes"]] == ["RER_A"]
    assert agg["nb_jours"] == 7


def test_detail_par_ligne_trie_et_totaux():
    du, au = date(2026, 11, 2), date(2026, 11, 8)
    rows = [_row(du, "RER_B", 500, perturbe=False), _row(du, "RER_A", 2000), _row(au, "RER_B", 1000)]
    agg = agreger(rows, du, au, SMIC)
    assert [l["line_id"] for l in agg["lignes"]] == ["RER_A", "RER_B"]
    assert agg["total_minutes_voyageurs"] == 3500
    assert agg["nb_lignes_perturbees"] == 2
    b = agg["lignes"][1]
    assert (b["nb_rt_delays"], b["nb_cancelled"], b["jours_perturbes"]) == (4, 2, 1)


def test_jours_avant_donnees_fiables_exclus():
    # Données fiables à partir du 2026-09-16 : la semaine du 14 n'en compte que 5 jours
    du, au = date(2026, 9, 14), date(2026, 9, 20)
    agg = agreger([_row(date(2026, 9, 15)), _row(date(2026, 9, 16))], du, au, SMIC)
    assert agg["du_effectif"] == "2026-09-16"
    assert agg["nb_jours"] == 5
    assert agg["total_incidents"] == 3


def test_trains_prevus_sommes_sur_les_jours():
    du, au = date(2026, 11, 2), date(2026, 11, 8)
    agg = agreger([_row(du)], du, au, SMIC, trains_prevus=lambda l, j: 100.4)
    assert agg["lignes"][0]["trains_prevus"] == 703
    inconnu = agreger([_row(du)], du, au, SMIC, trains_prevus=lambda l, j: None)
    assert inconnu["lignes"][0]["trains_prevus"] is None


def test_evolution_pct():
    assert evolution_pct(112, 100) == 12
    assert evolution_pct(92, 100) == -8
    assert evolution_pct(50, 0) is None
    assert evolution_pct(50, None) is None


# ── Texte ─────────────────────────────────────────────────

def _agg(du, au, euros=5_812_340, mv=27_380_000, inc=11_204, pire="RER_B"):
    return {"du": du.isoformat(), "au": au.isoformat(), "cout_eur": euros, "total_minutes_voyageurs": mv,
            "total_incidents": inc, "lignes": [{"line_id": pire, "minutes_voyageurs": 10}]}


def test_texte_semaine():
    texte = _compose_recap_periode("semaine", _agg(date(2026, 11, 2), date(2026, 11, 8)), 12)
    assert texte == (
        "🚨 Bilan de la semaine (02/11 → 08/11) — RER & Transilien 🚨\n"
        "\n"
        "5 812 340 € perdus à cause des retards\n"
        "52 ans 33 jours de vie gâchés\n"
        "11 204 incidents, RER B en tête\n"
        "+12 % par rapport à la semaine dernière\n"
        "\n"
        "Base SMIC 12,31 €/h · idf-retard.fr"
    )


def test_texte_evolution_negative_nulle_ou_absente():
    agg = _agg(date(2026, 11, 2), date(2026, 11, 8))
    assert "−8 % par rapport à la semaine dernière" in _compose_recap_periode("semaine", agg, -8)
    assert "Autant que la semaine dernière" in _compose_recap_periode("semaine", agg, 0)
    assert "semaine dernière" not in _compose_recap_periode("semaine", agg, None)


@pytest.mark.parametrize("au, titre", [
    (date(2026, 11, 29), "Bilan de novembre (01/11 → 29/11)"),
    (date(2026, 8, 30), "Bilan d’août (01/08 → 30/08)"),
    (date(2026, 10, 25), "Bilan d’octobre (01/10 → 25/10)"),
])
def test_texte_mois(au, titre):
    texte = _compose_recap_periode("mois", _agg(au.replace(day=1), au))
    assert texte.startswith(f"🚨 {titre} — RER & Transilien 🚨\n")


# ── Publication du dimanche ───────────────────────────────

def _mock_base(rows):
    return patch("backend.bot._metriques_entre", AsyncMock(return_value=rows))


def _sans_images():
    return (patch("backend.bot.generer_carte_png", AsyncMock(return_value=None)),
            patch("backend.bot.generer_carousel_png", AsyncMock(return_value=[])))


async def test_dimanche_ordinaire_bilan_semaine_seul(tmp_path):
    dimanche = date(2026, 11, 8)
    rows = [_row(dimanche, mv=2240), _row(dimanche - timedelta(days=7), mv=2000)]
    carte, carousel = _sans_images()
    with _mock_base(rows), carte as c, carousel:
        await post_recaps_periode(dossier=tmp_path, jour=dimanche)
    assert sorted(f.name for f in tmp_path.iterdir()) == ["2026-11-08-semaine.txt"]
    texte = (tmp_path / "2026-11-08-semaine.txt").read_text(encoding="utf-8")
    assert "Bilan de la semaine (02/11 → 08/11)" in texte
    assert "+12 % par rapport à la semaine dernière" in texte
    assert c.await_args.args[2:] == ("-semaine", "?type=semaine&du=2026-11-02&au=2026-11-08")


async def test_dernier_dimanche_semaine_et_mois(tmp_path):
    carte, carousel = _sans_images()
    with _mock_base([_row(date(2026, 11, 29))]), carte, carousel as k:
        await post_recaps_periode(dossier=tmp_path, jour=date(2026, 11, 29))
    noms = sorted(f.name for f in tmp_path.iterdir())
    assert noms == ["2026-11-29-mois.txt", "2026-11-29-semaine.txt"]
    assert k.await_args.args[3] == "?type=mois&du=2026-11-01&au=2026-11-29"


async def test_pas_un_dimanche_rien(tmp_path):
    with _mock_base([_row(date(2026, 11, 7))]):
        await post_recaps_periode(dossier=tmp_path, jour=date(2026, 11, 7))
    assert not tmp_path.exists() or not any(tmp_path.iterdir())


async def test_echec_semaine_ne_bloque_pas_le_mois(tmp_path):
    carte, carousel = _sans_images()
    with _mock_base([_row(date(2026, 11, 29))]), carte, carousel, \
         patch("backend.periodes.evolution_pct", side_effect=RuntimeError("boum")):
        await post_recaps_periode(dossier=tmp_path, jour=date(2026, 11, 29))
    assert sorted(f.name for f in tmp_path.iterdir()) == ["2026-11-29-mois.txt"]


async def test_semaine_precedente_non_fiable_pas_de_comparaison(tmp_path):
    carte, carousel = _sans_images()
    with _mock_base([_row(date(2026, 9, 20)), _row(date(2026, 9, 13))]), carte, carousel:
        await post_recaps_periode(dossier=tmp_path, jour=date(2026, 9, 20))
    assert "semaine dernière" not in (tmp_path / "2026-09-20-semaine.txt").read_text(encoding="utf-8")


# ── /api/publications ─────────────────────────────────────

async def test_liste_publications_avec_bilans_du_dimanche(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_PUBLICATIONS_DIR", tmp_path)
    for nom in ["2026-11-07", "2026-11-08", "2026-11-08-semaine", "2026-11-29-mois", "2026-11-08-autre"]:
        (tmp_path / f"{nom}.txt").write_text(nom, encoding="utf-8")
    (tmp_path / "2026-11-08-semaine.png").write_bytes(b"")
    (tmp_path / "2026-11-08-semaine").mkdir()
    (tmp_path / "2026-11-08-semaine" / "slide-1.png").write_bytes(b"")

    pubs = await api.list_publications()
    assert [(p["date"], p["type"]) for p in pubs] == [
        ("2026-11-29-mois", "mois"),
        ("2026-11-08-semaine", "semaine"), ("2026-11-08", "jour"),
        ("2026-11-07", "jour"),
    ]
    semaine = pubs[1]
    assert (semaine["texte"], semaine["has_png"], semaine["nb_slides"]) == ("2026-11-08-semaine", True, 1)
