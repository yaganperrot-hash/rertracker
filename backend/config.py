from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://user:password@db:5432/retards_idf"
    prim_api_key: str = ""
    twitter_api_key: str = ""
    twitter_api_secret: str = ""
    twitter_access_token: str = ""
    twitter_access_secret: str = ""
    polling_interval_minutes: int = 15
    log_level: str = "INFO"
    max_open_incident_minutes: int = 180
    cancel_default_impact_minutes: int = 5
    smic_horaire: float = 12.31           # € brut / heure, en vigueur depuis le 1er juin 2026 — base du coût estimé
    smic_source: str = "depuis le 1er juin 2026 · source : arrêté du 22 mai 2026"  # affiché sur /methode.html
    bilans_interval_minutes: int = 10     # période de régénération des JSON de bilans
    prim_quota_jour: int = 1000           # quota de requêtes PRIM par jour (contrat marketplace)

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
