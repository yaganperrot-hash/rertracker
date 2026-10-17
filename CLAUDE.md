# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
| Déploiement | VPS OVH Ubuntu 24 (`deploy/`) | 

---

## Source de données
- **API PRIM IDF Mobilités** : de 6 h à minuit (heure de Paris), temps réel toutes les 5 min, perturbations toutes les 20 min
- Endpoints : retards et suppressions via le flux SIRI **Estimated Timetable**
  (`/marketplace/estimated-timetable?LineRef=ALL`, un seul appel pour tout le réseau : ~4,5 Mo compressés, ~50 Mo de
  JSON, ~4 h 30 de trains arrêt par arrêt, filtré sur nos 13 lignes) ;
  perturbations déclarées via Navitia (`/marketplace/v2/navitia/physical_modes/{mode}/line_reports`).
  Un retard ou une suppression n'est mesuré qu'à moins de 10 min du passage estimé (`FENETRE_MESURE_MINUTES`).
- Auth : header `apikey: {PRIM_API_KEY}`
- Quota : **1 000 req/jour par clé et par flux** — compteurs distincts constatés dans les en-têtes
  (`x-ratelimit-remaining-day`) : Navitia, Estimated Timetable (2026-09-16), Prochains passages / stop-monitoring
  (2026-09-17, une requête par gare). Remise à zéro à minuit UTC (2 h l'été).
  Budget : Estimated Timetable 1 req/relevé × 216 = 216/jour ; Navitia 2 req/relevé × 54 = 108/jour.
  Les deux restes sont loggués à chaque relevé (warning sous 150). Chaque requête manuelle est prise sur ces budgets.
- **Données statiques** (open data, construites hors ligne, versionnées) — ordre de construction :
  `python -m backend.profils build` (profils horaires, vacances) → `python -m backend.offre build` (GTFS : départs
  par gare, missions, noms d'arrêts) → `python -m backend.frequentation build` (comptages SNCF + validations IDFM :
  voyageurs montant dans un train par gare et heure), puis `python -m backend.recalcul`.
  `python -m backend.offre horaires` (indépendant, sans recalcul) : `data/horaires.json.gz`, passage de chaque train à
  chaque gare, lu par « Mon trajet » (`backend/trajets.py`). À reconstruire à chaque publication du GTFS IDFM : les
  `trip_id` changent et le flux temps réel suit (warning « Horaires GTFS périmés » dans les logs).
  `data/frequentation.json` n'est plus utilisé par le calcul.

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
POLLING_INTERVAL_MINUTES=20
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

# 3. Lancer dans son propre terminal, ou détaché (`nohup … & disown`) — `run_in_background` seul est tué.
#    Ce serveur collecte sur le quota PRIM du VPS (voir « Production ») : ne le lancer que le temps d'un essai.
./venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# 4. Accès
# Frontend : http://localhost:8000
# API docs : http://localhost:8000/docs
```

---

## Commandes fréquentes

```bash
# Tests (328 tests, ~13 s)
venv/Scripts/python -m pytest tests/ -x -q          # Windows
./venv/bin/python -m pytest tests/ -x -q             # Mac

# Recalcul historique (après modification metrics/bilans/fréquentation)
python -m backend.recalcul

# Déploiement VPS
ssh ubuntu@149.56.102.94 "cd ~/rertracker && git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build"

# Reconstruction données statiques (dans l'ordre)
python -m backend.profils build
python -m backend.offre build
python -m backend.frequentation build
python -m backend.recalcul
python -m backend.offre horaires   # Mon trajet, indépendant
```

---

## Conventions de rangement
- Backend : `backend/` — FastAPI + scheduler. Collecte PRIM, calcul des minutes-voyageurs,
  génération des JSON bilans, extraction des causes, bot X, transfert d'incidents entre bases.
- Frontend : `frontend/` — HTML/CSS/JS vanilla, une page par vue ; nav et sélecteur de ligne
  factorisés (`nav.css`, `pick.*`).
- Tests → `tests/` (`test_*.py`, pytest). Config/env → `backend/config.py`.
- JSON statiques : `data/frequentation.json` (tracké) ; `frontend/data/` (régénéré, gitignored).
- Spécifique Claude Code : état de session dans `.claude/` (SESSION.md, DEBUG.md, TASKS.md,
  commands/) ; mémoire persistante dans `memory/` (lessons.md).
- Invisibles à `git ls-files` (gitignored) : `frontend/data/`, `logs/`, `.env`. `transferts/` et
  `publications/` sont versionnés.
- Rien de nouveau à la racine sans raison.
- Fichiers texte : toujours `encoding="utf-8"` explicite en lecture comme en écriture — le projet tourne sur Mac
  et sur Windows (cp1252 par défaut).
- Identifiants PRIM : les vérifier sur l'API (`pt_objects?q=…&type[]=line`, mode « RER » / « Train Transilien »),
  jamais les recopier — les lignes « Remplacement … » (bus) portent la même lettre.
- Collecte PRIM : une réponse HTTP 200 vide est une panne — chaque appel loggue un warning quand il ne renvoie rien.
- Collecte PRIM : toute mesure ajoutée au relevé est protégée par un `try/except` avec repli — elle ne doit jamais
  faire perdre le relevé (le 2026-09-17, un tri a fait perdre toutes les lignes). Un redémarrage ne relance un relevé
  que si le dernier date de plus d'un intervalle (1 requête temps réel, 2 Navitia).
- Tout invariant énoncé dans la doc ou un commentaire (somme de poids, borne, plafond) doit être couvert
  par un test : sinon il devient faux en silence — les poids horaires ont annoncé « somme=18.0 » pendant
  une semaine en valant 19.2, majorant tous les chiffres de 6,7 %.
- Flags d'arrêts (`s`, `k`) : hors fenêtre de mesure → `None` (pas `False`), pour que `fusionner_arrets`
  conserve la valeur précédente. Tout champ devant survivre à la fusion doit être dans la liste de
  conservation. `is_cancelled` = au moins un arrêt fusionné `s=True` (`collector.train_supprime`) : un arrêt sorti
  de la fenêtre garde son `True`, seul un `s=False` mesuré dans la fenêtre lève la suppression (bug 46, 2026-09-22) ;
  même règle au recalcul et à l'import de transfert (arrêts fusionnés arrêt par arrêt).


### 🔄 En maintenance — voir `TODO.md`

---

## Décisions de design
- **Accueil = fenêtre unique « aujourd'hui »** (journée comptée depuis la reprise des relevés, 6 h heure de Paris —
  `metrics.debut_journee`, 2026-09-18) : hero, cumul et table
  lisent les mêmes minutes-voyageurs du jour. Tout cumul pluri-jours (semaine, année) va sur une autre page.
  Charte : fond crème, Roboto, couleurs de ligne, accents noir + rouge uniquement.
- **Calcul = mesure** (2026-09-16) : chaque hypothèse maison est remplacée dès qu'une donnée mesurée existe
  (flux temps réel arrêt par arrêt, comptages SNCF, validations et GTFS IDFM) ; ce qui reste estimé est listé
  dans les Limites de la page Méthode.
- **Données fiables à partir du 2026-09-16** (`Settings.debut_donnees_fiables`) : les jours d'avant restent en base
  mais n'entrent dans aucun cumul ni aucune comparaison affichés.
- **Bilans = JSON statiques** (`frontend/data/`, ignoré par git) régénérés toutes les 10 min par le scheduler,
  servis avec `Cache-Control: max-age=600`. Coût arrondi **par ligne × jour** puis sommé : un total affiché est
  toujours la somme exacte de son détail. Deux unités à l'écran : € et minutes. Couleurs de ligne = celles de
  l'accueil. Causes : « Motif : … » PRIM lu en priorité.

---

## Production — VPS OVH (depuis le 2026-10-12)
Le VPS est le seul serveur qui collecte : sa base PostgreSQL fait référence. Procédures dans `deploy/README.md`.
- **Mise à jour** : sur le VPS, `git pull` puis
  `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`.
- **Un seul serveur, un seul worker** : la clé PRIM et ses quotas de 1 000 req/jour par flux sont communs à toutes
  les machines (216 Estimated Timetable et 108 Navitia pour un serveur au réglage par défaut). Ne pas lancer de
  serveur collecteur sur un PC de développement, et garder `--workers 1` en prod : le scheduler démarre une fois
  par worker. Toute affirmation sur la limite PRIM se vérifie dans les en-têtes `x-ratelimit-*-day` d'une réponse,
  jamais de mémoire.
- **Transfert inter-PC** (`backend/transfert.py`, `transferts/`) : plus utilisé au quotidien, gardé pour rapatrier
  une journée dans une base locale — `python -m backend.transfert export [AAAA-MM-JJ]` / `import <fichier>.json`.

---

## Prochaine étape à reprendre
Voir `TODO.md` et les bugs ouverts de `.claude/DEBUG.md`. Priorités : **régénérer la clé PRIM** (fichier supprimé
du repo mais clé encore dans l'historique git — à renouveler sur le portail PRIM IDFM), puis observer les arrêts
sautés (B, règle réécrite le 2026-09-22) avant de décider s'ils entrent dans le coût.

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
- EXCEPTION — stoppe et préviens-moi si : (a) tu dois toucher une ZONE CRITIQUE (voir liste
  ci-dessous), (b) tu découvres que le plan validé était faux ou incomplet, (c) tu devrais
  sortir du périmètre du projet.
- Ne modifier QUE le code concerné par la tâche. Ne pas sortir du projet sans accord préalable.
- Une tâche n'est "finie" que testée ET tests au vert. Un test rouge = tu corriges avant de
  déclarer terminé. Jamais de "fait" avec des tests qui échouent.

### Zones critiques — confirmation obligatoire avant modification
- **Config PRIM** : intervalle de polling, quota, endpoint, gestion de la clé API
  (un mauvais réglage = quota de 1 000 req/jour épuisé → HTTP 429, plus aucune collecte jusqu'à minuit UTC).
- **Gestion des secrets** : `.env`, clés API — jamais de secret en clair dans le code ou committé.
- **Base de données** : modèles SQLAlchemy, migrations, `database.py` (risque sur les données).
- **Logique de calcul** : `metrics.py`, `bilans.py`, `causes.py` — cœur métier (minutes-voyageurs,
  coûts) ; une régression fausse tous les chiffres affichés.

## Autorisations Claude Code

Claude Code dispose de **toutes les autorisations** sur ce projet, sous deux conditions :
1. **Périmètre** : ne toucher que les fichiers liés aux tâches en cours et rester dans ce dossier projet.
2. **Lancement** : une fois que l'utilisateur a dit « lance-toi » (ou équivalent), Claude Code agit en autonomie totale — **aucune confirmation supplémentaire** n'est requise.

Droits inclus sans demande :
- `git add`, `git commit`, `git push`
- Création, édition de fichiers dans le projet
- Exécution de commandes shell (`pytest`, `docker`, `pip`, `uvicorn`, etc.)
- Création de branches, tags, PRs

EXCEPTION — demander confirmation même en mode autonome (irréversible / destructif) :
- `git push --force` (utiliser `--force-with-lease` par défaut), `git reset --hard`, suppression de branche distante
- Suppression de fichiers (`rm`, `rm -rf`, suppression via l'outil d'édition)
- Toute réécriture d'historique git (`rebase`, `filter-repo`, `commit --amend` déjà poussé)