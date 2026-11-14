"""Pages d'archive par ligne et par jour : rendu, codes HTTP, sitemap. Sans base."""
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend import archives, main, seo
from backend.config import LINE_SLUGS, get_settings
from backend.metrics import PARIS_TZ, cout_eur, incident_minutes_voyageurs, journee_de

FRONTEND = Path(__file__).parent.parent / "frontend"
SITE = "https://idf-retard.fr"
J1, J2, J3 = date(2026, 11, 10), date(2026, 11, 11), date(2026, 11, 12)  # mardi, mercredi, jeudi
NOW = datetime(2026, 9, 11, 6, 30, tzinfo=timezone.utc)  # 8 h 30 à Paris
SMIC = 12.31


def _gabarit() -> str:
    return (FRONTEND / "archive.html").read_text(encoding="utf-8")


def _l(cout, minutes=None, retards=3, supprimes=1, perturbations=2) -> dict:
    return {"cout": cout, "minutes": minutes if minutes is not None else cout * 5,
            "retards": retards, "supprimes": supprimes, "perturbations": perturbations}


def _hist() -> dict:
    return {
        J1: {"RER_B": _l(1_000), "RER_A": _l(5_000)},
        J2: {"RER_B": _l(40_000), "RER_A": _l(2_000), "TRANSILIEN_H": _l(0, retards=0, supprimes=0, perturbations=0)},
        J3: {"RER_B": _l(3_000), "RER_A": _l(9_000), "RER_C": _l(4_000)},
    }


def _detail() -> dict:
    return {
        "trains": [
            {"heure": datetime(2026, 11, 11, 8, 42, tzinfo=PARIS_TZ), "gare": "Gare du Nord",
             "direction": "Aéroport CDG 2", "mission": "EKLI", "supprime": False, "duree": 25,
             "minutes": 9_000, "cout": 1_846},
            {"heure": datetime(2026, 11, 11, 18, 5, tzinfo=PARIS_TZ), "gare": "Massy <Palaiseau>", "direction": None,
             "mission": None, "supprime": True, "duree": 15, "minutes": 4_000, "cout": 820},
        ],
        "perturbations": [{"resume": "Trafic interrompu <script>alert(1)</script>", "categorie": "Panne"}],
    }


def _incident(**kw):
    champs = dict(
        id=1, navitia_id="rt_x", line_id="RER_A", type_incident="DELAY_REALTIME",
        cause="Retard de 10 min à Châtelet", heure_debut=NOW - timedelta(minutes=5),
        heure_fin=NOW + timedelta(minutes=5), duree_minutes=10, source="realtime",
        heure_theorique=None, is_cancelled=False, gare="Châtelet", direction="Cergy", mission="QYRO",
        lignes_impactees=None,
    )
    champs.update(kw)
    return SimpleNamespace(**champs)


@pytest.fixture
def base(monkeypatch):
    """Remplace les deux lectures en base."""
    hist, detail = _hist(), _detail()

    async def faux_hist():
        return hist

    async def faux_detail(line_id, jour):
        return detail
    monkeypatch.setattr(archives, "historique", faux_hist)
    monkeypatch.setattr(archives, "detail_jour", faux_detail)
    return hist


class TestHistorique:
    def test_jours_du_plus_recent_au_plus_ancien(self):
        assert archives.jours_de(_hist(), "RER_B") == [J3, J2, J1]
        assert archives.jours_de(_hist(), "TRANSILIEN_H") == [J2]
        assert archives.jours_de(_hist(), "TRANSILIEN_U") == []

    def test_rang_et_cout_du_reseau(self):
        hist = _hist()
        assert archives.rang_du_jour(hist, "RER_B", J2) == 1
        assert archives.rang_du_jour(hist, "RER_B", J3) == 3
        assert archives.cout_reseau(hist, J3) == 3_000 + 9_000 + 4_000

    def test_chemins_du_sitemap(self):
        chemins = archives.chemins_archives(_hist())
        assert len([c for c in chemins if c.endswith("/historique")]) == 13
        assert "/rer-b/2026-11-11" in chemins and "/ligne-h/2026-11-11" in chemins
        assert "/ligne-h/2026-11-10" not in chemins   # pas de donnée ce jour-là : pas de page
        assert len(chemins) == 13 + 3 + 3 + 1 + 1

    def test_base_en_panne_seuls_les_historiques(self):
        assert archives.chemins_archives(None) == [f"/{s}/historique" for s in LINE_SLUGS.values()]


class TestDetail:
    def test_trains_tries_par_cout_avec_le_calcul_des_metriques(self):
        petit = _incident(navitia_id="a", duree_minutes=5)
        gros = _incident(navitia_id="b", duree_minutes=30)
        trains = archives.trains_les_plus_couteux([petit, gros], NOW, SMIC)
        assert [t["duree"] for t in trains] == [30, 5]
        _, mv = incident_minutes_voyageurs(gros, NOW)
        assert trains[0]["minutes"] == mv and trains[0]["cout"] == cout_eur(mv, SMIC)
        assert trains[0]["heure"].tzinfo is not None and trains[0]["heure"].hour == 8   # heure de Paris

    def test_liste_bornee(self):
        incidents = [_incident(navitia_id=str(i), duree_minutes=5 + i) for i in range(15)]
        assert len(archives.trains_les_plus_couteux(incidents, NOW, SMIC)) == archives.NB_TRAINS

    def test_train_sans_cout_ecarte(self):
        assert archives.trains_les_plus_couteux([_incident(duree_minutes=0)], NOW, SMIC) == []

    def test_perturbations_de_la_ligne_sans_doublon(self):
        declarees = [
            _incident(source="disruption", type_incident="SIGNIFICANT_DELAYS", cause="Panne de signalisation",
                      lignes_impactees=["RER_A", "RER_B"]),
            _incident(source="disruption", type_incident="SIGNIFICANT_DELAYS", cause="Panne de signalisation",
                      lignes_impactees=["RER_B"], heure_debut=NOW),
            _incident(source="disruption", type_incident="NO_SERVICE", cause="Accident de personne", line_id="RER_D"),
        ]
        assert [p["resume"] for p in archives.perturbations_declarees(declarees, "RER_B")] == ["Panne de signalisation"]
        assert archives.perturbations_declarees(declarees, "RER_C") == []

    def test_message_long_coupe(self):
        inc = _incident(source="disruption", cause="mot " * 200)
        resume = archives.perturbations_declarees([inc], "RER_A")[0]["resume"]
        assert len(resume) <= archives.LONGUEUR_RESUME + 1 and resume.endswith("…")


class TestPageJour:
    def _page(self, line_id="RER_B", jour=J2, detail="defaut"):
        return archives.rendre_jour(_gabarit(), line_id, jour, _hist(), _detail() if detail == "defaut" else detail)

    def test_en_tete(self):
        html = self._page()
        titre = re.search(r"<title>(.*?)</title>", html).group(1)
        assert titre == "Retards RER B du mercredi 11 novembre 2026 : 40 000 € — IDF-RETARD"
        assert f'<link rel="canonical" href="{SITE}/rer-b/2026-11-11">' in html
        assert f"{SITE}/share/rer-b/2026-11-11.png?format=og" in html
        assert len(re.findall(r"<h1[ >]", html)) == 1
        assert "noindex" not in html and "<!--SEO" not in html

    def test_phrase_rang_et_reseau(self):
        html = self._page()
        assert "du RER B ont coûté <strong>40 000 €</strong>" in html
        assert "la ligne la plus touchée du réseau ce jour-là" in html
        assert "la journée a coûté 42 000 €" in html
        assert "3<sup>e</sup> ligne la plus touchée des 13 lignes suivies" in self._page(jour=J3)

    def test_trains_et_perturbations(self):
        html = self._page()
        assert "8 h 42" in html and "Gare du Nord → Aéroport CDG 2" in html and "25 min" in html
        assert "1 846 €" in html and "Supprimé" in html

    def test_texte_de_l_operateur_echappe(self):
        html = self._page()
        assert "<script>alert" not in html and "&lt;script&gt;alert(1)" in html
        assert "Massy &lt;Palaiseau&gt;" in html

    def test_veille_et_lendemain(self):
        html = self._page()
        assert 'href="/rer-b/2026-11-10" rel="prev"' in html
        assert 'href="/rer-b/2026-11-12" rel="next"' in html
        dernier = self._page(jour=J3)
        assert 'rel="next"' not in dernier and '<a href="/rer-b">Aujourd\'hui →</a>' in dernier
        assert 'rel="prev"' not in self._page(jour=J1)

    def test_sans_detail_la_page_garde_ses_totaux(self):
        html = self._page(detail=None)
        assert "40 000 €" in html and "<table>" not in html

    def test_jour_sans_cout(self):
        html = self._page(line_id="TRANSILIEN_H", detail={"trains": [], "perturbations": []})
        assert "aucun coût n'a été mesuré" in html and "de la ligne H" in html
        assert "ligne la plus touchée" not in html
        assert "<strong>0</strong> train retardé<" in html


class TestPageHistorique:
    def test_total_egal_a_la_somme_des_jours(self):
        html = archives.rendre_historique(_gabarit(), "RER_B", _hist())
        assert "ont coûté <strong>44 000 €</strong> aux voyageurs sur 3 jours" in html
        assert "Du 10 novembre 2026 au 12 novembre 2026" in html
        assert f'<link rel="canonical" href="{SITE}/rer-b/historique">' in html
        assert len(re.findall(r"<h1[ >]", html)) == 1 and "noindex" not in html

    def test_un_lien_par_jour_et_pire_journee(self):
        html = archives.rendre_historique(_gabarit(), "RER_B", _hist())
        for j in (J1, J2, J3):
            assert f'href="/rer-b/{j.isoformat()}"' in html
        assert 'Pire journée : le <a href="/rer-b/2026-11-11">mercredi 11 novembre 2026</a>' in html
        assert 'href="/rer-a/historique"' in html and 'href="/rer-b/historique"' not in html

    def test_ligne_sans_jour(self):
        html = archives.rendre_historique(_gabarit(), "TRANSILIEN_U", _hist())
        assert "Aucune journée terminée" in html and "<table>" not in html


class TestReponses:
    async def test_jour_connu(self, base):
        code, html = await archives.reponse_jour(_gabarit(), "RER_B", "2026-11-11")
        assert code == 200 and "40 000 €" in html

    @pytest.mark.parametrize("jour", ["abc", "2026-13-01", "20261111", "2026-11-1", "2026-11-13", "2026-09-01"])
    async def test_jour_inconnu(self, base, jour):
        assert (await archives.reponse_jour(_gabarit(), "RER_B", jour))[0] == 404

    async def test_ligne_sans_donnee_ce_jour(self, base):
        assert (await archives.reponse_jour(_gabarit(), "TRANSILIEN_H", "2026-11-10"))[0] == 404

    async def test_journee_en_cours_renvoie_a_la_page_de_la_ligne(self, base):
        aujourdhui = journee_de(datetime.now(PARIS_TZ)).isoformat()
        assert await archives.reponse_jour(_gabarit(), "RER_B", aujourdhui) == (302, "/rer-b")

    async def test_base_en_panne_503_jamais_404(self, monkeypatch):
        """Un 404 ferait retirer la page des moteurs ; un 503 leur dit de revenir."""
        async def panne():
            return None
        monkeypatch.setattr(archives, "historique", panne)
        assert (await archives.reponse_jour(_gabarit(), "RER_B", "2026-11-11"))[0] == 503
        assert (await archives.reponse_historique(_gabarit(), "RER_B"))[0] == 503

    async def test_historique(self, base):
        code, html = await archives.reponse_historique(_gabarit(), "RER_B")
        assert code == 200 and "44 000 €" in html


class TestGabaritEtRoutes:
    def test_gabarit(self):
        g = _gabarit()
        assert seo.MARQUEUR_HEAD[0] in g and seo.MARQUEUR_HEAD[1] in g
        assert g.count(archives.MARQUEUR_CORPS) == 1
        assert 'content="noindex"' in g   # /archive.html servi tel quel reste hors index

    def test_routes_par_ligne(self):
        chemins = [r.path for r in main.app.routes]
        for slug in LINE_SLUGS.values():
            assert f"/{slug}/historique" in chemins and f"/{slug}/{{jour}}" in chemins
            # « historique » avant « {jour} », qui sinon l'attraperait
            assert chemins.index(f"/{slug}/historique") < chemins.index(f"/{slug}/{{jour}}")
        assert main.app.routes[-1].name == "frontend"

    async def test_sitemap_avec_les_archives(self, base):
        xml = (await main.sitemap_xml()).body.decode("utf-8")
        assert f"<loc>{SITE}/rer-b/2026-11-11</loc>" in xml
        assert f"<loc>{SITE}/rer-b/historique</loc>" in xml
        assert len(re.findall(r"<loc>", xml)) == 17 + 13 + 8

    def test_reponses_http(self):
        assert main._reponse_archive(200, "<p>x</p>").headers["cache-control"] == "public, max-age=3600"
        assert main._reponse_archive(302, "/rer-b").headers["location"] == "/rer-b"
        indispo = main._reponse_archive(503, "x")
        assert indispo.status_code == 503 and indispo.headers["retry-after"] == "300"
        assert main._reponse_archive(404, "x").status_code == 404

    def test_page_de_ligne_mene_a_l_historique(self):
        assert 'href="/rer-b/historique"' in seo.resume_ligne("RER_B", None)

    def test_debut_des_donnees_fiables_borne_l_historique(self):
        """historique() ne lit rien avant cette date : les jours d'avant n'ont pas de page."""
        assert get_settings().debut_donnees_fiables == date(2026, 9, 16)
