from datetime import date

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://user:password@db:5432/retards_idf"
    prim_api_key: str = ""
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

    # Alertes Telegram « une ligne dégénère » (backend/alertes.py, ALERTES.md) — calibrées par le backtest
    alerte_seuil_euros: int = 100_000     # coût d'une ligne sur la fenêtre glissante qui déclenche seul (backtest 28/10–10/11 : 4 alertes/semaine)
    alerte_duree_incident_min: int = 30   # un train retardé d'au moins ce temps déclenche si coût ≥ seuil × ratio
    alerte_ratio_seuil_incident: float = 0.8
    alerte_fenetre_min: int = 60          # fenêtre glissante du coût (minutes)
    alerte_max_jour: int = 2              # alertes envoyées par jour, toutes lignes
    alerte_delai_ligne_h: int = 3         # au plus une alerte par ligne sur ce délai
    alerte_silence_debut: int = 22        # aucune alerte de cette heure…
    alerte_silence_fin: int = 6           # … à celle-ci (heure de Paris)
    # Secrets : uniquement dans .env, jamais dans le code
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

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
