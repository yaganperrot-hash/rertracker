# TODO — Compteur de Retards IDF

## En cours
_(aucun)_

## À faire
- [ ] **Régénérer la clé PRIM** (en clair dans l'historique git, commit `c591442`) — urgent
- [ ] Vérifier visuellement le rendu des durées lisibles (bureau + mobile 390 px)
- [ ] Renseigner les clés Twitter/X dans `.env`
- [ ] Vérifier les causes des perturbations (catégorisation `causes.py` vs motifs réels PRIM)

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
- [x] Bug 9 — HOURLY_WEIGHTS aligné sur 19.2 (test corrigé) — 2026-09-11
- [x] Bug 10 — 5 tests collector réalignés (mocks, statuts, heures) — 2026-09-11
- [x] Bug 11 — Logging diagnostic ajouté pour Transilien L/N/P/R à 0 incident — 2026-09-11
- [x] Bug 17 — `_parse_dt` corrigé : timestamps PRIM lus en Europe/Paris au lieu d'UTC — 2026-09-11
- [x] Refonte typo `methode.html` alignée sur l'accueil (--muted #555, --sub #333, 16px, graisse 400) — 2026-09-11
- [x] Bot récap : bilan du jour même au lieu de la veille — 2026-09-11
