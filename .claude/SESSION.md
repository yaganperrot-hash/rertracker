# SESSION — État courant

## 2026-09-27 — PC Windows (historique : `.claude/archive/`)

### Objectif
Session courte : relance du serveur Windows, vérification des stats du jour, export transfert.

### Avancement
- Serveur lancé, scheduler actif.
- Stats du jour : 8 incidents, 3 660 min-voyageurs, 749 €, 3 lignes perturbées (RER B, RER D, Transilien H).
- Export `transferts/incidents-2026-09-27.json` (309 incidents).

### Blocages
- **Clé PRIM toujours à régénérer** (en clair dans l'historique git).
- **Horaires GTFS à reconstruire** (`python -m backend.offre horaires`) — RER A et B sans correspondance GTFS.

### Prochaine étape
1. Reconstruire `data/horaires.json.gz` (horaires GTFS).
2. Régénérer la clé PRIM.
3. Arrêts sautés (B) : observer les logs.
4. Optionnel : ajouter la valeur du temps DGITM comme alternative au SMIC sur la page Méthode.
