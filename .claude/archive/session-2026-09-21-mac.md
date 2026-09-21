# SESSION — 2026-09-21 — Mac

### Objectif
Reprise sur le Mac : récupérer la collecte Windows du 18 au 20/09, relancer la collecte.

### Avancement
- `git pull` OK. Réétiquetage Transilien déjà appliqué : 13 et 14/09 ignorés, 15 → 20/09 importés
  (836, 1 427, 143 + 1 666, 2 347, 740, 600 incidents), métriques et bilans recalculés à chaque import.
- `POLLING_INTERVAL_MINUTES=5` OK.
- Serveur lancé sur le Mac (`nohup`, log `logs/uvicorn.out`, désormais ignoré par git) ; quota Estimated
  Timetable à 993 au démarrage → PC Windows arrêté, pas de double collecte.
- Export `transferts/incidents-2026-09-21.json` (883 incidents).
- Aucun code modifié, tests non relancés (304 verts au 20/09 sur Windows).

### Blocages
- Clé PRIM toujours à régénérer (commit `c591442`).
- Historique du Mac pas encore recalculé avec les données statiques régénérées sur Windows le 20/09
  (GTFS 17/09 → 19/10, fréquentation, horaires) : chiffres différents de Windows pour les jours anciens.

### Prochaine étape
1. Serveur arrêté → `./venv/bin/python -m backend.recalcul`, puis tests.
2. Régénérer la clé PRIM (portail PRIM, puis `.env`).
3. Plan de déploiement VPS (Docker, `.env`, base, `frontend/data/`, `logs/`).
4. Fenêtre de mesure 10 → 5 min : analyse sur `logs/flux_brut/` avant tout changement.
