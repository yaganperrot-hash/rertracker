"""Référencement : robots.txt, sitemap, llms.txt, balises des pages et texte écrit par le serveur. Sans base."""
import re
from datetime import date
from pathlib import Path

import pytest

from backend import main, seo
from backend.config import LINE_SLUGS, get_settings

FRONTEND = Path(__file__).parent.parent / "frontend"
SITE = "https://idf-retard.fr"
JOUR = date(2026, 11, 14)  # un samedi

PAGES_STATIQUES = {"/": "index.html", "/temps-reel": "temps-reel.html", "/statistiques": "statistiques.html",
                   "/methode.html": "methode.html"}
PAGES_INTERNES = ["carte.html", "carousel.html", "publications.html", "mon-trajet.html", "alerte.html"]


def _lire(nom: str) -> str:
    return (FRONTEND / nom).read_text(encoding="utf-8")


def _chiffres(**lignes) -> dict:
    lignes = lignes or {"RER_B": {"minutes": 60_000, "cout": 12_310}, "RER_A": {"minutes": 30_000, "cout": 6_155}}
    return {"jour": JOUR, "smic": 12.31, "heure_debut": 6, "lignes": lignes,
            "minutes": sum(l["minutes"] for l in lignes.values()), "cout": sum(l["cout"] for l in lignes.values())}


@pytest.fixture
def chiffres(monkeypatch):
    """Remplace la lecture en base par des chiffres fixes."""
    valeur = _chiffres()

    async def faux():
        return valeur
    monkeypatch.setattr(seo, "chiffres_du_jour", faux)
    return valeur


class TestRobots:
    def test_adresse_du_site_par_defaut(self):
        assert get_settings().site_url == SITE

    def test_sitemap_declare(self):
        assert f"Sitemap: {SITE}/sitemap.xml" in seo.robots_txt()

    def test_robots_ia_dans_le_groupe_ouvert(self):
        txt = seo.robots_txt()
        for robot in ("GPTBot", "OAI-SearchBot", "ClaudeBot", "PerplexityBot", "Google-Extended"):
            assert f"User-agent: {robot}" in txt
        # Un seul groupe : les robots nommés héritent des mêmes règles que « * »
        assert txt.count("Disallow:") == len(seo.CHEMINS_INTERDITS)

    def test_api_et_donnees_explorables(self):
        """Google charge /api/ et /data/ pour afficher les pages : les interdire les rendrait vides."""
        interdits = re.findall(r"Disallow: (\S+)", seo.robots_txt())
        assert "/api/admin/" in interdits
        assert not any(c in ("/", "/api/", "/api", "/data/", "/share/") for c in interdits)


class TestSitemap:
    def test_toutes_les_pages_publiques(self):
        xml = seo.sitemap_xml(JOUR)
        urls = re.findall(r"<loc>(.*?)</loc>", xml)
        attendues = [SITE + c for c in PAGES_STATIQUES] + [f"{SITE}/{s}" for s in LINE_SLUGS.values()]
        assert sorted(urls) == sorted(attendues)
        assert len(urls) == 4 + 13

    def test_pages_internes_absentes(self):
        xml = seo.sitemap_xml(JOUR)
        for nom in ("carte", "carousel", "publications", "mon-trajet", "alerte", "/api/", "/share/"):
            assert nom not in xml

    def test_date_du_jour(self):
        assert "<lastmod>2026-11-14</lastmod>" in seo.sitemap_xml(JOUR)

    def test_chaque_page_du_sitemap_est_servie(self):
        chemins = {r.path for r in main.app.routes}
        for chemin in seo.urls_sitemap():
            assert chemin in chemins or (FRONTEND / chemin.lstrip("/")).is_file(), chemin


class TestLlms:
    def test_liens_vers_les_pages_et_les_lignes(self):
        txt = seo.llms_txt()
        assert txt.startswith("# IDF-RETARD")
        for slug in LINE_SLUGS.values():
            assert f"({SITE}/{slug})" in txt
        assert f"({SITE}/methode.html)" in txt

    def test_chiffres_lus_dans_la_config(self):
        s = get_settings()
        txt = seo.llms_txt()
        assert f"{s.smic_horaire:.2f}".replace(".", ",") in txt
        assert "16 septembre 2026" in txt


class TestNoms:
    def test_rer_et_transilien(self):
        assert seo.nom_ligne("RER_B") == "RER B"
        assert seo.nom_ligne("TRANSILIEN_H") == "ligne H"
        assert seo.de_la_ligne("RER_B") == "du RER B"
        assert seo.de_la_ligne("TRANSILIEN_H") == "de la ligne H"

    def test_date_longue(self):
        assert seo.date_longue(JOUR) == "samedi 14 novembre 2026"
        assert seo.date_longue(date(2026, 11, 1)) == "dimanche 1er novembre 2026"

    def test_un_titre_par_ligne(self):
        titres = {seo.titre_ligne(lid) for lid in LINE_SLUGS}
        assert len(titres) == len(LINE_SLUGS) == 13


class TestPagesStatiques:
    @pytest.mark.parametrize("chemin,fichier", PAGES_STATIQUES.items())
    def test_balises(self, chemin, fichier):
        html = _lire(fichier)
        assert len(re.findall(r"<title[ >]", html)) == 1
        assert len(re.findall(r'<meta name="description"', html)) == 1
        assert f'<link rel="canonical" href="{SITE}{chemin}">' in html
        assert f'<meta property="og:image" content="{SITE}/og.png">' in html
        assert len(re.findall(r"<h1[ >]", html)) == 1
        assert 'content="noindex"' not in html

    def test_descriptions_toutes_differentes(self):
        descs = [re.search(r'<meta name="description" content="(.*?)">', _lire(f)).group(1)
                 for f in PAGES_STATIQUES.values()]
        assert len(set(descs)) == len(descs)

    @pytest.mark.parametrize("fichier", PAGES_INTERNES)
    def test_pages_internes_hors_index(self, fichier):
        assert '<meta name="robots" content="noindex">' in _lire(fichier)

    def test_images_presentes(self):
        assert (FRONTEND / "og.png").is_file()
        assert (FRONTEND / "favicon.svg").is_file()

    def test_json_ld_valide(self):
        import json
        for fichier, type_ in (("index.html", "WebSite"), ("statistiques.html", "Dataset")):
            bloc = re.search(r'<script type="application/ld\+json">(.*?)</script>', _lire(fichier), re.S).group(1)
            assert json.loads(bloc)["@type"] == type_


class TestGabarits:
    def test_marqueurs_presents(self):
        """Sans ses marqueurs, une page serait servie sans titre propre ni phrase chiffrée, en silence."""
        ligne = _lire("ligne.html")
        assert seo.MARQUEUR_HEAD[0] in ligne and seo.MARQUEUR_HEAD[1] in ligne
        assert ligne.count(seo.MARQUEUR_RESUME) == 1
        assert _lire("index.html").count(seo.MARQUEUR_RESUME) == 1

    def test_gabarit_de_ligne_brut_hors_index(self):
        """/ligne.html, servi tel quel, ne doit pas concurrencer les pages de ligne."""
        assert 'content="noindex"' in _lire("ligne.html")

    def test_le_javascript_ne_reecrit_plus_le_titre(self):
        assert "getElementById('page-title').textContent" not in _lire("ligne.html")

    def test_rendre_sans_marqueur_laisse_la_page_intacte(self):
        assert seo.rendre("<p>x</p>", head="<title>t</title>", resume="r") == "<p>x</p>"


class TestPageLigne:
    @pytest.mark.parametrize("line_id,slug", LINE_SLUGS.items())
    async def test_en_tete_propre_a_la_ligne(self, chiffres, line_id, slug):
        html = await seo.page_ligne(_lire("ligne.html"), line_id)
        assert len(re.findall(r"<title[ >]", html)) == 1
        assert seo.nom_ligne(line_id) in re.search(r"<title[^>]*>(.*?)</title>", html).group(1)
        assert f'<link rel="canonical" href="{SITE}/{slug}">' in html
        assert f"{SITE}/share/{slug}/today.png?format=og" in html
        assert len(re.findall(r"<h1[ >]", html)) == 1
        assert "noindex" not in html
        assert "<!--SEO" not in html and "<!--/SEO" not in html

    async def test_phrase_chiffree(self, chiffres):
        html = await seo.page_ligne(_lire("ligne.html"), "RER_B")
        assert "Samedi 14 novembre 2026, depuis 6 h" in html
        assert "du RER B ont coûté <strong>12 310 €</strong>" in html
        assert "12,31 €/h" in html
        assert 'href="/rer-a"' in html and 'href="/rer-b"' not in html.split('class="resume-lignes"')[1].split("</nav>")[0]

    async def test_ligne_sans_cout(self, chiffres):
        html = await seo.page_ligne(_lire("ligne.html"), "TRANSILIEN_U")
        assert "aucun coût n'a encore été mesuré" in html
        assert "de la ligne U" in html

    async def test_base_en_panne_page_servie_quand_meme(self, monkeypatch):
        async def panne():
            return None
        monkeypatch.setattr(seo, "chiffres_du_jour", panne)
        html = await seo.page_ligne(_lire("ligne.html"), "RER_B")
        assert "Retards RER B aujourd'hui" in html
        assert "€</strong>" not in html

    async def test_erreur_inattendue_gabarit_servi(self, monkeypatch):
        async def casse():
            raise RuntimeError("boum")
        monkeypatch.setattr(seo, "chiffres_du_jour", casse)
        gabarit = _lire("ligne.html")
        assert await seo.page_ligne(gabarit, "RER_B") == gabarit


class TestPageAccueil:
    async def test_total_et_ligne_la_plus_touchee(self, chiffres):
        html = await seo.page_accueil(_lire("index.html"))
        assert "ont coûté <strong>18 465 €</strong>" in html
        assert "Ligne la plus touchée : RER B (12 310 €)" in html
        assert len(re.findall(r"<h1[ >]", html)) == 1
        assert "<!--SEO" not in html

    async def test_lien_vers_chaque_ligne(self, chiffres):
        html = await seo.page_accueil(_lire("index.html"))
        for slug in LINE_SLUGS.values():
            assert f'<a href="/{slug}">' in html

    async def test_total_egal_a_la_somme_des_lignes(self, chiffres):
        assert chiffres["cout"] == sum(l["cout"] for l in chiffres["lignes"].values())

    async def test_base_en_panne(self, monkeypatch):
        async def panne():
            return None
        monkeypatch.setattr(seo, "chiffres_du_jour", panne)
        html = await seo.page_accueil(_lire("index.html"))
        assert "IDF-RETARD mesure en temps réel" in html
        assert "€</strong>" not in html


class TestRoutes:
    async def test_robots_sitemap_llms(self):
        assert (await main.robots_txt()).body.decode("utf-8") == seo.robots_txt()
        assert b"<urlset" in (await main.sitemap_xml()).body
        assert (await main.llms_txt()).body.decode("utf-8") == seo.llms_txt()

    async def test_accueil(self, chiffres):
        rep = await main.page_accueil()
        assert rep.status_code == 200
        assert "18 465 €" in rep.body.decode("utf-8")

    def test_routes_declarees_avant_le_montage_statique(self):
        chemins = [r.path for r in main.app.routes]
        for chemin in ("/", "/robots.txt", "/sitemap.xml", "/llms.txt", "/rer-b", "/ligne-u"):
            assert chemin in chemins
        # Le montage « / » (fichiers statiques) attrape tout : il doit rester le dernier
        assert chemins.index("/robots.txt") < len(chemins) - 1
        assert main.app.routes[-1].name == "frontend"

    def test_head_accepte(self):
        """Les robots vérifient une page par HEAD avant de la lire."""
        for r in main.app.routes:
            if r.path in ("/", "/robots.txt", "/sitemap.xml", "/rer-b", "/statistiques", "/temps-reel"):
                assert "HEAD" in r.methods, r.path
