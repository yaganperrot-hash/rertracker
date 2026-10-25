import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.config import get_settings, LINE_SLUGS, SLUG_TO_ID
from backend.database import init_db
from backend.collector import collect_disruptions, collect_rt_delays, collecte_autorisee, dernier_releve
from backend.metrics import compute_daily_metrics, journee_de
from backend.bilans import generer_bilans
from backend.api import router
from backend.bot import post_daily_recap

settings = get_settings()
logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

# Après une mise en veille, les relevés en retard étaient tous sautés (tolérance
# par défaut : 1 s). coalesce : une seule exécution pour tous les relevés manqués.
scheduler = AsyncIOScheduler(job_defaults={"coalesce": True, "misfire_grace_time": None})


PARIS_TZ = ZoneInfo("Europe/Paris")


async def _finalize_yesterday():
    """Recalcule les métriques de la veille (basées sur les incidents déjà en BDD).

    Utile quand le serveur a été arrêté pendant la nuit : les métriques de la
    veille étaient figées au dernier relevé et les incidents encore ouverts
    avaient une durée sous-estimée.
    """
    yesterday = journee_de(datetime.now(PARIS_TZ)) - timedelta(days=1)
    try:
        await compute_daily_metrics(target_date=yesterday)
        logger.info("Finalized yesterday's metrics (%s)", yesterday)
    except Exception:
        logger.exception("Error finalizing yesterday's metrics")


async def _releve_recent(source: str, intervalle_minutes: int) -> bool:
    """Un relevé de cette source a-t-il été écrit il y a moins d'un intervalle ? Un redémarrage ne le refait
    pas : chaque relevé est pris sur le quota PRIM. En cas de doute (erreur, base vide), on relève."""
    try:
        dernier = await dernier_releve(source)
    except Exception:
        logger.exception("Dernier relevé %s illisible", source)
        return False
    return dernier is not None and datetime.now(timezone.utc) - dernier < timedelta(minutes=intervalle_minutes)


async def _startup_collect():
    """Collecte initiale séquentielle : collecte → métriques → bilans.

    Évite la race condition où compute_daily_metrics tourne avant que les
    incidents du cycle soient en BDD.
    """
    try:
        # Finaliser la veille (incidents ouverts, serveur éteint la nuit…)
        await _finalize_yesterday()
        if collecte_autorisee():
            if await _releve_recent("disruption", settings.perturbations_interval_minutes):
                logger.info("Perturbations relevées il y a moins de %d min : pas de relevé au démarrage",
                            settings.perturbations_interval_minutes)
            else:
                await collect_disruptions()
            if await _releve_recent("realtime", settings.polling_interval_minutes):
                logger.info("Temps réel relevé il y a moins de %d min : pas de relevé au démarrage",
                            settings.polling_interval_minutes)
            else:
                await collect_rt_delays()
        else:
            logger.info("Pause nocturne : aucun relevé PRIM avant %d h", settings.collecte_heure_debut)
        await compute_daily_metrics()
        await generer_bilans()
        logger.info("Initial collect + metrics + bilans OK")
    except Exception:
        logger.exception("Error during startup collect")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing database...")
    await init_db()

    logger.info("Starting scheduler (temps réel toutes les %d min, perturbations toutes les %d min)",
                settings.polling_interval_minutes, settings.perturbations_interval_minutes)

    # Premier cycle : séquentiel au démarrage pour éviter la race condition
    await _startup_collect()

    # Cycle temps réel : collecte → métriques dans le même job (pas de race)
    async def _collect_cycle():
        # Pause nocturne : quota PRIM de 1 000 req/jour, et la nuit ne pèse rien dans le calcul
        if not collecte_autorisee():
            return
        await collect_rt_delays()
        await compute_daily_metrics()

    # Perturbations déclarées : sans coût dans le calcul, cadence propre (compteur Navitia)
    async def _perturbations_cycle():
        if collecte_autorisee():
            await collect_disruptions()

    scheduler.add_job(
        _collect_cycle,
        "interval",
        minutes=settings.polling_interval_minutes,
        id="collect_cycle",
    )
    scheduler.add_job(
        _perturbations_cycle,
        "interval",
        minutes=settings.perturbations_interval_minutes,
        id="perturbations_cycle",
    )
    scheduler.add_job(
        generer_bilans,
        "interval",
        minutes=settings.bilans_interval_minutes,
        id="generer_bilans",
    )
    # 5 min après le début de la journée comptée (collecte_heure_debut) : finaliser les métriques de la veille
    scheduler.add_job(
        _finalize_yesterday,
        "cron",
        hour=settings.collecte_heure_debut,
        minute=5,
        timezone=PARIS_TZ,
        id="finalize_yesterday",
    )
    scheduler.add_job(
        post_daily_recap,
        "cron",
        hour=19,
        minute=30,
        timezone=PARIS_TZ,
        id="daily_recap",
        # Au-delà d'1 h de retard, on saute : le bilan porterait sur le mauvais jour
        misfire_grace_time=3600,
    )
    scheduler.start()

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")


app = FastAPI(
    title="IDF-RETARD",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

frontend_dir = Path(__file__).parent.parent / "frontend"

# Bilans recalculés toutes les 10 min : cache navigateur/CDN aligné sur ce rythme
_CACHE_CONTROL = {
    "/statistiques": "public, max-age=600",
    "/annee": "public, max-age=600",
    "/bilan.css": "public, max-age=86400",  # chargés avec ?v=N par les pages
    "/bilan.js": "public, max-age=86400",
}


@app.middleware("http")
async def cache_bilans(request: Request, call_next):
    response = await call_next(request)
    chemin = request.url.path
    if chemin.startswith("/data/"):
        valeur = "public, max-age=600, stale-while-revalidate=600"
    else:
        valeur = _CACHE_CONTROL.get(chemin)
    # Jamais de cache sur un 404 : le premier calcul peut ne pas être encore écrit
    if valeur and response.status_code == 200:
        response.headers["Cache-Control"] = valeur
    return response


# Déclarées avant le mount "/" qui, sinon, les masquerait
@app.get("/statistiques", include_in_schema=False)
async def page_statistiques():
    return FileResponse(frontend_dir / "statistiques.html")


@app.get("/annee", include_in_schema=False)
async def page_annee():
    return FileResponse(frontend_dir / "annee.html")


@app.get("/stats.html", include_in_schema=False)
async def ancienne_page_stats():
    return RedirectResponse("/statistiques", status_code=301)


@app.get("/mon-trajet", include_in_schema=False)
async def page_mon_trajet():
    return FileResponse(frontend_dir / "mon-trajet.html")


@app.get("/temps-reel", include_in_schema=False)
async def page_temps_reel():
    return FileResponse(frontend_dir / "temps-reel.html")


# Pages par ligne : une route explicite par slug (pas de catch-all
# qui masquerait les fichiers statiques comme nav.css, pick.js, etc.)
_ligne_html = frontend_dir / "ligne.html"
for _slug in SLUG_TO_ID:
    @app.get(f"/{_slug}", include_in_schema=False)
    async def _page_ligne(_s=_slug):
        return FileResponse(_ligne_html)


# ── Partage réseaux sociaux ──

async def _share_metrics(target_date: date) -> list[dict]:
    """Charge les DailyMetric de toutes les lignes pour une date donnée."""
    from sqlalchemy import select as sa_select
    from backend.database import AsyncSessionLocal
    from backend.models import DailyMetric
    from backend.metrics import cout_eur

    smic = get_settings().smic_horaire
    async with AsyncSessionLocal() as db:
        stmt = sa_select(DailyMetric).where(DailyMetric.date == target_date)
        rows = (await db.execute(stmt)).scalars().all()
        return [
            {"line_id": r.line_id, "minutes_voyageurs": r.minutes_voyageurs,
             "cout_eur": cout_eur(r.minutes_voyageurs, smic)}
            for r in rows
        ]


@app.get("/share/{slug}/{date_str}.png", include_in_schema=False)
async def share_image(slug: str, date_str: str, format: str = Query(default="square")):
    from backend.share import LINE_COLORS, FORMATS, compute_card_data, render_card, effective_date

    line_id = SLUG_TO_ID.get(slug)
    if not line_id or line_id not in LINE_COLORS:
        return Response(status_code=404, content="Ligne inconnue")

    if format not in FORMATS:
        format = "square"

    if date_str == "today":
        target_date = effective_date()
    else:
        try:
            target_date = date.fromisoformat(date_str)
        except ValueError:
            return Response(status_code=400, content="Date invalide (AAAA-MM-JJ)")

    metrics = await _share_metrics(target_date)
    data = compute_card_data(line_id, target_date, metrics)
    png = render_card(data, format)

    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=600"},
    )


@app.get("/share/{slug}/{date_str}", include_in_schema=False)
async def share_page(slug: str, date_str: str):
    from backend.share import LINE_COLORS, compute_card_data, effective_date, _fmt, _date_label

    line_id = SLUG_TO_ID.get(slug)
    if not line_id or line_id not in LINE_COLORS:
        return Response(status_code=404, content="Ligne inconnue")

    if date_str == "today":
        target_date = effective_date()
    else:
        try:
            target_date = date.fromisoformat(date_str)
        except ValueError:
            return Response(status_code=400, content="Date invalide")

    metrics = await _share_metrics(target_date)
    data = compute_card_data(line_id, target_date, metrics)
    meta = LINE_COLORS[line_id]

    cout_txt = f"{_fmt(data['cout_eur'])} €" if data["cout_eur"] else "0 €"
    date_fmt = f"{target_date.day}/{target_date.month:02d}/{target_date.year}"
    title = f"{meta['name']} — {cout_txt} de retards le {date_fmt}"
    description = f"Coût des retards sur {meta['name']} le {date_fmt}, estimé par IDF-RETARD."
    og_image = f"/share/{slug}/{target_date.isoformat()}.png?format=og"
    page_url = f"/{slug}"

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:image" content="{og_image}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:type" content="article">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{description}">
<meta name="twitter:image" content="{og_image}">
<style>body{{font-family:Roboto,sans-serif;text-align:center;padding:60px 20px;background:#F7F4EF;color:#000}}
h1{{font-size:24px}}p{{color:#555;font-size:16px}}a{{color:#C0392B}}</style>
</head>
<body>
<h1>{title}</h1>
<p>{description}</p>
<p>Redirection vers <a href="{page_url}">{meta['name']}</a>…</p>
<script>setTimeout(function(){{location.href="{page_url}"}},1500)</script>
</body>
</html>"""

    return HTMLResponse(content=html, headers={"Cache-Control": "public, max-age=600"})


# Serve frontend static files
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
