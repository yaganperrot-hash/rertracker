# SESSION — État courant

## 2026-09-18 (soir) — PC Windows (historique : `.claude/archive/`)

### Objectif
Collecte continue des données sur le PC Windows.

### Avancement
- Serveur lancé (uvicorn, port 8000), scheduler actif (temps réel 5 min, perturbations 20 min).
- Export `transferts/incidents-2026-09-18.json` (195 incidents).
- 293 tests verts (session précédente, pas relancés cette session).

### Blocages
- Clé PRIM toujours à régénérer (commit `c591442`).
- Bug D (trains absents du flux) : diagnostic en observation, pas de comptabilisation automatique.

### Prochaine étape
1. Surveiller les logs D (trains manquants) sur les archives 5 min.
2. Ajuster la fenêtre de mesure (10 min) sur les archives.
3. Bug 23 (clic pastille picker) — diagnostic console F12.
4. Recalculer l'historique Windows (`python -m backend.recalcul`).
