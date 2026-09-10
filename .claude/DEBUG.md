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

## Bugs résolus — Session 2026-03-11

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

## Bugs résolus — Session 2026-04-28

### [2026-04-28] Endpoint PRIM incorrect
**Fichier(s)** : `backend/collector.py`
**Symptôme** : Base vide, 0 incidents collectés
**Cause** : `/marketplace/disruptions/` n'existe pas. Correct : `/marketplace/v2/navitia/line_reports/lines/{id}/line_reports`
**Fix** : Boucle sur chaque ligne de `LIGNES_CIBLES`, appel individuel
**Status** : ✅ Résolu

### [2026-04-28] duree_minutes jamais calculée
**Fichier(s)** : `backend/collector.py`
**Symptôme** : Stats toujours à 0 malgré des incidents actifs
**Cause** : `duree_minutes` absente du `.values()` et `set_` du upsert
**Fix** : Calcul `(heure_fin - heure_debut).total_seconds() / 60`, inclus dans insert et upsert
**Status** : ✅ Résolu

### [2026-04-28] Incidents planifiés (1 an) polluaient les métriques
**Fichier(s)** : `backend/collector.py`, `backend/metrics.py`
**Symptôme** : `total_duree_min = 92 millions`
**Cause** : PRIM retourne des modifications de service sur 1 an
**Fix** : Triple filtre — `heure_debut <= now`, heure Paris >= 7h, `duree_minutes <= 720`
**Status** : ✅ Résolu

### [2026-04-28] Formule euros frontend — division par 60 en double
**Fichier(s)** : `frontend/index.html`
**Symptôme** : Total euros 60x trop bas
**Cause** : `0.198` est déjà `11.88/60`, `/60` appliqué en double
**Fix** : `minutes * 0.198` (suppression du `/60`)
**Status** : ✅ Résolu

---

## Bugs résolus — Session 2026-09-09

### [2026-09-09] Bug 1 — Double comptage disruptions + RT
**Fichier(s)** : `backend/metrics.py`, `backend/collector.py`, `backend/models.py`
**Symptôme** : Métriques surestimées — même événement compté 2 fois (disruption + retard RT)
**Cause** : Pas de distinction entre sources, tout agrégé ensemble
**Fix** : Ajout colonne `source` ("disruption"/"realtime"), seuls les RT comptent pour durée/MV, disruptions comptées séparément
**Status** : ✅ Résolu

### [2026-09-09] Bug 2 — duree_expr ignorait duree_minutes stocké
**Fichier(s)** : `backend/metrics.py`
**Symptôme** : Durées recalculées via timestamps même quand `duree_minutes` était renseigné
**Cause** : `duree_expr` SQL faisait `extract(epoch, heure_fin - heure_debut)` sans vérifier `duree_minutes`
**Fix** : Priorité `duree_minutes` > timestamp diff > cap 180 min (via `_effective_duration()`)
**Status** : ✅ Résolu

### [2026-09-09] Bug 3 — Heure théorique de départ perdue
**Fichier(s)** : `backend/models.py`, `backend/collector.py`
**Symptôme** : Impossible de savoir l'heure prévue du train
**Cause** : `base_departure_date_time` utilisé puis jeté
**Fix** : Ajout colonne `heure_theorique`, stockée dans `collect_rt_delays`
**Status** : ✅ Résolu

### [2026-09-09] Bug 4 — Timezone UTC au lieu de Paris
**Fichier(s)** : `backend/metrics.py`, `backend/bot.py`
**Symptôme** : Mauvais jour calculé entre 22h-00h UTC (= 00h-02h Paris)
**Cause** : `date.today()` utilise le fuseau système (UTC sur serveur)
**Fix** : `datetime.now(ZoneInfo("Europe/Paris")).date()` partout
**Status** : ✅ Résolu

### [2026-09-09] Bug 5 — Incidents ouverts sans limite de durée
**Fichier(s)** : `backend/metrics.py`
**Symptôme** : Un incident sans `heure_fin` pouvait accumuler des heures de durée
**Cause** : `func.now() - heure_debut` sans borne
**Fix** : Cap à `MAX_OPEN_DURATION_MIN = 180` minutes
**Status** : ✅ Résolu

### [2026-09-09] Bug 6 — Trains supprimés invisibles
**Fichier(s)** : `backend/collector.py`, `backend/models.py`
**Symptôme** : Trains annulés jamais détectés, sous-estimation des perturbations
**Cause** : Pas de mécanisme de détection des suppressions
**Fix** : Comparaison flux RT vs incidents BDD récents — trains disparus avec `heure_theorique` passée marqués `is_cancelled=True`
**Status** : ✅ Résolu

### [2026-09-09] Bug 7 — Fréquentation uniforme sur toute la journée
**Fichier(s)** : `backend/metrics.py`
**Symptôme** : Un retard de 10 min à 8h (pointe) comptait autant qu'à 14h (creux)
**Cause** : `voyageurs_jour / 18 / 60` = moyenne plate
**Fix** : Profil horaire (18 poids, somme=18.0) — ex: 8h=2.5, 14h=0.7, nuit=0
**Status** : ✅ Résolu

### [2026-09-09] Bug 8 — Compteur frontend fake (random)
**Fichier(s)** : `frontend/index.html`
**Symptôme** : Le compteur de minutes s'incrémente aléatoirement toutes les 2.8s
**Cause** : `setInterval(() => { minutes += Math.floor(Math.random() * 45) + 10; }, 2800)`
**Fix** : Remplacé par polling réel toutes les 5 minutes (`fetchLiveData()` + `fetchLinesStats()`)
**Status** : ✅ Résolu

---

## Bugs ouverts

### [2026-04-28] Transilien L, N, P — 404 sur PRIM
**Fichier(s)** : `backend/collector.py` (LIGNES_CIBLES)
**Symptôme** : `404 Not Found` sur certains IDs Navitia
**Cause** : IDs Navitia incorrects pour ces lignes dans la couverture PRIM
**Fix** : À investiguer — vérifier les bons IDs via l'API PRIM ou le référentiel IDFM
**Status** : ❌ Ouvert

---

## Notes de surveillance
- Quota PRIM : 20 000 req/jour — polling 5 min = 288 req/jour (marge x69)
- Bot X : planifié à 20h via APScheduler dans `main.py`
- Logs applicatifs : `logs/` (monté en volume Docker)
