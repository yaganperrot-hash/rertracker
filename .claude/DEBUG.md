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

## Bugs résolus — Session 2026-09-10

### [2026-09-10] Bug 12 — Un même train compté une fois par gare
**Fichier(s)** : `backend/collector.py` (`collect_rt_delays`)
**Symptôme** : liste d'incidents pleine de retards quasi identiques sur la même ligne ; sur un appel RER D,
45 départs RT pour 28 trains distincts
**Cause** : `/lines/{id}/departures` renvoie les prochains départs de *toutes* les gares ; la clé
`rt_{vj_id}_{base_departure_date_time}` changeait à chaque gare → un incident par gare desservie
**Fix** : clé par train et par jour (`rt_{vj}_{AAAAMMJJ}`), pire retard du relevé conservé ; d'un relevé à
l'autre l'upsert garde `GREATEST(duree_minutes)` et la gare/l'heure associées (`CASE`)
**Status** : ✅ Résolu

### [2026-09-10] Bug 13 — Identifiant de train instable (suffixe `:RealTime:`)
**Fichier(s)** : `backend/collector.py`
**Symptôme** : après le fix du bug 12, encore 781 lignes pour 202 trains réels ; fausses suppressions
**Cause** : l'id `vehicle_journey:IDFM:TN:SNCF:<uuid>:RealTime:<uuid>` change de suffixe à chaque mise à
jour temps réel PRIM → nouveau train à chaque relevé, et l'ancien id « disparaît » (→ faux « SUPPRIMÉ »)
**Fix** : `train_id = vj_id.split(":RealTime:")[0]` dans la clé. Base fusionnée par la migration n° 2
(sauvegarde `incidents_backup_20260910b`)
**Status** : ✅ Résolu

### [2026-09-10] Bug 14 — `heure_theorique` décalée de +2 h
**Fichier(s)** : `backend/collector.py`
**Symptôme** : train relevé à 10:06 enregistré « prévu 12:02 »
**Cause** : `base_departure_date_time` / `departure_date_time` sont en heure locale de Paris mais étaient
lus avec `tzinfo=timezone.utc`. Le retard (différence des deux) restait juste.
**Fix** : `.replace(tzinfo=PARIS_TZ).astimezone(timezone.utc)`. Base corrigée par la migration n° 1
(sauvegarde `incidents_backup_20260910`)
**Status** : ✅ Résolu

### [2026-09-10] Bug 15 — Détection des suppressions : trains partis marqués « SUPPRIMÉ »
**Fichier(s)** : `backend/collector.py`
**Symptôme** : faux trains supprimés (3 le 2026-09-10) ; masqué jusque-là par le bug 14, qui repoussait
de 2 h l'entrée dans la fenêtre de détection
**Cause** : le fix du bug 6 considérait « disparu du flux avec heure prévue passée » comme supprimé — or
tout train parti ou arrivé au terminus disparaît aussi
**Fix** : supprimé seulement si disparu *avant* son départ attendu (`heure_theorique + duree_minutes >
now + 2 min`) ; l'upsert remet `is_cancelled=False` si le train réapparaît
**Status** : ✅ Résolu

### [2026-09-10] Bug 16 — Aucune info sur les retards temps réel
**Fichier(s)** : `backend/collector.py`, `backend/models.py`, `backend/database.py`, `backend/api.py`, `frontend/index.html`
**Symptôme** : affichage « Retard de 6 min (temps réel) · DELAY_REALTIME · à 09:51 » — ni gare, ni train,
ni direction ; heure affichée = heure du relevé
**Cause** : `stop_point.name`, `display_informations.direction` et `headsign` ignorés par le collecteur
**Fix** : colonnes `gare`, `direction`, `mission` (+ `ALTER TABLE … IF NOT EXISTS` dans `init_db()`) ;
frontend « Gare → Direction » / « Train XXXX · départ prévu HH:MM »
**Status** : ✅ Résolu

### [2026-09-10] Texte du frontend peu lisible
**Fichier(s)** : `frontend/index.html`
**Symptôme** : textes en gris clair, 7-9 px, graisse 300 ; note SMIC écrite avec la couleur des bordures (`#D4CFC7`)
**Fix** : texte principal `#000`, `--muted #555`, `--sub #333`, base 16 px, libellés 11-13 px, graisse 300 supprimée
**Status** : ✅ Résolu (page d'accueil uniquement — `stats.html` et `methode.html` pas encore traitées)

### [2026-09-10] Minutes-voyageurs illisibles (« 2 847 340 minutes »)
**Fichier(s)** : `frontend/duree.js` (nouveau), `frontend/index.html`, `frontend/stats.html`, `backend/bot.py`
**Symptôme** : chiffres en millions de minutes (ou « 23,8 M min-voy. ») — aucun ordre de grandeur perceptible
**Cause** : affichage brut de l'unité de calcul
**Fix** : unité adaptative composée (min → h → jours → ans, bascule à 2× l'unité suivante), accord
perdues/perdus, libellé « de vie perdus collectivement » ; même logique JS (`formatDuree`) et Python
(`_fmt_duree`), testée dans `tests/test_bot.py`. Stockage toujours en minutes.
**Status** : ✅ Résolu (rendu navigateur non vérifié visuellement)

### [2026-09-10] Serveur local arrêté
**Fichier(s)** : —
**Symptôme** : http://127.0.0.1:8000 ne répond plus, aucun process uvicorn ; PostgreSQL toujours actif
**Cause** : uvicorn tournait en tâche de fond d'une session Claude Code → meurt avec elle (ou tué par le système)
**Fix** : relancé ; pour un serveur durable, le lancer dans son propre terminal
(`./venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`)
**Status** : ✅ Contourné

---

## Bugs ouverts

### [2026-09-10] Bug 17 — Horaires des perturbations probablement lus en UTC
**Fichier(s)** : `backend/collector.py` (`_parse_dt`, utilisé par `collect_disruptions`)
**Symptôme** : non observé directement
**Cause probable** : même erreur que le bug 14 — `_parse_dt` applique `tzinfo=timezone.utc` aux
`application_periods` Navitia, vraisemblablement en heure de Paris. Fausserait `heure_debut`/`heure_fin`
des perturbations et le filtre « incidents de nuit » (< 7 h)
**Fix** : à vérifier sur un payload `line_reports` réel, puis lire en `Europe/Paris`
**Status** : ❌ Ouvert

### [2026-09-10] Bug 9 — HOURLY_WEIGHTS somme à 19.2 au lieu de 18.0
**Fichier(s)** : `backend/metrics.py:34`
**Symptôme** : `test_weights_sum_to_18` échoue — `Weights sum to 19.2, expected 18.0`
**Cause** : le fix du bug 7 (profil horaire) suppose une somme de 18.0 pour que le poids moyen
vaille 1.0 et que `voyageurs_jour * weight / 18` conserve le total journalier. La table des
18 poids somme en réalité à 19.2.
**Impact** : **toutes les minutes-voyageurs sont surestimées d'environ 6,7 %**, et donc les euros
affichés sur le frontend et dans le tweet quotidien aussi. Les 193 318 min-voyageurs mesurées le
2026-09-10 valent en réalité ~181 300.
**Fix** : à trancher — soit normaliser dynamiquement (`weight / sum(HOURLY_WEIGHTS.values()) * 18`),
soit rééquilibrer les 18 valeurs à la main pour retomber sur 18.0. La 1ʳᵉ option est robuste aux
futurs ajustements du profil.
**Status** : ❌ Ouvert

### [2026-09-10] Bug 10 — 5 tests collector obsolètes vs le code qui marche
**Fichier(s)** : `tests/test_collector.py`
**Symptôme** : 5 échecs — `test_pr_base_url_correct`, `test_parse_disruptions_depuis_reponse`,
`test_disruption_has_source_disruption`, `test_rt_delay_has_source_realtime`,
`test_rt_delay_has_is_cancelled_false` (`test_disappeared_train_marked_cancelled` réécrit et
corrigé avec le bug 15 : `MagicMock` au lieu d'`AsyncMock` pour la réponse HTTP)
**Cause** : dérive test/code, pas un bug applicatif — la collecte PRIM réelle fonctionne
(75 incidents collectés le 2026-09-10). Ex. : `test_pr_base_url_correct` attend une base URL
finissant par `navitia` alors que le code utilise `.../v2/navitia/line_reports` (corrigé en
2026-04-28 sans mettre le test à jour). Les autres échouent sur des mocks async qui ne
déclenchent plus `execute()` (`coroutine 'AsyncMockMixin._execute_mock_call' was never awaited`).
**Fix** : réaligner les assertions et les mocks sur le collecteur actuel.
**Status** : ❌ Ouvert

### [2026-04-28] Transilien L, N, P — 404 sur PRIM
**Fichier(s)** : `backend/collector.py` (LIGNES_CIBLES)
**Symptôme** : `404 Not Found` sur certains IDs Navitia
**Cause** : IDs Navitia incorrects pour ces lignes dans la couverture PRIM
**Fix** : IDs corrigés par le commit `7adb7e3` — **plus aucun 404 dans les logs** au 2026-09-10
**Status** : 🔄 En cours — à requalifier

### [2026-09-10] Bug 11 — Transilien L, N, P, R remontent 0 incident
**Fichier(s)** : `backend/collector.py` (LIGNES_CIBLES)
**Symptôme** : sur la collecte du 2026-09-10, H, J, K et U remontent des incidents mais
L, N, P et R sont à zéro (`/api/stats/line/TRANSILIEN_L?period=1` → `total_incidents: 0`)
**Cause** : inconnue. Ce n'est plus le 404 du bug précédent (aucune erreur au log), donc soit
c'est légitime (pas de perturbation sur ces lignes à cet instant), soit l'appel renvoie 200
avec un payload vide. 4 lignes à zéro simultanément reste suspect.
**Fix** : à investiguer — logger le payload brut PRIM pour ces 4 lignes et comparer à H/J/K/U
**Status** : ❌ Ouvert

### [2026-09-10] Clé PRIM en clair dans l'historique git
**Fichier(s)** : `PRIM_KEY.txt` (commit `c591442`)
**Symptôme** : la clé API PRIM est lisible en clair dans le dépôt
**Cause** : transport volontaire de la clé vers une autre machine — le portail PRIM masque
partiellement la clé, donc impossible de la relire à l'arrivée
**Fix** : supprimer `PRIM_KEY.txt` après récupération **et régénérer la clé côté portail PRIM** —
un `git rm` ne la retire pas de l'historique (elle reste dans `c591442`)
**Status** : ❌ Ouvert — action requise

---

## Notes de surveillance
- Quota PRIM : 20 000 req/jour — polling 5 min = 288 req/jour (marge x69)
- Bot X : planifié à 20h via APScheduler dans `main.py`
- Logs applicatifs : `logs/` (monté en volume Docker)
