# SESSION — 2026-09-25 — PC Windows

## Objectif
Reprise Windows : importer les données Mac (22→25/09), relancer la collecte.

## Avancement
- `git pull --ff-only` OK (d2449b3 → ace70fd) : 19 fichiers, dont collector.py, recalcul.py, transfert.py,
  tests, exports Mac 24-25/09, horaires reconstruits, bugs 45/46/B/C corrigés.
- Réétiquetage Transilien déjà appliqué : 13 et 14/09 ignorés.
- `incidents-2026-09-24.json` importé (1 457 incidents, 31 suppressions levées).
- `incidents-2026-09-25.json` importé (1 034 incidents).
- `POLLING_INTERVAL_MINUTES=5` OK.
- Serveur lancé, scheduler opérationnel.
- Export `transferts/incidents-2026-09-25.json` (1 266 incidents, fusion Mac + Windows).

## Blocages
- Clé PRIM toujours à régénérer (commit `c591442`).

## Prochaine étape
1. Régénérer la clé PRIM.
2. Observer les arrêts sautés (B) quelques jours.
3. Plan de déploiement VPS.
