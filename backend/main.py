import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.config import get_settings, SLUG_TO_ID
from backend.database import init_db
from backend.collector import collect_disruptions, collect_rt_delays, collecte_autorisee
from backend.metrics import compute_daily_metrics
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
    yesterday = datetime.now(PARIS_TZ).date() - timedelta(days=1)
    try:
        await compute_daily_metrics(target_date=yesterday)
        logger.info("Finalized yesterday's metrics (%s)", yesterday)
    except Exception:
        logger.exception("Error finalizing yesterday's metrics")


async def _startup_collect():
    """Collecte initiale séquentielle : collecte → métriques → bilans.

    Évite la race condition où compute_daily_metrics tourne avant que les
    incidents du cycle soient en BDD.
    """
    try:
        # Finaliser la veille (incidents ouverts, serveur éteint la nuit…)
        await _finalize_yesterday()
        if collecte_autorisee():
            await collect_disruptions()
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

    logger.info("Starting scheduler (interval=%d min)", settings.polling_interval_minutes)

    # Premier cycle : séquentiel au démarrage pour éviter la race condition
    await _startup_collect()

    # Cycle régulier : un seul job qui enchaîne collecte → métriques (pas de race)
    async def _collect_cycle():
        # Pause nocturne : quota PRIM de 1 000 req/jour, et la nuit ne pèse rien dans le calcul
        if not collecte_autorisee():
            return
        await collect_disruptions()
        await collect_rt_delays()
        await compute_daily_metrics()

    scheduler.add_job(
        _collect_cycle,
        "interval",
        minutes=settings.polling_interval_minutes,
        id="collect_cycle",
    )
    scheduler.add_job(
        generer_bilans,
        "interval",
        minutes=settings.bilans_interval_minutes,
        id="generer_bilans",
    )
    # À 07h05 Paris : finaliser les métriques de la veille (fenêtre 07h-07h bouclée)
    scheduler.add_job(
        _finalize_yesterday,
        "cron",
        hour=7,
        minute=5,
        timezone=PARIS_TZ,
        id="finalize_yesterday",
    )
    scheduler.add_job(
        post_daily_recap,
        "cron",
        hour=20,
        minute=0,
        id="daily_tweet",
        # Au-delà d'1 h de retard, on saute : le bilan porterait sur le mauvais jour
        misfire_grace_time=3600,
    )
    scheduler.start()

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")


app = FastAPI(
    title="Compteur de Retards IDF",
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


# Serve frontend static files
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
