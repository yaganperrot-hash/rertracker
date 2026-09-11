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
- Endpoint : `https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia/line_reports`
- Auth : header `apikey: {PRIM_API_KEY}`
- Quota : 20 000 req/jour (polling 5 min × 13 lignes × 2 appels ≈ 7 488 req/jour ✅)
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

> **IMPORTANT** : toujours lancer Claude Code avec `--dangerously-skip-permissions` pour éviter les confirmations à chaque commande.

```bash
# 0. Lancer Claude Code sans confirmations
claude --dangerously-skip-permissions

# 1. Copier les variables d'environnement
cp .env.example .env
# Éditer .env avec vos credentials

# 2. Mac sans Docker — une seule fois : PostgreSQL 16 + venv Python 3.12
#    (jamais le Python système 3.14 : asyncpg==0.29 n'a pas de wheel)
brew install postgresql@16 && brew services start postgresql@16 && createdb retards_idf
/opt/homebrew/bin/python3.12 -m venv venv && ./venv/bin/pip install -r requirements.txt

# 3. Lancer dans son propre terminal (en tâche de fond Claude Code, le process est tué)
./venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

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

- Étape 11 — Bot X quotidien (`backend/bot.py`, planifié à 20h dans `main.py`)
- Étape 14 — README.md final (`README.md`)
- Frontend refonte complète — design light cream + Roboto, API fetch avec fallback mock
- Accueil — refonte de la hiérarchie (2026-09-10) : coût du jour → cumul du jour → incident en cours →
  table par ligne (aujourd'hui, triée par coût, lignes épargnées condensées), repli mobile 2 colonnes
- Bilans (2026-09-11) : `/statistiques` et `/annee` d'après `docs/maquettes/` —
  `backend/bilans.py`, `backend/causes.py`, `frontend/statistiques.html`, `frontend/annee.html`,
  `frontend/bilan.css|js` ; `stats.html` supprimée (301) ; SMIC 2026 = 12,31 €/h (`SMIC_HORAIRE`)
- Navigation unifiée (2026-09-11) : menu de l'accueil sur les 4 pages (`frontend/nav.css`), liens gardés sur
  mobile (2ᵉ rangée) ; menu = Aujourd'hui · Statistiques · Par ligne · Méthode ; sélecteur
  « 7 jours · 30 jours · Année » partagé par `/statistiques` et `/annee` (90 j retiré)
- Zéro donnée en dur (2026-09-11) : coûts du jour / par ligne / par incident calculés par le backend
  (`cout_eur`, même arrondi que les bilans), paramètres affichés servis par `/api/reference` (SMIC, relevés,
  quota PRIM, fréquentation), bandeau des incidents réel sur toutes les pages (`frontend/ticker.js`)
- Récap quotidien enregistré dans le projet (2026-09-11) : à 20 h, `publications/AAAA-MM-JJ.txt` (bilan de la
  veille, montant arrondi par ligne comme le site) ; posté aussi sur X seulement si les clés sont renseignées

### 🔄 En maintenance — voir `TODO.md`

---

## Problèmes rencontrés & solutions
- `pydantic-settings` ajouté à `requirements.txt` (nécessaire pour `BaseSettings` dans FastAPI moderne)
- `DATABASE_URL` avec préfixe `postgresql://` converti automatiquement en `postgresql+asyncpg://` dans `database.py`
- **Accueil = fenêtre unique « aujourd'hui »** (journée comptée depuis 7 h, heure de Paris) : hero, cumul et table
  lisent les mêmes minutes-voyageurs du jour. Tout cumul pluri-jours (semaine, année) va sur une autre page —
  décision du 2026-09-10. Charte : fond crème, Roboto, couleurs de ligne, accents noir + rouge uniquement.
- **Bilans = JSON statiques** (`frontend/data/`, ignoré par git) régénérés toutes les 10 min par le scheduler,
  servis avec `Cache-Control: max-age=600`. Coût arrondi **par ligne × jour** puis sommé : un total affiché est
  toujours la somme exacte de son détail. Deux unités à l'écran sur ces pages : € et minutes. Couleurs de
  ligne = celles de l'accueil (pas celles des maquettes). Causes : « Motif : … » PRIM lu en priorité.

---

## Prochaine étape à reprendre
Voir `TODO.md` et les bugs ouverts de `.claude/DEBUG.md`. Priorités : **régénérer la clé PRIM** (en clair dans
l'historique git), puis bugs 9 / 10 / 11 / 17.

---

## Workflow multi-agents

### Rôles
| Agent | Rôle |
|-------|------|
| **Claude Code** | Analyse le code, lit les fichiers, crée et attribue les tâches |
| **Deepseek** | Implémente les tâches — écriture de code uniquement |

### Règles strictes
- **Claude Code crée toutes les tâches** avant que Deepseek commence à coder.
- **Deepseek ne lance jamais de commande terminal** (pas de `docker`, `pytest`, `pip`, `git`, etc.).
- Deepseek lit les fichiers, écrit du code, c'est tout.
- Toute vérification (tests, lint, docker) est faite par Claude Code ou l'utilisateur.
- Les tâches sont décrites dans `.claude/TASKS.md` avec fichier cible, contexte et critères d'acceptation.
