# SESSION — État courant

## 2026-09-29 — Windows (historique : `.claude/archive/`)

### Objectif
Serveur unique sur Windows, bases Mac et Windows fusionnées, collecte en cours.

### Avancement
- **Bases fusionnées** : imports Mac 25→28/09 (1 395 + 686 + 477 + 650) + export fusionné 28/09 (799) importés sur
  Windows. Recalcul historique complet (160 jours). Les deux PC affichent les mêmes chiffres.
- **Récaps fusionnés** : `publications/2026-09-{25,26,27}.txt` réécrits avec les données fusionnées
  (25/09 : 1 357 · 853 163 € ; 26/09 : 809 · 484 100 € ; 27/09 : 514 · 147 177 €).
- **Horaires GTFS reconstruits** : `python -m backend.offre horaires` — fenêtre 25/09 → 27/10, warning
  « Horaires GTFS périmés » résolu pour RER A et B.
- **Serveur Windows lancé** : premier relevé OK (71 retards, 2 suppressions). Quotas PRIM 998/999.
- Export du jour : `transferts/incidents-2026-09-29.json` (164 incidents).

### Blocages
- **Clé PRIM toujours à régénérer** (en clair dans l'historique git, commit `c591442`).

### Prochaine étape
1. Régénérer la clé PRIM.
2. Observer les logs arrêts sautés (B) et trains absents (D) sur quelques jours.
3. Valider la maquette `frontend/carte.html`, puis reprendre le plan X/Instagram.
