# SESSION — État courant

## 2026-09-17 (après-midi) — PC Mac (historique : `.claude/archive/`)

### Objectif
Suivre les trains de plus près sans dépasser les quotas PRIM, et ne compter que des retards mesurés.

### Avancement
- **Collecte temps réel toutes les 5 min en un seul appel** (`LineRef=ALL`, 4,5 Mo compressés, 52 Mo de JSON,
  ~4 h 30 d'horizon), filtré sur les 13 lignes : 216 req/jour Estimated Timetable au lieu de 702. Perturbations
  Navitia sur leur propre cadence (20 min, 108 req/jour). Pas de relevé au redémarrage si le dernier date de moins
  d'un intervalle. Commit `5bb85bf`, en service depuis 12 h 18 : 1 requête par relevé vérifiée dans les en-têtes.
- **Fenêtre de mesure de 10 min** : retard et suppression d'un arrêt comptés seulement à moins de 10 min du passage
  estimé ; un train déjà en base sans retard dans la fenêtre voit ses arrêts mis à jour.
- Tests de quota : l'API « Prochains passages » (une requête par gare) a aussi 1 000 req/jour → écartée.
- Transferts du 15, 16 et 17 importés sur le Mac, recalcul fait. `.env` : `POLLING_INTERVAL_MINUTES=5`.
- **Coupure Viroflay (≈ 9 h 40 → 13 h, RER C / N / U)** : trains bloqués jusqu'à 198 min (SICA, VERI, PORO).
  Pris d'abord pour des fantômes, puis vérifiés réels (reprise de marche après la coupure). Aucune correction
  (décision utilisateur : ne rien toucher). 282 tests verts.

### Blocages
- Clé PRIM toujours à régénérer (commit `c591442`).
- Le 17/09 mélange deux méthodes (20 min jusqu'à 12 h 18, puis 5 min + fenêtre) : non comparable aux jours d'avant.

### Prochaine étape
1. **PC Windows** : `git pull`, serveur arrêté, `POLLING_INTERVAL_MINUTES=5` dans `.env`, importer
   `transferts/incidents-2026-09-17.json`, `python -m backend.recalcul`, relancer. Un seul serveur à la fois.
2. Après une journée complète à 5 min : ajuster la fenêtre de 10 min sur les archives (retard annoncé à 30 / 20 / 10 / 5 min
   du passage comparé au retard final) ; surveiller `logs/flux_brut/` (~440 Ko par relevé) et `compute_daily_metrics`.
3. Valider B (arrêts sautés) sur les archives à 5 min ; soupçons C, D (ligne K vide côté PRIM), E.
4. Filtre anti-fantôme : écarte des trains réellement bloqués — à rediscuter avant toute modification.
