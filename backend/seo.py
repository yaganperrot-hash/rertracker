"""Référencement : robots.txt, sitemap.xml, llms.txt, et texte écrit dans le HTML par le serveur.

Les chiffres des pages sont chargés en JavaScript : un moteur de recherche ou un robot d'IA qui ne l'exécute pas
ne voyait qu'une page vide, et les 13 pages de ligne portaient toutes le même titre. Ce module écrit dans le HTML
servi le titre, la description et une phrase datée reprenant les chiffres du jour (lus en base, lecture seule,
mêmes fonctions que l'accueil). Rien ici ne doit empêcher une page de s'afficher : sans chiffres, le texte reste
générique.
"""
import logging
import time
from datetime import date, datetime
from html import escape
from xml.sax.saxutils import escape as xml_escape

from backend.bot import _fmt, _fmt_duree
from backend.config import LINE_SLUGS, get_settings
from backend.share import LINE_COLORS

logger = logging.getLogger(__name__)

# Marqueurs remplacés dans les gabarits HTML (frontend/index.html, frontend/ligne.html)
MARQUEUR_HEAD = ("<!--SEO:HEAD-->", "<!--/SEO:HEAD-->")
MARQUEUR_RESUME = "<!--SEO:RESUME-->"

# Pages proposées aux moteurs, hors pages de ligne. Les pages internes (carte, carrousel, publications, alerte,
# mon-trajet) portent une balise noindex et n'y figurent pas.
PAGES_PUBLIQUES = ["/", "/temps-reel", "/statistiques", "/methode.html"]

# Robots de recherche et d'assistants IA nommés explicitement : certains n'explorent un site que s'ils y sont cités
ROBOTS_IA = [
    "GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "Claude-User",
    "PerplexityBot", "Perplexity-User", "Google-Extended", "Applebot-Extended", "MistralAI-User", "CCBot",
]

# Jamais utiles à un moteur. /api/ et /data/ restent explorables : Google en a besoin pour afficher les pages.
CHEMINS_INTERDITS = ["/api/admin/", "/docs", "/redoc", "/openapi.json"]

_JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_MOIS = ["", "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
         "novembre", "décembre"]

CACHE_SECONDES = 300  # un relevé toutes les 5 min : inutile de relire la base plus souvent
_cache: dict = {"instant": 0.0, "valeur": None}


def site() -> str:
    return get_settings().site_url.rstrip("/")


def nom_ligne(line_id: str) -> str:
    """« RER B », « ligne H » : le nom tel qu'il est cherché."""
    court = LINE_COLORS[line_id]["short"]
    return f"RER {court}" if line_id.startswith("RER_") else f"ligne {court}"


def nom_ligne_long(line_id: str) -> str:
    """« RER B », « ligne H (Transilien) »."""
    nom = nom_ligne(line_id)
    return nom if line_id.startswith("RER_") else f"{nom} (Transilien)"


def de_la_ligne(line_id: str) -> str:
    """« du RER B », « de la ligne H »."""
    return f"du {nom_ligne(line_id)}" if line_id.startswith("RER_") else f"de la {nom_ligne(line_id)}"


def date_courte(jour: date) -> str:
    """« 14 novembre 2026 »."""
    premier = "1er" if jour.day == 1 else str(jour.day)
    return f"{premier} {_MOIS[jour.month]} {jour.year}"


def date_longue(jour: date) -> str:
    """« samedi 14 novembre 2026 »."""
    return f"{_JOURS[jour.weekday()]} {date_courte(jour)}"


def _smic(smic: float) -> str:
    return f"{smic:.2f}".replace(".", ",")


# ── Fichiers pour les robots ──

def robots_txt() -> str:
    lignes = ["# IDF-RETARD : exploration ouverte à tous les moteurs et assistants IA", "User-agent: *"]
    lignes += [f"User-agent: {r}" for r in ROBOTS_IA]
    lignes += [f"Disallow: {c}" for c in CHEMINS_INTERDITS]
    lignes += ["", f"Sitemap: {site()}/sitemap.xml", ""]
    return "\n".join(lignes)


def urls_sitemap() -> list[str]:
    return PAGES_PUBLIQUES + [f"/{slug}" for slug in LINE_SLUGS.values()]


def sitemap_xml(jour: date, archives: list[str] | None = None) -> str:
    """Toutes les pages publiques, puis les pages d'archive (`archives.chemins_archives`). `lastmod` = jour des
    chiffres pour les pages vivantes ; rien pour la Méthode ni pour une journée terminée, qui ne changent plus."""
    entrees = []
    for chemin in urls_sitemap():
        lastmod = "" if chemin == "/methode.html" else f"<lastmod>{jour.isoformat()}</lastmod>"
        entrees.append(f"  <url><loc>{xml_escape(site() + chemin)}</loc>{lastmod}</url>")
    for chemin in archives or []:
        lastmod = f"<lastmod>{jour.isoformat()}</lastmod>" if chemin.endswith("/historique") else ""
        entrees.append(f"  <url><loc>{xml_escape(site() + chemin)}</loc>{lastmod}</url>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(entrees) + "\n</urlset>\n")


def llms_txt() -> str:
    """Résumé du site pour les assistants IA (convention llms.txt)."""
    s = get_settings()
    lignes = [
        "# IDF-RETARD",
        "",
        "> Tableau de bord indépendant qui mesure en temps réel ce que les retards et suppressions de trains "
        "coûtent aux voyageurs des RER et Transiliens d'Île-de-France, en minutes perdues et en euros.",
        "",
        "- Lignes couvertes : RER A, B, C, D, E et Transilien H, J, K, L, N, P, R, U.",
        "- Source : flux temps réel PRIM d'Île-de-France Mobilités, relevé toutes les "
        f"{s.polling_interval_minutes} minutes de {s.collecte_heure_debut} h à minuit (heure de Paris).",
        "- Unité : minutes-voyageurs perdues (retard de chaque train × voyageurs à bord), converties en euros "
        f"au SMIC horaire brut ({_smic(s.smic_horaire)} €/h).",
        f"- Une journée est comptée à partir de {s.collecte_heure_debut} h. Données fiables depuis le "
        f"{date_courte(s.debut_donnees_fiables)}.",
        "- Les chiffres sont des estimations ; la méthode et ses limites sont publiées.",
        "",
        "## Pages",
        "",
        f"- [Aujourd'hui]({site()}/) : coût des retards du jour, tout le réseau",
        f"- [Temps réel]({site()}/temps-reel) : trains retardés et supprimés en ce moment",
        f"- [Statistiques]({site()}/statistiques) : bilans par semaine, mois et année, ligne par ligne",
        f"- [Méthode]({site()}/methode.html) : sources, calcul du coût, périmètre et limites",
        "",
        "## Lignes",
        "",
    ]
    lignes += [f"- [Retards {nom_ligne_long(lid)}]({site()}/{slug}) — "
               f"[historique jour par jour]({site()}/{slug}/historique)" for lid, slug in LINE_SLUGS.items()]
    lignes += [
        "",
        "Chaque journée terminée a sa page : `/{ligne}/{AAAA-MM-JJ}`, par exemple "
        f"{site()}/rer-b/{get_settings().debut_donnees_fiables.isoformat()} (coût, trains les plus coûteux, "
        "perturbations déclarées).",
    ]
    lignes += [
        "",
        "## Données",
        "",
        f"- [Totaux du jour (JSON)]({site()}/api/stats/today)",
        f"- [Détail du jour par ligne (JSON)]({site()}/api/stats/today/lines)",
        "",
    ]
    return "\n".join(lignes)


# ── Chiffres du jour ──

async def chiffres_du_jour() -> dict | None:
    """Coût et minutes du jour, réseau et par ligne, tels que l'accueil les affiche. None si la base ne répond pas :
    la page est alors servie avec son texte générique."""
    if _cache["valeur"] is not None and time.monotonic() - _cache["instant"] < CACHE_SECONDES:
        return _cache["valeur"]
    try:
        from sqlalchemy import select
        from backend.database import AsyncSessionLocal
        from backend.metrics import cout_eur, get_today_stats
        from backend.models import DailyMetric

        async with AsyncSessionLocal() as db:
            stats = await get_today_stats(db)
            jour = date.fromisoformat(stats["date"])
            rows = (await db.execute(select(DailyMetric).where(DailyMetric.date == jour))).scalars().all()
        smic = stats["smic_horaire"]
        valeur = {
            "jour": jour,
            "smic": smic,
            "heure_debut": stats["heure_debut_journee"],
            "minutes": stats["total_minutes_voyageurs"],
            "cout": stats["cout_eur"],
            "lignes": {r.line_id: {"minutes": r.minutes_voyageurs, "cout": cout_eur(r.minutes_voyageurs, smic)}
                       for r in rows if r.line_id in LINE_SLUGS},
        }
    except Exception:
        logger.exception("Chiffres du jour illisibles : pages servies sans phrase chiffrée")
        return None
    _cache.update(instant=time.monotonic(), valeur=valeur)
    return valeur


# ── Texte écrit dans les pages ──

def _phrase(chiffres: dict, sujet: str, minutes: int, cout: int) -> str:
    quand = f"{date_longue(chiffres['jour']).capitalize()}, depuis {chiffres['heure_debut']} h"
    if cout <= 0:
        return f"{quand}, aucun coût n'a encore été mesuré pour les retards et suppressions de trains {sujet}."
    return (f"{quand}, les retards et suppressions de trains {sujet} ont coûté <strong>{_fmt(cout)} €</strong> "
            f"aux voyageurs, soit {_fmt_duree(minutes)} de temps perdu, valorisé au SMIC horaire brut "
            f"({_smic(chiffres['smic'])} €/h).")


def _liens_lignes(sauf: str | None = None) -> str:
    liens = [f'<a href="/{slug}">{escape(nom_ligne(lid).replace("ligne", "Ligne"))}</a>'
             for lid, slug in LINE_SLUGS.items() if lid != sauf]
    return '<nav class="resume-lignes" aria-label="Retards par ligne">' + " · ".join(liens) + "</nav>"


_SUITE = ('Chiffres mesurés à partir du flux temps réel d\'Île-de-France Mobilités, mis à jour toutes les 5 minutes. '
          '<a href="/methode.html">Voir la méthode</a>.')


def resume_accueil(chiffres: dict | None) -> str:
    if chiffres is None:
        phrase = ("IDF-RETARD mesure en temps réel ce que les retards et suppressions de trains coûtent aux "
                  "voyageurs des RER et Transiliens d'Île-de-France, en minutes perdues et en euros.")
    else:
        phrase = _phrase(chiffres, "sur les RER et Transiliens d'Île-de-France", chiffres["minutes"],
                         chiffres["cout"])
        pire = max(chiffres["lignes"].items(), key=lambda kv: kv[1]["cout"], default=None)
        if pire and pire[1]["cout"] > 0:
            phrase += (f" Ligne la plus touchée : {escape(nom_ligne(pire[0]))} "
                       f"({_fmt(pire[1]['cout'])} €).")
    return ('<section class="resume">\n'
            '  <h2>Retards RER et Transilien, ligne par ligne</h2>\n'
            f'  <p>{phrase} {_SUITE}</p>\n'
            f'  {_liens_lignes()}\n'
            '</section>')


def resume_ligne(line_id: str, chiffres: dict | None) -> str:
    sujet = de_la_ligne(line_id)
    if chiffres is None:
        phrase = (f"IDF-RETARD mesure en temps réel ce que les retards et suppressions de trains {sujet} "
                  "coûtent aux voyageurs, en minutes perdues et en euros.")
    else:
        ligne = chiffres["lignes"].get(line_id, {"minutes": 0, "cout": 0})
        phrase = _phrase(chiffres, sujet, ligne["minutes"], ligne["cout"])
    archives = (f'<a href="/{LINE_SLUGS[line_id]}/historique">Historique des retards {escape(sujet)}, '
                'jour par jour</a>.')
    return ('<section class="resume">\n'
            f'  <h1>Retards {escape(nom_ligne_long(line_id))} aujourd\'hui</h1>\n'
            f'  <p>{phrase} {_SUITE} {archives}</p>\n'
            f'  {_liens_lignes(sauf=line_id)}\n'
            '</section>')


def titre_ligne(line_id: str) -> str:
    return f"Retards {nom_ligne_long(line_id)} aujourd'hui : coût en temps réel — IDF-RETARD"


def description_ligne(line_id: str) -> str:
    return (f"Combien les retards et suppressions de trains {de_la_ligne(line_id)} coûtent aux voyageurs "
            "aujourd'hui : euros et minutes perdues, mesurés en temps réel, et incidents en cours.")


def head_ligne(line_id: str) -> str:
    """Balises d'en-tête propres à une ligne (les id sont gardés pour le JavaScript existant)."""
    slug = LINE_SLUGS[line_id]
    titre, desc = escape(titre_ligne(line_id)), escape(description_ligne(line_id))
    url = f"{site()}/{slug}"
    image = f"{site()}/share/{slug}/today.png?format=og"
    return "\n  ".join([
        f'<title id="page-title">{titre}</title>',
        f'<meta name="description" id="page-desc" content="{desc}">',
        f'<link rel="canonical" href="{url}">',
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="IDF-RETARD">',
        '<meta property="og:locale" content="fr_FR">',
        f'<meta property="og:title" content="{titre}">',
        f'<meta property="og:description" content="{desc}">',
        f'<meta property="og:url" content="{url}">',
        f'<meta property="og:image" content="{image}">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        '<meta name="twitter:card" content="summary_large_image">',
        '<meta name="twitter:site" content="@idfretard">',
    ])


def rendre(gabarit: str, head: str | None = None, resume: str | None = None) -> str:
    """Remplace les marqueurs du gabarit. Un marqueur absent laisse la page intacte."""
    html = gabarit
    debut, fin = MARQUEUR_HEAD
    if head is not None and debut in html and fin in html:
        i, j = html.index(debut), html.index(fin) + len(fin)
        html = html[:i] + head + html[j:]
    if resume is not None:
        html = html.replace(MARQUEUR_RESUME, resume, 1)
    return html


async def page_accueil(gabarit: str) -> str:
    try:
        return rendre(gabarit, resume=resume_accueil(await chiffres_du_jour()))
    except Exception:
        logger.exception("Accueil : texte de référencement non écrit")
        return gabarit


async def page_ligne(gabarit: str, line_id: str) -> str:
    try:
        return rendre(gabarit, head=head_ligne(line_id), resume=resume_ligne(line_id, await chiffres_du_jour()))
    except Exception:
        logger.exception("Page %s : texte de référencement non écrit", line_id)
        return gabarit
