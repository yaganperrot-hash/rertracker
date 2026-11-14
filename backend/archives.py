"""Pages d'archive : une page par ligne et par jour passé (/rer-b/2026-11-12) et un historique par ligne
(/rer-b/historique), entièrement écrits par le serveur.

Chaque journée terminée devient une page fixe, lisible sans JavaScript, qui répond à « que s'est-il passé sur le
RER B le 12 novembre ». Lecture seule : les totaux viennent de daily_metrics, le coût de chaque train de la même
fonction que l'API (`api._impact`). Seuls les jours terminés, à partir du début des données fiables, ont une page ;
la journée en cours reste sur la page de la ligne.
"""
import logging
import time
from datetime import date, datetime, timedelta, timezone
from html import escape

from backend import seo
from backend.bot import _fmt, _fmt_duree
from backend.config import LINE_SLUGS, get_settings
from backend.share import LINE_COLORS

logger = logging.getLogger(__name__)

MARQUEUR_CORPS = "<!--SEO:CORPS-->"
NB_TRAINS = 10          # trains les plus coûteux listés sur une page de jour
NB_PERTURBATIONS = 8    # perturbations déclarées listées
LONGUEUR_RESUME = 220   # un message PRIM peut faire plusieurs paragraphes

CACHE_HISTORIQUE_S = 600   # les bilans sont recalculés toutes les 10 min
CACHE_DETAIL_S = 3600      # une journée terminée ne change plus (sauf recalcul historique)
CACHE_DETAIL_MAX = 400     # pages de jour gardées en mémoire
_cache_hist: dict = {"instant": 0.0, "valeur": None}
_cache_detail: dict = {}


# ── Lecture en base ──

async def historique() -> dict | None:
    """{jour: {line_id: {minutes, cout, retards, supprimes, perturbations}}} pour chaque jour terminé depuis le
    début des données fiables. None si la base ne répond pas."""
    if _cache_hist["valeur"] is not None and time.monotonic() - _cache_hist["instant"] < CACHE_HISTORIQUE_S:
        return _cache_hist["valeur"]
    try:
        from sqlalchemy import select
        from backend.database import AsyncSessionLocal
        from backend.metrics import PARIS_TZ, cout_eur, journee_de
        from backend.models import DailyMetric

        s = get_settings()
        aujourdhui = journee_de(datetime.now(PARIS_TZ))
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(select(DailyMetric).where(
                DailyMetric.date >= s.debut_donnees_fiables, DailyMetric.date < aujourdhui))).scalars().all()
        valeur: dict = {}
        for r in rows:
            if r.line_id not in LINE_SLUGS:
                continue
            valeur.setdefault(r.date, {})[r.line_id] = {
                "minutes": r.minutes_voyageurs,
                "cout": cout_eur(r.minutes_voyageurs, s.smic_horaire),
                "retards": r.nb_rt_delays or 0,
                "supprimes": r.nb_cancelled or 0,
                "perturbations": r.nb_disruptions or 0,
            }
    except Exception:
        logger.exception("Historique illisible : pages d'archive indisponibles")
        return None
    _cache_hist.update(instant=time.monotonic(), valeur=valeur)
    return valeur


def trains_les_plus_couteux(incidents, now_utc: datetime, smic: float, n: int = NB_TRAINS) -> list[dict]:
    """Les n trains retardés ou supprimés qui ont coûté le plus, calculés comme les métriques du jour."""
    from backend.api import _impact
    from backend.metrics import PARIS_TZ

    trains = []
    for inc in incidents:
        duree, mv, cout = _impact(inc, now_utc, smic)
        if not mv or not cout:
            continue
        quand = inc.heure_theorique or inc.heure_debut
        trains.append({
            "heure": quand.astimezone(PARIS_TZ), "gare": inc.gare, "direction": inc.direction,
            "mission": inc.mission, "supprime": bool(inc.is_cancelled), "duree": duree,
            "minutes": mv, "cout": cout,
        })
    trains.sort(key=lambda t: (-t["minutes"], t["heure"]))
    return trains[:n]


def perturbations_declarees(incidents, line_id: str, n: int = NB_PERTURBATIONS) -> list[dict]:
    """Perturbations déclarées par l'opérateur touchant la ligne, sans doublon de message."""
    from backend.causes import categoriser_cause, resume_perturbation

    vues, resultat = set(), []
    for inc in sorted(incidents, key=lambda i: i.heure_debut):
        if line_id not in (inc.lignes_impactees or [inc.line_id]):
            continue
        resume = resume_perturbation(inc.cause)
        if not resume or resume in vues:
            continue
        vues.add(resume)
        if len(resume) > LONGUEUR_RESUME:
            resume = resume[:LONGUEUR_RESUME].rsplit(" ", 1)[0] + "…"
        resultat.append({"resume": resume, "categorie": categoriser_cause(inc.cause)})
    return resultat[:n]


async def detail_jour(line_id: str, jour: date) -> dict | None:
    """Trains les plus coûteux et perturbations déclarées d'une ligne un jour donné. None en cas d'erreur :
    la page est alors servie avec ses seuls totaux."""
    cle = (line_id, jour)
    en_cache = _cache_detail.get(cle)
    if en_cache and time.monotonic() - en_cache[0] < CACHE_DETAIL_S:
        return en_cache[1]
    try:
        from sqlalchemy import or_, select
        from backend.database import AsyncSessionLocal
        from backend.metrics import debut_journee
        from backend.models import Incident

        debut = debut_journee(jour).astimezone(timezone.utc)
        fin = debut_journee(jour + timedelta(days=1)).astimezone(timezone.utc)
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(select(Incident).where(
                Incident.heure_debut >= debut, Incident.heure_debut < fin,
                or_(Incident.line_id == line_id, Incident.source.is_distinct_from("realtime")),
            ))).scalars().all()
        # Même tri que compute_daily_metrics : supprimé, sinon temps réel, sinon perturbation déclarée
        trains, declarees = [], []
        for inc in rows:
            source = inc.source or ("realtime" if inc.type_incident == "DELAY_REALTIME" else "disruption")
            if inc.is_cancelled or source == "realtime":
                if inc.line_id == line_id:
                    trains.append(inc)
            else:
                declarees.append(inc)
        valeur = {
            "trains": trains_les_plus_couteux(trains, datetime.now(timezone.utc), get_settings().smic_horaire),
            "perturbations": perturbations_declarees(declarees, line_id),
        }
    except Exception:
        logger.exception("Détail %s du %s illisible : page servie sans la liste des trains", line_id, jour)
        return None
    if len(_cache_detail) >= CACHE_DETAIL_MAX:
        _cache_detail.clear()
    _cache_detail[cle] = (time.monotonic(), valeur)
    return valeur


# ── Lecture de l'historique ──

def jours_de(hist: dict, line_id: str) -> list[date]:
    """Jours ayant une page pour cette ligne, du plus récent au plus ancien."""
    return sorted((j for j, lignes in hist.items() if line_id in lignes), reverse=True)


def chemins_archives(hist: dict | None) -> list[str]:
    """Toutes les pages d'archive, pour le sitemap."""
    chemins = [f"/{slug}/historique" for slug in LINE_SLUGS.values()]
    for line_id, slug in LINE_SLUGS.items():
        chemins += [f"/{slug}/{j.isoformat()}" for j in jours_de(hist or {}, line_id)]
    return chemins


def rang_du_jour(hist: dict, line_id: str, jour: date) -> int:
    """Rang de la ligne ce jour-là par coût décroissant (1 = la plus touchée)."""
    lignes = hist[jour]
    return 1 + sum(1 for l in lignes.values() if l["cout"] > lignes[line_id]["cout"])


def cout_reseau(hist: dict, jour: date) -> int:
    return sum(l["cout"] for l in hist[jour].values())


# ── Rendu ──

def _pluriel(n: int, singulier: str, pluriel: str) -> str:
    return f"{_fmt(n)} {singulier if n < 2 else pluriel}"


def _head(titre: str, desc: str, chemin: str, image: str) -> str:
    titre, desc = escape(titre), escape(desc)
    url = f"{seo.site()}{chemin}"
    return "\n  ".join([
        f"<title>{titre}</title>",
        f'<meta name="description" content="{desc}">',
        f'<link rel="canonical" href="{url}">',
        '<meta property="og:type" content="article">',
        '<meta property="og:site_name" content="IDF-RETARD">',
        '<meta property="og:locale" content="fr_FR">',
        f'<meta property="og:title" content="{titre}">',
        f'<meta property="og:description" content="{desc}">',
        f'<meta property="og:url" content="{url}">',
        f'<meta property="og:image" content="{seo.site()}{image}">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        '<meta name="twitter:card" content="summary_large_image">',
        '<meta name="twitter:site" content="@idfretard">',
    ])


def _pastille(line_id: str) -> str:
    m = LINE_COLORS[line_id]
    return (f'<span class="pastille" style="background:{m["color"]};color:{m["textColor"]}">'
            f'{escape(m["short"])}</span>')


def _heure(dt: datetime) -> str:
    return f"{dt.hour} h {dt.minute:02d}"


def _habiller(gabarit: str, head: str, corps: str) -> str:
    return seo.rendre(gabarit, head=head).replace(MARQUEUR_CORPS, corps, 1)


def rendre_jour(gabarit: str, line_id: str, jour: date, hist: dict, detail: dict | None) -> str:
    slug, sujet, nom = LINE_SLUGS[line_id], seo.de_la_ligne(line_id), seo.nom_ligne_long(line_id)
    l = hist[jour][line_id]
    smic = f"{get_settings().smic_horaire:.2f}".replace(".", ",")
    quand = seo.date_longue(jour)
    compte = f"{_pluriel(l['retards'], 'train retardé', 'trains retardés')} et " \
             f"{_pluriel(l['supprimes'], 'train supprimé', 'trains supprimés')}"

    if l["cout"] > 0:
        titre = f"Retards {nom} du {quand} : {_fmt(l['cout'])} € — IDF-RETARD"
        desc = (f"Le {quand}, les retards et suppressions de trains {sujet} ont coûté {_fmt(l['cout'])} € aux "
                f"voyageurs, soit {_fmt_duree(l['minutes'])} de temps perdu : {compte}. Détail des trains et des "
                "perturbations.")
        phrase = (f"Le {quand}, les retards et suppressions de trains {sujet} ont coûté "
                  f"<strong>{_fmt(l['cout'])} €</strong> aux voyageurs, soit {_fmt_duree(l['minutes'])} de temps "
                  f"perdu, valorisé au SMIC horaire brut ({smic} €/h).")
        rang = rang_du_jour(hist, line_id, jour)
        if rang == 1:
            phrase += " C'était la ligne la plus touchée du réseau ce jour-là."
        else:
            phrase += f" C'était la {rang}<sup>e</sup> ligne la plus touchée des {len(LINE_SLUGS)} lignes suivies."
        phrase += (f" Sur l'ensemble des RER et Transiliens, la journée a coûté "
                   f"{_fmt(cout_reseau(hist, jour))} €.")
    else:
        titre = f"Retards {nom} du {quand} — IDF-RETARD"
        desc = (f"Le {quand}, aucun coût n'a été mesuré pour les retards et suppressions de trains {sujet} : "
                f"{compte}.")
        phrase = f"Le {quand}, aucun coût n'a été mesuré pour les retards et suppressions de trains {sujet}."

    corps = [
        '<header class="entete">',
        f'  <p class="fil"><a href="/">Aujourd\'hui</a> › <a href="/{slug}">{escape(seo.nom_ligne(line_id))}</a> › '
        f'<a href="/{slug}/historique">Historique</a></p>',
        f'  <h1>{_pastille(line_id)} Retards {escape(sujet)}<br>{escape(quand)}</h1>',
        f'  <p class="cout">{_fmt(l["cout"])} €</p>',
        f'  <p class="chapeau">{phrase}</p>',
        '</header>',
        '<ul class="chiffres">',
        f'  <li><strong>{_fmt(l["retards"])}</strong> {"train retardé" if l["retards"] < 2 else "trains retardés"}</li>',
        f'  <li><strong>{_fmt(l["supprimes"])}</strong> '
        f'{"train supprimé" if l["supprimes"] < 2 else "trains supprimés"}</li>',
        f'  <li><strong>{_fmt(l["perturbations"])}</strong> '
        f'{"perturbation déclarée" if l["perturbations"] < 2 else "perturbations déclarées"}</li>',
        '</ul>',
    ]

    if detail and detail["trains"]:
        corps += ['<section class="bloc">',
                  f'  <h2>Les trains qui ont coûté le plus cher</h2>',
                  '  <table>',
                  '    <thead><tr><th>Départ prévu</th><th>Train</th><th>Retard</th><th class="d">Coût</th></tr></thead>',
                  '    <tbody>']
        for t in detail["trains"]:
            trajet = escape(t["gare"] or "Gare non précisée")
            # Retard relevé au terminus : gare et direction identiques, la flèche n'apprend rien
            if t["direction"] and t["direction"] != t["gare"]:
                trajet += f" → {escape(t['direction'])}"
            if t["mission"]:
                trajet += f' <span class="mission">{escape(t["mission"])}</span>'
            retard = "Supprimé" if t["supprime"] else f"{t['duree']} min"
            corps.append(f'      <tr><td>{_heure(t["heure"])}</td><td>{trajet}</td><td>{retard}</td>'
                         f'<td class="d">{_fmt(t["cout"])} €</td></tr>')
        corps += ['    </tbody>', '  </table>',
                  '  <p class="note">Coût d\'un train : minutes perdues par ses voyageurs, valorisées au SMIC. '
                  'Pour un train supprimé, l\'attente du train suivant.</p>',
                  '</section>']

    if detail and detail["perturbations"]:
        corps += ['<section class="bloc">', '  <h2>Perturbations déclarées par l\'opérateur</h2>', '  <ul class="liste">']
        corps += [f'    <li>{escape(p["resume"])} <span class="categorie">{escape(p["categorie"])}</span></li>'
                  for p in detail["perturbations"]]
        corps += ['  </ul>', '</section>']

    jours = jours_de(hist, line_id)
    i = jours.index(jour)
    veille = jours[i + 1] if i + 1 < len(jours) else None
    lendemain = jours[i - 1] if i > 0 else None
    liens = []
    if veille:
        liens.append(f'<a href="/{slug}/{veille.isoformat()}" rel="prev">← {escape(seo.date_longue(veille))}</a>')
    liens.append(f'<a href="/{slug}/historique">Tous les jours</a>')
    if lendemain:
        liens.append(f'<a href="/{slug}/{lendemain.isoformat()}" rel="next">'
                     f'{escape(seo.date_longue(lendemain))} →</a>')
    else:
        liens.append(f'<a href="/{slug}">Aujourd\'hui →</a>')
    heure_debut = get_settings().collecte_heure_debut
    corps += [
        f'<nav class="jours" aria-label="Autres jours">{" ".join(liens)}</nav>',
        f'<p class="note pied">Journée comptée de {heure_debut} h à {heure_debut} h le lendemain. Chiffres mesurés à '
        'partir du flux temps réel d\'Île-de-France Mobilités. <a href="/methode.html">Voir la méthode</a>.</p>',
    ]
    image = f"/share/{slug}/{jour.isoformat()}.png?format=og"
    return _habiller(gabarit, _head(titre, desc, f"/{slug}/{jour.isoformat()}", image), "\n".join(corps))


def rendre_historique(gabarit: str, line_id: str, hist: dict) -> str:
    slug, sujet, nom = LINE_SLUGS[line_id], seo.de_la_ligne(line_id), seo.nom_ligne_long(line_id)
    jours = jours_de(hist, line_id)
    titre = f"Historique des retards {nom}, jour par jour — IDF-RETARD"
    if jours:
        total = sum(hist[j][line_id]["cout"] for j in jours)
        minutes = sum(hist[j][line_id]["minutes"] for j in jours)
        pire = max(jours, key=lambda j: hist[j][line_id]["cout"])
        phrase = (f"Du {seo.date_courte(jours[-1])} au {seo.date_courte(jours[0])}, les retards et suppressions de "
                  f"trains {sujet} ont coûté <strong>{_fmt(total)} €</strong> aux voyageurs sur "
                  f"{_pluriel(len(jours), 'jour', 'jours')}, soit {_fmt_duree(minutes)} de temps perdu.")
        if hist[pire][line_id]["cout"] > 0:
            phrase += (f' Pire journée : le <a href="/{slug}/{pire.isoformat()}">{escape(seo.date_longue(pire))}</a> '
                       f"({_fmt(hist[pire][line_id]['cout'])} €).")
        desc = (f"Coût des retards et suppressions de trains {sujet}, jour par jour depuis le "
                f"{seo.date_courte(jours[-1])} : {_fmt(total)} € au total, avec le détail de chaque journée.")
    else:
        total = 0
        phrase = f"Aucune journée terminée n'est encore disponible pour les retards {sujet}."
        desc = f"Coût des retards et suppressions de trains {sujet}, jour par jour."

    corps = [
        '<header class="entete">',
        f'  <p class="fil"><a href="/">Aujourd\'hui</a> › <a href="/{slug}">{escape(seo.nom_ligne(line_id))}</a></p>',
        f'  <h1>{_pastille(line_id)} Historique des retards {escape(sujet)}</h1>',
        f'  <p class="cout">{_fmt(total)} €</p>',
        f'  <p class="chapeau">{phrase}</p>',
        '</header>',
    ]
    if jours:
        corps += ['<section class="bloc">', '  <h2>Jour par jour</h2>', '  <table>',
                  '    <thead><tr><th>Jour</th><th class="d">Coût</th><th class="d">Temps perdu</th>'
                  '<th class="d">Retardés</th><th class="d">Supprimés</th></tr></thead>', '    <tbody>']
        for j in jours:
            l = hist[j][line_id]
            corps.append(f'      <tr><td><a href="/{slug}/{j.isoformat()}">{escape(seo.date_longue(j))}</a></td>'
                         f'<td class="d">{_fmt(l["cout"])} €</td><td class="d">{_fmt_duree(l["minutes"])}</td>'
                         f'<td class="d">{_fmt(l["retards"])}</td><td class="d">{_fmt(l["supprimes"])}</td></tr>')
        corps += ['    </tbody>', '  </table>', '</section>']
    autres = " · ".join(f'<a href="/{s}/historique">{escape(seo.nom_ligne(lid).replace("ligne", "Ligne"))}</a>'
                        for lid, s in LINE_SLUGS.items() if lid != line_id)
    corps += [
        f'<nav class="jours autres" aria-label="Historique des autres lignes">{autres}</nav>',
        '<p class="note pied">La journée en cours est sur la page de la ligne. Chiffres mesurés à partir du flux '
        'temps réel d\'Île-de-France Mobilités. <a href="/methode.html">Voir la méthode</a>.</p>',
    ]
    return _habiller(gabarit, _head(titre, desc, f"/{slug}/historique", "/og.png"), "\n".join(corps))


# ── Réponses ──

async def reponse_jour(gabarit: str, line_id: str, jour_str: str) -> tuple[int, str]:
    """(code HTTP, contenu). 200 : la page ; 302 : adresse de redirection (journée en cours) ; 404 : jour inconnu ;
    503 : base injoignable — jamais 404, qui ferait retirer la page des moteurs."""
    from backend.metrics import PARIS_TZ, journee_de

    try:
        jour = date.fromisoformat(jour_str)
    except ValueError:
        return 404, "Page inconnue"
    if jour_str != jour.isoformat():   # 20261112, 2026-W46-4… : une seule adresse par jour
        return 404, "Page inconnue"
    if jour == journee_de(datetime.now(PARIS_TZ)):
        return 302, f"/{LINE_SLUGS[line_id]}"
    hist = await historique()
    if hist is None:
        return 503, "Données momentanément indisponibles"
    if line_id not in hist.get(jour, {}):
        return 404, "Aucune donnée pour ce jour"
    return 200, rendre_jour(gabarit, line_id, jour, hist, await detail_jour(line_id, jour))


async def reponse_historique(gabarit: str, line_id: str) -> tuple[int, str]:
    hist = await historique()
    if hist is None:
        return 503, "Données momentanément indisponibles"
    return 200, rendre_historique(gabarit, line_id, hist)
