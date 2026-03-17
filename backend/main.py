import logging
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import get_settings
from backend.database import init_db
from backend.collector import collect_disruptions
from backend.metrics import compute_daily_metrics
from backend.api import router
from backend.bot import post_daily_recap

settings = get_settings()
logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing database...")
    await init_db()

    logger.info("Starting scheduler (interval=%d min)", settings.polling_interval_minutes)
    scheduler.add_job(
        collect_disruptions,
        "interval",
        minutes=settings.polling_interval_minutes,
        id="collect_disruptions",
    )
    scheduler.add_job(
        compute_daily_metrics,
        "interval",
        minutes=settings.polling_interval_minutes,
        id="compute_metrics",
    )
    scheduler.add_job(
        post_daily_recap,
        "cron",
        hour=20,
        minute=0,
        id="daily_tweet",
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

# Serve frontend static files
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
