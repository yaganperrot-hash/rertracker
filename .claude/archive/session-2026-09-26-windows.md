# SESSION — État courant

## 2026-09-25 — PC Windows (historique : `.claude/archive/`)

### Objectif
Reprise Windows : importer les données Mac, relancer la collecte, avancer sur les bugs restants.

### Avancement
- `git pull` OK (ace70fd) : bugs 45/46/B/C corrigés côté Mac, horaires reconstruits, nouveaux tests.
- Transferts 24/09 (1 457) et 25/09 (1 034) importés depuis le Mac, 31 suppressions levées.
- Serveur lancé, scheduler actif (temps réel 5 min, perturbations 20 min).
- Export `transferts/incidents-2026-09-25.json` (1 266 incidents, fusion Mac + Windows).

### Blocages
- **Clé PRIM toujours à régénérer** (en clair dans l'historique git, commit `c591442`).

### Prochaine étape
1. Régénérer la clé PRIM (portail PRIM, puis `.env`).
2. Arrêts sautés (B) : observer les logs, puis décider s'ils entrent dans le coût.
3. Reconstruire `data/horaires.json.gz` dès que le warning « Horaires GTFS périmés » réapparaît.
4. Plan de déploiement VPS.
