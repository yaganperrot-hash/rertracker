from datetime import date

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://user:password@db:5432/retards_idf"
    prim_api_key: str = ""
    twitter_api_key: str = ""
    twitter_api_secret: str = ""
    twitter_access_token: str = ""
    twitter_access_secret: str = ""
    # Retards et suppressions : 1 req Estimated Timetable (flux global) par relevé × 216 relevés (6 h → minuit) = 216/jour
    polling_interval_minutes: int = 5
    # Perturbations déclarées : 2 req Navitia par relevé × 54 relevés = 108/jour (annonces qui changent lentement)
    perturbations_interval_minutes: int = 20
    log_level: str = "INFO"
    max_open_incident_minutes: int = 180
    cancel_default_impact_minutes: int = 5
    smic_horaire: float = 12.31           # € brut / heure, en vigueur depuis le 1er juin 2026 — base du coût estimé
    smic_source: str = "depuis le 1er juin 2026 · source : arrêté du 22 mai 2026"  # affiché sur /methode.html
    bilans_interval_minutes: int = 10     # période de régénération des JSON de bilans
    prim_quota_jour: int = 1000           # quota PRIM par clé — en-tête x-ratelimit-limit-day, remis à zéro à minuit UTC
    collecte_heure_debut: int = 6         # aucun relevé PRIM de minuit à cette heure (poids horaires nuls, quota épargné)
    # Premier jour dont les chiffres sont complets (13 lignes, identifiants Transilien justes, suppressions détectées) :
    # les jours d'avant restent en base mais n'entrent dans aucun cumul ni aucune comparaison affichés
    debut_donnees_fiables: date = date(2026, 9, 16)
    archive_flux_jours: int = 3           # réponses brutes du flux Estimated Timetable gardées dans logs/flux_brut/ (0 = aucune)
    email_sender: str = ""                # adresse Gmail expéditrice du récap quotidien
    email_password: str = ""              # App Password Gmail (16 caractères, sans espaces)
    email_recipient: str = ""             # adresse destinataire du récap quotidien

    class Config:
        env_file = ".env"
        extra = "ignore"


# Mapping line_id → URL slug (pour les pages /:slug)
LINE_SLUGS = {
    'RER_A': 'rer-a', 'RER_B': 'rer-b', 'RER_C': 'rer-c', 'RER_D': 'rer-d', 'RER_E': 'rer-e',
    'TRANSILIEN_H': 'ligne-h', 'TRANSILIEN_J': 'ligne-j', 'TRANSILIEN_K': 'ligne-k',
    'TRANSILIEN_L': 'ligne-l', 'TRANSILIEN_N': 'ligne-n', 'TRANSILIEN_P': 'ligne-p',
    'TRANSILIEN_R': 'ligne-r', 'TRANSILIEN_U': 'ligne-u',
}
SLUG_TO_ID = {v: k for k, v in LINE_SLUGS.items()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
