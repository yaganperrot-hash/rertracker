# SESSION — État courant

## 2026-09-20 — PC Windows (historique : `.claude/archive/`)

### Objectif
Collecte continue + régénération des données statiques (GTFS, fréquentation, recalcul historique).

### Avancement
- `git pull` OK (`cb5f521`). 304 tests verts.
- Export 19/09 (740 incidents) et 20/09 (600 incidents).
- Données statiques régénérées : offre GTFS (fenêtre 17/09 -> 19/10), fréquentation (0 inconnues),
  horaires Mon trajet (33 773 trains), recalcul 151 jours (23/04 -> 20/09).
- Bug 23 (pastille picker) : résolu (non reproductible). Bugs B/C/D/E : résolus ou observation passive.
- Fix cp1252 : caractères Unicode (`->`, `·`) remplacés dans les `print()` de `offre.py`.
- Serveur actif, collecte du 20/09 en cours.

### Blocages
- Clé PRIM toujours à régénérer (commit `c591442`).
- Validation des arrêts sautés nécessite des données terrain.

### Prochaine étape
1. Déploiement VPS (Docker, accès mobile).
2. Vérification croisée sur un trajet réel avant publication.
3. Fenêtre de mesure 10 -> 5 min, Mon trajet aller-retour.
