# CLAUDE.md — Compteur de Retards IDF

## Vue d'ensemble
Tableau de bord temps réel comptabilisant incidents, retards et minutes-voyageurs perdues
sur les lignes RER et Transilien d'Île-de-France.

---

## Architecture & Choix techniques

| Composant | Technologie | Raison |
|-----------|-------------|--------|
| Backend | Python 3.12 + FastAPI | Async natif, APScheduler intégrable |
| Base de données | PostgreSQL 16 | Robuste, requêtes analytiques |
| ORM | SQLAlchemy 2.x async | Async/await natif |
| Scheduler | APScheduler 3.x | Polling 5 min sans process séparé |
| Frontend | HTML/CSS/JS vanilla | Zéro dépendance, déploiement simple |
| Graphiques | Chart.js (CDN) | Léger, pas de build step |
| Conteneurisation | Docker + docker-compose | Cohérence dev/prod |
| Déploiement cible | VPS Ubuntu 24 | Simple, contrôlé |

---

## Source de données
- **API PRIM IDF Mobilités** : polling toutes les 5 min
- Endpoint : `https://prim.iledefrance-mobilites.fr/marketplace/`
- Auth : header `apikey: {PRIM_API_KEY}`
- Quota : 20 000 req/jour (polling 5 min ≈ 288 req/jour ✅)
- **Fréquentation** : `data/frequentation.json` (statique, màj mensuelle)

---

## Lignes couvertes
RER A, B, C, D, E — Transilien H, J, K, L, N, P, R, U

---

## Variables d'environnement (voir `.env.example`)
```
PRIM_API_KEY=
TWITTER_API_KEY=
TWITTER_API_SECRET=
TWITTER_ACCESS_TOKEN=
TWITTER_ACCESS_SECRET=
DATABASE_URL=postgresql://user:password@db:5432/retards_idf
POLLING_INTERVAL_MINUTES=5
LOG_LEVEL=INFO
```

---

## Comment lancer localement
```bash
# 1. Copier les variables d'environnement
cp .env.example .env
# Éditer .env avec vos credentials

# 2. Lancer avec Docker
docker-compose up -d

# 3. Vérifier les logs
docker-compose logs -f backend

# 4. Accès
# Frontend : http://localhost:8000
# API docs : http://localhost:8000/docs
```

---

## Structure des dossiers
```
/
├── CLAUDE.md            ← ce fichier
├── TODO.md
├── .claude/commands/    ← custom slash commands
├── backend/             ← FastAPI + collecteur + métriques
├── frontend/            ← HTML/CSS/JS vanilla
├── data/                ← frequentation.json (statique)
├── logs/                ← logs applicatifs
├── tests/               ← pytest
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## État d'avancement

### ✅ Terminé
- Étape 01 — CLAUDE.md créé
- Étape 02 — TODO.md créé
- Étape 03 — git init + .gitignore + structure dossiers
- Étape 04 — Docker + PostgreSQL (`docker-compose.yml`, `Dockerfile`, `requirements.txt`)
- Étape 05 — Modèles SQLAlchemy (`backend/models.py`, `backend/database.py`, `backend/config.py`)
- Étape 06 — Collector PRIM (`backend/collector.py`, `data/frequentation.json`)
- Étape 07 — Calcul des métriques (`backend/metrics.py`)
- Étape 08 — Endpoints API REST (`backend/api.py`, `backend/main.py`)
- Étape 09 — Frontend page principale (`frontend/index.html`)
- Étape 10 — Frontend page statistiques (`frontend/stats.html`)
- Étape 12 — Page /methode (`frontend/methode.html`)
- Étape 13 — Tests unitaires (`tests/test_collector.py`, `tests/test_metrics.py`, `pytest.ini`)

### ⏳ À faire
- Étape 11 — Bot X quotidien
- Étape 14 — README.md final

---

## Problèmes rencontrés & solutions
- `pydantic-settings` ajouté à `requirements.txt` (nécessaire pour `BaseSettings` dans FastAPI moderne)
- `DATABASE_URL` avec préfixe `postgresql://` converti automatiquement en `postgresql+asyncpg://` dans `database.py`

---

## Prochaine étape à reprendre
**Étape 11** — Bot X quotidien (`backend/bot.py`)
