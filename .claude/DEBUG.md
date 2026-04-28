# DEBUG — Compteur de Retards IDF

## Format d'entrée
```
### [DATE] Titre court
**Fichier(s)** : path/to/file.py
**Symptôme** : ce qui se passe
**Cause** : pourquoi
**Fix** : ce qui a été fait
**Status** : ✅ Résolu | 🔄 En cours | ❌ Bloqué
```

---

## Bugs résolus

### [2026-03-11] pydantic-settings manquant
**Fichier(s)** : `requirements.txt`, `backend/config.py`
**Symptôme** : `ImportError: cannot import name 'BaseSettings' from 'pydantic'`
**Cause** : Pydantic v2 a sorti `BaseSettings` dans un package séparé `pydantic-settings`
**Fix** : Ajout de `pydantic-settings` dans `requirements.txt`
**Status** : ✅ Résolu

### [2026-03-11] DATABASE_URL incompatible asyncpg
**Fichier(s)** : `backend/database.py`
**Symptôme** : SQLAlchemy async refuse le préfixe `postgresql://`
**Cause** : asyncpg nécessite le driver `postgresql+asyncpg://`
**Fix** : Conversion automatique du préfixe dans `database.py` au runtime
**Status** : ✅ Résolu

---

## Bugs ouverts

_(aucun pour l'instant)_

---

## Bugs résolus (suite — session 2026-04-28)

### [2026-04-28] Incidents planifiés (1 an) polluaient les métriques journalières
**Fichier(s)** : `backend/collector.py`, `backend/metrics.py`
**Symptôme** : `total_duree_min = 92 millions`, `minutes_voyageurs = milliards`
**Cause** : PRIM retourne des modifications de service sur 1 an (`duree_minutes = 525 600`). Filtre `status=active` insuffisant.
**Fix** : Triple filtre dans collector — `heure_debut <= now`, heure Paris >= 7h, `duree_minutes <= 720`. Fenêtre metrics : 07h00 Paris → NOW.
**Status** : ✅ Résolu

### [2026-04-28] duree_minutes jamais calculée → stats toujours à 0
**Fichier(s)** : `backend/collector.py`
**Symptôme** : "0 Incidents ce jour" affiché même avec des incidents actifs dans la liste
**Cause** : `duree_minutes` n'était pas incluse dans le `.values()` ni dans le `set_` du upsert. `compute_daily_metrics` filtrant sur `duree_minutes.isnot(None)`, aucun incident n'était jamais comptabilisé.
**Fix** : Calcul de `duree_minutes = (heure_fin - heure_debut).total_seconds() / 60` dès que les deux dates sont connues, inclus dans insert et upsert.
**Status** : ✅ Résolu

---

## Bugs résolus (suite)

### [2026-04-28] Endpoint PRIM incorrect — URL complète erronée
**Fichier(s)** : `backend/collector.py`
**Symptôme** : Base vide, 0 incidents collectés malgré clé API valide
**Cause** : L'endpoint `/marketplace/disruptions/` n'existe pas. Le swagger indique `basePath=/marketplace/v2/navitia/line_reports` + `/{uri}/line_reports`. URL correcte : `/marketplace/v2/navitia/line_reports/lines/{navitia_id}/line_reports`
**Fix** : Boucle sur chaque ligne de `LIGNES_CIBLES`, appel individuel par ligne
**Status** : ✅ Résolu

### [2026-04-28] Incidents planifiés (1 an) polluaient les métriques journalières
**Fichier(s)** : `backend/collector.py`, `tests/test_collector.py`
**Symptôme** : Le collector appelait `/marketplace/disruptions/` qui n'existe pas dans le swagger PRIM
**Cause** : L'API PRIM est documentée sous `/marketplace/v2/navitia/line_reports`, pas `/disruptions/`
**Fix** :
- `PRIM_BASE_URL` → `…/marketplace/v2/navitia`
- Endpoint → `/line_reports`
- Ajout de `disable_geojson=true` dans les params
- Tests mis à jour (6 nouveaux tests dans `TestCollectDisruptions`)
**Status** : ✅ Résolu

---

### [2026-04-28] Transilien L, N, P — 404 sur PRIM
**Fichier(s)** : `backend/collector.py` (LIGNES_CIBLES)
**Symptôme** : `404 Not Found` sur `/lines/line:IDFM:C01732/`, `/C01733/`, `/C01734/`
**Cause** : Ces IDs Navitia ne correspondent pas aux lignes Transilien dans la couverture PRIM
**Fix** : À investiguer — vérifier les bons IDs via l'API PRIM ou le référentiel IDFM
**Status** : ❌ Ouvert

### [2026-04-28] Formule euros frontend — division par 60 en double
**Fichier(s)** : `frontend/index.html`
**Symptôme** : Total €  affichait ~9 400 € au lieu de ~563 000 € (mock)
**Cause** : `minutes * 0.198 / 60` — `0.198` est déjà `11.88/60`, donc `/60` en double
**Fix** : `minutes * 0.198` (suppression du `/60`)
**Status** : ✅ Résolu

### [2026-04-28] mockLines hardcodé, jamais remplacé par l'API
**Fichier(s)** : `frontend/index.html`
**Symptôme** : Tableau "Toutes les lignes" affichait des données inventées
**Fix** : `fetchLinesStats()` — `Promise.allSettled` sur `/api/stats/line/{id}?period=1` pour les 13 lignes
**Status** : ✅ Résolu

---

## Notes de surveillance
- Quota PRIM : 20 000 req/jour — polling 5 min ≈ 288 req/jour (marge ×69)
- Bot X : planifié à 20h via APScheduler dans `main.py`
- Logs applicatifs : `logs/` (monté en volume Docker)
