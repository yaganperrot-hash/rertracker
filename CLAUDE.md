# CLAUDE.md — Compteur de Retards IDF

## Vue d'ensemble
Tableau de bord temps réel comptabilisant incidents, retards et minutes-voyageurs perdues
sur les lignes RER et Transilien d'Île-de-France.

---

## Architecture & Choix techniques

| Composant | Technologie | 
|-----------|-------------|
| Backend | Python 3.12 + FastAPI | 
| Base de données | PostgreSQL 16 | 
| ORM | SQLAlchemy 2.x async | 
| Scheduler | APScheduler 3.x | 
| Frontend | HTML/CSS/JS vanilla |
| Graphiques | Chart.js (CDN) | 
| Conteneurisation | Docker + docker-compose | 
| Déploiement cible | VPS Ubuntu 24 | 

---

## Source de données
- **API PRIM IDF Mobilités** : polling toutes les 5 min
- Endpoint : `https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia/line_reports`
- Auth : header `apikey: {PRIM_API_KEY}`
- Quota : 1 000 req/jour 
- **Fréquentation** : `data/frequentation.json` (statique, màj mensuelle)

---

## Lignes couvertes
RER A, B, C, D, E — Transilien H, J, K, L, N, P, R, U
(Métro retiré : PRIM ne remonte quasiment pas de données pour les lignes de métro)

---

## Variables d'environnement (voir `.env.example`)
```
PRIM_API_KEY=
TWITTER_API_KEY=
TWITTER_API_SECRET=
TWITTER_ACCESS_TOKEN=
TWITTER_ACCESS_SECRET=
DATABASE_URL=postgresql://user:password@db:5432/retards_idf
POLLING_INTERVAL_MINUTES=12
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
├── CLAUDE.md
├── TODO.md
├── README.md
├── .claude/             ← SESSION.md, DEBUG.md, TASKS.md, commands/
├── backend/
│   ├── main.py          ← FastAPI app + scheduler
│   ├── api.py           ← endpoints REST
│   ├── collector.py     ← collecteur PRIM
│   ├── metrics.py       ← calcul minutes-voyageurs
│   ├── bilans.py        ← génération JSON bilans
│   ├── causes.py        ← extraction causes incidents
│   ├── bot.py           ← récap quotidien X + publications/
│   ├── transfert.py     ← export/import incidents entre PC
│   ├── models.py        ← modèles SQLAlchemy
│   ├── database.py      ← connexion async PostgreSQL
│   ├── config.py        ← Settings (env vars)
│   └── migrate_source.py
├── frontend/
│   ├── index.html       ← dashboard aujourd'hui
│   ├── statistiques.html ← bilans 7j / 30j / année
│   ├── annee.html       ← vue par ligne
│   ├── ligne.html       ← détail d'une ligne
│   ├── temps-reel.html  ← vue temps réel
│   ├── methode.html     ← page méthodologie
│   ├── bilan.css|js     ← styles/logique bilans
│   ├── nav.css          ← navigation unifiée
│   ├── pick.css|js      ← sélecteur de ligne
│   ├── ticker.js        ← bandeau incidents
│   ├── duree.js         ← formatage durées
│   └── data/            ← JSON statiques (gitignored)
├── data/
│   └── frequentation.json ← fréquentation mensuelle
├── docs/maquettes/      ← maquettes de référence
├── logs/                ← logs applicatifs
├── memory/              ← mémoire persistante Claude Code
├── publications/        ← récaps quotidiens (AAAA-MM-JJ.txt)
├── tests/               ← pytest (test_*.py)
├── transferts/          ← exports JSON incidents inter-PC
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── pytest.ini
├── .env.example
└── .gitignore
```


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

---

## Exécution des tâches
- Avant toute tâche : proposer un plan (tâches découpées et ordonnées) et le soumettre.
  Ne jamais commencer sans mon accord explicite.
- Une fois le plan validé : exécuter en autonomie jusqu'au bout, sans redemander
  d'autorisation à chaque étape.
- EXCEPTION — stoppe et préviens-moi si : (a) tu dois toucher une zone critique (PROJECT.md),
  (b) tu découvres que le plan validé était faux ou incomplet, (c) tu devrais sortir du
  périmètre du projet.
- Ne modifier QUE le code concerné par la tâche. Ne pas sortir du projet sans accord préalable.
- Une tâche n'est "finie" que testée ET tests au vert. Un test rouge = tu corriges avant de
  déclarer terminé. Jamais de "fait" avec des tests qui échouent.
---

## Autorisations Claude Code

Claude Code dispose de **toutes les autorisations** sur ce projet, sous deux conditions :
1. **Périmètre** : ne toucher que les fichiers liés aux tâches en cours et rester dans ce dossier projet.
2. **Lancement** : une fois que l'utilisateur a dit « lance-toi » (ou équivalent), Claude Code agit en autonomie totale — **aucune confirmation supplémentaire** n'est requise.

Droits inclus sans demande :
- `git add`, `git commit`, `git push` (y compris `--force` si nécessaire)
- Création, édition, suppression de fichiers dans le projet
- Exécution de commandes shell (`pytest`, `docker`, `pip`, `uvicorn`, etc.)
- Création de branches, tags, PRs
