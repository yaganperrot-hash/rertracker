# TODO — Compteur de Retards IDF

## En cours
_(aucun)_

## À faire
- [ ] **Régénérer la clé PRIM** (en clair dans l'historique git, commit `c591442`) — urgent
- [ ] Bug 9 — `HOURLY_WEIGHTS` somme à 19.2 → min-voyageurs surestimées de ~6,7 % (`backend/metrics.py`)
- [ ] Bug 10 — réaligner les 5 tests collector obsolètes (`tests/test_collector.py`)
- [ ] Bug 11 — Transilien L, N, P, R à 0 incident : logger le payload PRIM brut (les 404 ont disparu)
- [ ] Bug 17 — vérifier le fuseau des horaires de perturbations (`_parse_dt`, probablement lus en UTC)
- [ ] Vérifier visuellement le rendu des durées lisibles (bureau + mobile 390 px)
- [ ] Lisibilité : appliquer la refonte typo de `index.html` à `methode.html`
- [ ] Renseigner les clés Twitter/X dans `.env`

## Terminé
- [x] Étape 01 — CLAUDE.md structuré créé — 2026-03-11
- [x] Étape 02 — TODO.md créé — 2026-03-11
- [x] Étape 03 — git init + .gitignore + structure dossiers — 2026-03-11
- [x] Étape 04 — Docker + PostgreSQL (docker-compose.yml, Dockerfile) — 2026-03-11
- [x] Étape 05 — Modèles SQLAlchemy (backend/models.py, backend/database.py, backend/config.py) — 2026-03-11
- [x] Étape 06 — Collector PRIM (backend/collector.py, data/frequentation.json) — 2026-03-11
- [x] Étape 07 — Calcul des métriques (backend/metrics.py) — 2026-03-11
- [x] Étape 08 — Endpoints API REST (backend/api.py, backend/main.py) — 2026-03-11
- [x] Étape 09 — Frontend page principale (frontend/index.html) — 2026-03-17
- [x] Étape 10 — Frontend page statistiques (frontend/stats.html) — 2026-03-17
- [x] Étape 11 — Bot X quotidien (backend/bot.py) — 2026-03-17
- [x] Étape 12 — Page /methode (frontend/methode.html) — 2026-03-17
- [x] Étape 13 — Tests unitaires (tests/test_collector.py, tests/test_metrics.py) — 2026-03-17
- [x] Étape 14 — README.md final — 2026-03-17
- [x] Correctifs session 2026-04-28 — endpoint PRIM, duree_minutes, filtres, frontend
- [x] Correctifs session 2026-09-09 — 8 bugs corrigés (double comptage, timezone, trains supprimés, pondération horaire, fake counter, etc.)
- [x] Session 2026-09-10 — setup local Mac, retards RT (gare/train/direction), dédoublonnage par train, fuseau Paris, suppressions, lisibilité accueil
- [x] Durées lisibles min → h → jours → ans (`frontend/duree.js`, `bot.py`, tests) — 2026-09-10
- [x] Pages `/statistiques` et `/annee` (maquettes `docs/maquettes/`, TASK-02 → TASK-12) : bilans JSON
  statiques recalculés toutes les 10 min, totaux réconciliés, causes depuis les motifs opérateur, Chart.js ;
  SMIC 2026 à 12,31 €/h partout ; `stats.html` supprimée (301 vers `/statistiques`) — 2026-09-11
- [x] Menu de l'accueil sur les 4 pages, sélecteur 7 jours · 30 jours · Année — 2026-09-11
- [x] Zéro donnée en dur : coûts calculés par le backend, `/api/reference`, bandeau réel — 2026-09-11
- [x] Récap quotidien de 20 h enregistré dans `publications/` sans compte X — 2026-09-11
