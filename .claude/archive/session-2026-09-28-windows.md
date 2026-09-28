# SESSION — État courant

## 2026-09-28 — PC Windows (historique : `.claude/archive/`)

### Objectif
Import des transferts Mac, recalcul historique, reconstruction horaires GTFS.

### Avancement
- 13 transferts importés (15→27/09), 2 ignorés (13, 14 — relabel déjà appliqué).
- Recalcul historique complet (159 jours) — base Windows alignée sur les poids actuels.
- Horaires GTFS reconstruits (fenêtre 24/09→26/10) — RER A et B OK.
- Export `transferts/incidents-2026-09-28.json` (157 incidents).
- Serveur relancé, scheduler actif (5 min RT, 20 min perturbations).

### Blocages
- **Clé PRIM toujours à régénérer** (en clair dans l'historique git).
- Arrêts sautés (B) et trains absents (D) toujours en observation.

### Prochaine étape
1. Régénérer la clé PRIM.
2. Observer les logs (arrêts sautés B, trains absents D) sur quelques jours.
3. Valider la maquette `frontend/carte.html` et reprendre le plan X/Instagram.
