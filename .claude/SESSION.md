# SESSION — État courant

## 2026-10-05 — Windows (historique : `.claude/archive/`)

### Objectif
Améliorer la précision du calcul et reconstruire les données GTFS périmées.

### Avancement
- Session courte : /start + /wrap, pas de code écrit.
- Serveur lancé sur ce PC, collecte active (quota PRIM 998/1 000 Estimated Timetable).
- Dernier incident en base : 2026-10-05 07:09 (Paris), 27 443 incidents au total.
- **Horaires GTFS périmés sur les 13 lignes** : warning à chaque relevé, « Mon trajet » cassé.

### Blocages
- **Horaires GTFS périmés** : `python -m backend.offre horaires` à relancer (les `trip_id` ont changé).
- **Clé PRIM toujours à régénérer** (en clair dans l'historique git, commit `c591442`).
- **Recalcul historique Windows** pas encore fait (anciens poids horaires).

### Prochaine étape
1. Reconstruire les horaires GTFS (`python -m backend.offre horaires`).
2. Recalculer l'historique Windows (`python -m backend.recalcul`).
3. Observer les trains absents du flux (D).
4. Régénérer la clé PRIM.

### Serveur
- Un serveur tourne **sur ce PC (Windows)** — lancé dans cette session Claude Code (tâche de fond, sera tué à la fermeture de la session). À relancer manuellement si besoin.
