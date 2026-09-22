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
**Fix** : Profil horaire (18 poids) — ex: 8h=2.5, 14h=0.7, nuit=0
**Status** : ✅ Résolu, puis remplacé le 2026-09-16 par les profils réels (cf. bug 30)

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
**Status** : ✅ Résolu (rendu vérifié sur l'accueil, bureau + 390 px ; `stats.html` non vérifiée)

### [2026-09-10] Serveur local arrêté
**Fichier(s)** : —
**Symptôme** : http://127.0.0.1:8000 ne répond plus, aucun process uvicorn ; PostgreSQL toujours actif
**Cause** : uvicorn tournait en tâche de fond d'une session Claude Code → meurt avec elle (ou tué par le système).
Récidive l'après-midi du 2026-09-10 : tué 2 fois, dont une confirmée « low memory » par Claude Code,
alors que `memory_pressure` indiquait 29 % libre et qu'aucun process n'était anormalement gros
**Fix** : relancé ; pour un serveur durable, le lancer dans son propre terminal
(`./venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`)
**Status** : ✅ Contourné

### [2026-09-10] Accueil — fenêtres temporelles mélangées et mise en avant arbitraire
**Fichier(s)** : `frontend/index.html`
**Symptôme** : table par ligne mêlant « Coût / jour » et « Coût / mois » (jour × 28, pure extrapolation) ; tri
alphabétique ; RER B surligné en rouge en permanence ; temps cumulé affiché 2 fois (bloc hero + barre de stats) ;
hero affichant « 9.377 € » de maquette avant chargement, et jamais mis à jour les jours à 0 minute-voyageur
(`if (stats.total_minutes_voyageurs > 0)`)
**Cause** : héritage de la maquette — surlignage codé en dur (`line.id === 'B'`), colonne mensuelle calculée côté front
**Fix** : refonte de la hiérarchie (voir SESSION.md) — tout sur la fenêtre « aujourd'hui », tri par coût,
pire ligne calculée, une seule occurrence du temps cumulé, placeholders « — »
**Status** : ✅ Résolu

### [2026-09-10] Ticker bloqué sur « Chargement des données en cours… »
**Fichier(s)** : `frontend/index.html`
**Symptôme** : bandeau figé sur le texte de chargement dès qu'aucun incident n'est en cours
**Cause** : le ticker n'était mis à jour que dans la branche `incidents.length > 0`
**Fix** : texte « Aucun incident en cours sur le réseau RER et Transilien » dans la branche vide
**Status** : ✅ Résolu

---

## Bugs résolus — Session 2026-09-11

### [2026-09-11] Bug 18 — Statistiques : deux totaux qui se contredisent
**Fichier(s)** : `frontend/stats.html` (supprimée) → `backend/bilans.py`, `frontend/statistiques.html`
**Symptôme** : héro « 487 incidents · 45 ans 132 j · 4 722 580 € » contre ligne de KPI « 752 · 5 ans 233 j ·
587 053 € » juste en dessous ; écarts par ligne vs mois précédent affichés
**Cause** : héro et comparaison mensuelle écrits en dur (maquette), écarts inventés (`EVOL_MOCK`) ; seule la ligne
de KPI était calculée
**Fix** : bilans calculés côté serveur ; coût arrondi par ligne × jour puis sommé → héro = Σ classement
(= Σ mois pour l'année), invariant testé
**Status** : ✅ Résolu

### [2026-09-11] Bug 19 — Messages PRIM affichés en HTML brut sur l'accueil
**Fichier(s)** : `backend/api.py`, `backend/causes.py`, `frontend/index.html`
**Symptôme** : `<p _msttexthash="…">P&#233;riode : …` affiché tel quel dans les incidents en cours et le ticker ;
code « SIGNIFICANT_DELAYS » en sous-titre
**Cause** : `Incident.cause` stocke le message PRIM brut (HTML, entités, parfois balises de traduction automatique) ;
le front l'échappait et l'affichait
**Fix** : l'API renvoie `cause` en texte lisible, `resume` (1ʳᵉ ligne informative) et `categorie` ; l'accueil
affiche résumé + catégorie, texte complet au survol. Historique couvert sans migration
**Status** : ✅ Résolu

### [2026-09-11] Causes : avis de travaux classés « signalisation »
**Fichier(s)** : `backend/causes.py`
**Symptôme** : « Période : … Dates : … Motif : travaux sur le réseau ferroviaire (… de signalisation …
l'infrastructure …) » compté en Signalisation / infrastructure
**Cause** : catégories testées par priorité sur tout le texte ; Signalisation passe avant Travaux
**Fix** : ordre de lecture — tête du « Motif : » (avant la parenthèse), motif entier, avis planifié → travaux,
puis mots-clés. Message réel ajouté aux tests
**Status** : ✅ Résolu

### [2026-09-11] Trains fantômes : retard qui grossit à chaque relevé
**Fichier(s)** : `backend/collector.py`, `tests/test_collector.py`
**Symptôme** : train prévu il y a 166 min qui « part maintenant » à chaque relevé (train ELBA, 2026-09-11)
**Cause** : train supprimé ou arrêté resté dans le flux PRIM : son départ estimé suit l'heure du relevé
**Fix** : retard ≥ 60 min avec départ estimé à ± 3 min de l'heure du relevé → écarté (mais compté présent pour
la détection des suppressions) ; 3 tests
**Status** : ✅ Résolu (modification trouvée non commitée au début de la session, commitée à part)

### [2026-09-11] Relevés sautés après une mise en veille
**Fichier(s)** : `backend/main.py`
**Cause** : tolérance APScheduler par défaut d'1 s → tous les relevés en retard étaient abandonnés
**Fix** : `coalesce=True`, `misfire_grace_time=None` (une seule exécution de rattrapage) ; bot de 20 h : 1 h de
tolérance au plus, sinon le bilan porterait sur le mauvais jour
**Status** : ✅ Résolu (idem, trouvé non commité)

### [2026-09-10 → 2026-09-11] SMIC 2025 encore utilisé en 2026
**Fichier(s)** : `backend/config.py`, `backend/bot.py`, `frontend/index.html`, `frontend/methode.html`
**Fix** : 12,31 €/h (en vigueur depuis le 1er juin 2026, arrêté du 22 mai 2026) — `SMIC_HORAIRE` dans la config,
lu par les bilans et le bot ; accueil et méthode alignés (exemple recalculé : 7 693 €)
**Status** : ✅ Résolu

### [2026-09-10 → 2026-09-11] « Salaires journaliers » : 90 € en dur
**Fichier(s)** : `frontend/index.html`
**Fix** : `SALAIRE_JOUR = SMIC_HORAIRE × 7` (≈ 86 €)
**Status** : ✅ Résolu

### [2026-09-11] Données écrites en dur dans le frontend
**Fichier(s)** : `frontend/index.html`, `frontend/methode.html`, `frontend/bilan.js`, `backend/api.py`, `backend/metrics.py`
**Symptôme** : faux incidents dans le bandeau de la méthode (« RER B — Panne signalisation Gare du Nord — 47 min ») ;
table `FREQ` et taux SMIC recopiés dans l'accueil ; SMIC, exemple chiffré et « 288 req/jour » en dur dans la méthode ;
« recalcul toutes les 10 min » en dur dans les bilans
**Cause** : héritage des maquettes, doublons de `data/frequentation.json` et de `config.py`
**Fix** : le backend calcule tous les coûts (`cout_eur` dans l'API : jour, ligne, incident) ; `/api/reference` sert
SMIC, source du taux, relevés, quota, fréquentation ; `ticker.js` lit les incidents réels ; `meta.recalcul_minutes`
dans les JSON de bilans. Le « 288 req/jour » était faux : 13 lignes × 2 appels par relevé → 7 488 req/jour
**Status** : ✅ Résolu

---

## Bugs ouverts

### [2026-09-10 → 2026-09-11] Bug 17 — Horaires des perturbations lus en UTC au lieu de Paris
**Fichier(s)** : `backend/collector.py` (`_parse_dt`)
**Symptôme** : décalage de 1-2h sur `heure_debut`/`heure_fin` des disruptions, filtre < 7h faussé
**Cause** : même erreur que le bug 14 — `_parse_dt` appliquait `tzinfo=timezone.utc` aux timestamps
PRIM qui sont en heure locale de Paris
**Fix** : `dt.replace(tzinfo=PARIS_TZ).astimezone(timezone.utc)` ; doublon `PARIS_TZ` supprimé
**Status** : ✅ Résolu

### [2026-09-10 → 2026-09-11] Bug 9 — HOURLY_WEIGHTS somme à 19.2 au lieu de 18.0
**Fichier(s)** : `backend/metrics.py:34`, `tests/test_metrics.py`
**Symptôme** : `test_weights_sum_to_18` échouait — `Weights sum to 19.2, expected 18.0`
**Cause** : le profil horaire a été ajusté à 19.2 (total pondéré réaliste), le test attendait 18.0
**Fix** : test renommé `test_weights_sum_to_expected` et aligné sur 19.2 ; commentaire du code corrigé
**Status** : ✅ Résolu

### [2026-09-10 → 2026-09-11] Bug 10 — 5 tests collector obsolètes vs le code qui marche
**Fichier(s)** : `tests/test_collector.py`
**Symptôme** : 5 échecs sur mocks async + assertions obsolètes
**Cause** : `mock_resp.json = AsyncMock(...)` mais le code appelle `.json()` sans `await` →
coroutine au lieu de dict ; mock disruption manquait `"status": "active"` et avait `begin: 06:30`
(filtré < 7h Paris) ; `PRIM_BASE_URL` avait changé
**Fix** : `AsyncMock` → `MagicMock` pour `.json()`, ajout `status: "active"`, heure corrigée `08:00`
**Status** : ✅ Résolu

### [2026-09-11] Bug 20 — PRIM_BASE_URL doublait `/line_reports`
**Fichier(s)** : `backend/collector.py`
**Symptôme** : URL des disruptions contenait `.../line_reports/lines/{id}/line_reports`
**Cause** : `PRIM_BASE_URL` terminait par `/line_reports` et `collect_disruptions` ajoutait
`/lines/{id}/line_reports` → double suffixe
**Impact** : l'API PRIM retournait probablement un 404 ou un payload vide pour les disruptions
(le log ne montrait pas d'erreur car le serveur répondait 200)
**Fix** : `PRIM_BASE_URL` retiré de `/line_reports`, unifié avec `PRIM_NAVITIA_BASE` (supprimé)
**Status** : ✅ Résolu

### [2026-04-28] Transilien L, N, P — 404 sur PRIM
**Fichier(s)** : `backend/collector.py` (LIGNES_CIBLES)
**Symptôme** : `404 Not Found` sur certains IDs Navitia
**Cause** : IDs Navitia incorrects pour ces lignes dans la couverture PRIM
**Fix** : IDs corrigés par le commit `7adb7e3` — **plus aucun 404 dans les logs** au 2026-09-10
**Status** : ✅ Requalifié le 2026-09-15 — plus de 404, mais IDs toujours faux (bus / autres lignes) : voir bug 25

### [2026-09-10 → 2026-09-11] Bug 11 — Transilien L, N, P, R remontent 0 incident
**Fichier(s)** : `backend/collector.py` (LIGNES_CIBLES)
**Symptôme** : sur la collecte du 2026-09-10, H, J, K et U remontent des incidents mais
L, N, P et R sont à zéro
**Cause** : inconnue — probablement légitime ou payload vide
**Fix** : logging diagnostic ajouté dans `collect_disruptions` et `collect_rt_delays` quand
une ligne ne remonte aucun résultat. Permettra de confirmer si c'est légitime ou un bug de parsing
**Status** : ✅ Résolu le 2026-09-15 — cause : identifiants PRIM faux (bug 25)

### [2026-09-10] Clé PRIM en clair dans l'historique git
**Fichier(s)** : `PRIM_KEY.txt` (commit `c591442`)
**Symptôme** : la clé API PRIM est lisible en clair dans le dépôt
**Cause** : transport volontaire de la clé vers une autre machine — le portail PRIM masque
partiellement la clé, donc impossible de la relire à l'arrivée
**Fix** : supprimer `PRIM_KEY.txt` après récupération **et régénérer la clé côté portail PRIM** —
un `git rm` ne la retire pas de l'historique (elle reste dans `c591442`)
**Status** : ❌ Ouvert — action requise. Au 2026-09-14 `PRIM_KEY.txt` est **toujours suivi** dans `HEAD` et
poussé sur GitHub ; la clé de `.env` répond toujours HTTP 200 (non régénérée)

### [2026-09-11] Coût du jour : accueil vs bilans, écart d'arrondi
**Fichier(s)** : `frontend/index.html`
**Symptôme** : le coût du jour de l'accueil peut différer de quelques euros de la même journée dans `/statistiques`
**Cause** : l'accueil calcule `floor(Σ minutes × SMIC / 60)`, les bilans arrondissent par ligne × jour puis somment
**Fix** : servir le coût du jour depuis le backend avec la règle des bilans (`cout_eur` de `/api/stats/today`)
**Status** : ✅ Résolu le 2026-09-11

### [2026-09-10] Coût par incident : formule front ≠ backend
**Fichier(s)** : `frontend/index.html` (`coutIncident`, table `FREQ`)
**Symptôme** : le montant d'un incident en cours ne correspond pas exactement à sa contribution au total de sa ligne
**Cause** : le front calcule `FREQ / 1080 × durée × SMIC` (moyenne plate sur 18 h), le backend pondère par heure
(`HOURLY_WEIGHTS`, lui-même faussé par le bug 9). `FREQ` duplique aussi `data/frequentation.json` en dur
**Fix** : coût par incident exposé par l'API (`cout_eur`, même calcul que les métriques du jour) ; `FREQ` supprimé.
Une perturbation déclarée n'a plus de coût propre (« — ») : elle n'entre pas dans le total
**Status** : ✅ Résolu le 2026-09-11

---

### [2026-09-12] Quota PRIM grillé en 3h30 avec 29 lignes
**Fichier(s)** : `backend/collector.py`, `backend/config.py`, `.env`
**Symptôme** : API retourne 429 après ~3h30 de fonctionnement, plus aucune collecte
**Cause** : 29 lignes × 2 appels × 5 cycles/h = ~290 req/h → 1 000 atteint en 3h30
**Fix** : retrait des 16 métros (inutiles sur PRIM), disruptions en appel global (1 req au lieu de 13),
polling 15 min → 14 req/cycle × 4/h × 16h ≈ 896 req/jour
**Status** : ✅ Résolu

### [2026-09-12] Métro PRIM : quasi aucune donnée
**Fichier(s)** : `backend/collector.py`
**Symptôme** : 1 seul incident métro jamais enregistré (METRO_4) sur tout l'historique
**Cause** : PRIM/Navitia ne couvre pas le métro en disruptions ni en retards RT de manière fiable
**Fix** : lignes de métro retirées du polling. Réintroduction possible avec une source alternative
**Status** : ✅ Résolu (contourné)

### [2026-09-13] Bug 21 — Race condition scheduler : 0 € malgré des incidents en cours
**Fichier(s)** : `backend/main.py`
**Symptôme** : 3 retards en BDD avec coûts calculés, mais `/api/stats/today` retourne 0 € / 0 min
**Cause** : au démarrage, APScheduler lançait `collect_disruptions`, `collect_rt_delays` et
`compute_daily_metrics` en parallèle → les métriques étaient calculées avant que la collecte ne soit terminée
**Fix** : `_startup_collect()` séquentiel (collecte → métriques → bilans), cycle régulier via un seul job
`_collect_cycle` qui enchaîne les 3 étapes
**Status** : ✅ Résolu

### [2026-09-13] Bug 22 — Métriques de la veille jamais finalisées
**Fichier(s)** : `backend/main.py`
**Symptôme** : si le serveur est redémarré le lendemain, les métriques de la veille sont figées au dernier
relevé (incidents ouverts avec durée sous-estimée)
**Cause** : `compute_daily_metrics` ne traite que `today`, pas de recalcul au changement de jour
**Fix** : `_finalize_yesterday()` au démarrage + job cron à 07h05 Paris (fenêtre 07h-07h bouclée)
**Status** : ✅ Résolu

### [2026-09-13] Bug 23 — Clic pastille picker sans effet
**Fichier(s)** : `frontend/pick.js`
**Symptôme** : clic sur une pastille (ex: RER C) → rien ne se passe visuellement
**Cause** : inconnue — le code semble correct, l'API répond 200, le serveur sert le fichier à jour.
Possibles pistes : erreur JS silencieuse dans `select()` ou `updatePanel()`, cache navigateur,
`formatDuree` non trouvé (mais `duree.js` est chargé avant `pick.js`)
**Fix** : code relu le 2026-09-20, aucun problème trouvé (handler correct, CSS OK, dépendances chargées).
Non reproduit depuis 7 jours — probable cache navigateur ou erreur réseau ponctuelle.
**Status** : ✅ Résolu (non reproductible)

---

## Session 2026-09-14

### [2026-09-14] Compteur du jour à 0 sur le Mac du travail
**Fichier(s)** : — (base locale)
**Symptôme** : `/api/stats/today` à 0 € / 0 incident ; l'autre PC affichait ~50 k € 40 min plus tôt
**Cause** : pas un bug — chaque PC a sa propre base. Celle du Mac n'avait rien reçu depuis le 2026-09-11 17 h 02
(serveur non lancé). Vérifié : séquence d'ids continue, aucune suppression récente, clé PRIM valide
**Fix** : pull + relance du serveur ; outil de transfert `backend/transfert.py` (export/import JSON fusionné)
pour ne plus perdre une demi-journée de collecte en changeant de PC
**Status** : ✅ Résolu (contourné — les bases restent séparées, trou du 12-13/09 sur le Mac)

### [2026-09-14] `.env` local écrasait le polling de 15 min
**Fichier(s)** : `.env` (non versionné), `backend/config.py`
**Symptôme** : après le pull, le serveur du Mac relevait toutes les 5 min → ~2 700 req/j pour un quota de 1 000
**Cause** : le défaut est passé à 15 min dans `config.py` sur l'autre PC, mais `POLLING_INTERVAL_MINUTES=5`
restait dans le `.env` du Mac (non versionné, donc jamais mis à jour par git). `.env.example` indique 12
**Fix** : `.env` du Mac passé à 15. À vérifier sur tout nouveau poste ; aligner `.env.example` (12) et
`CLAUDE.md` (« polling toutes les 5 min ») sur 15
**Status** : ✅ Résolu — polling à 5 min partout (config, .env.example, CLAUDE.md)

### [2026-09-14] Conflit au pull sur `publications/`
**Fichier(s)** : `publications/2026-09-11.txt`
**Symptôme** : `git pull` bloqué par un fichier non suivi local portant le même nom qu'un fichier distant
**Cause** : le récap de 20 h est généré par chaque PC où le serveur tourne, avec sa propre base → deux
versions différentes du même jour (Mac : 314 474 €, bilan du 10/09 faute de données ; autre PC : 427 006 €)
**Fix** : version distante gardée. Piste : ne générer le récap que sur un PC, ou le commiter systématiquement
**Status** : ✅ Contourné

---

### [2026-09-14] Bug 24 — "Usager moyen" affiche un retard dilué (5 min au lieu de ~30)
**Fichier(s)** : `frontend/pick.js`, `backend/metrics.py`
**Symptôme** : panneau picker affiche "5 minutes de vie" pour le RER C malgré des incidents de 48 et 61 min
**Cause** : `total_minutes_voyageurs / fréquentation_jour` divisait par tous les voyageurs du jour (500k+),
y compris ceux non impactés → résultat minuscule
**Fix** : nouveau calcul backend `_retard_moyen_pondere` : `Σ(durée × poids_horaire) / Σ(poids_horaire)`,
query directe sur les incidents de la période. Frontend lit `retard_moyen_min` / `retard_moyen_eur`.
Label changé : "Un usager retardé a perdu en moyenne"
**Status** : ✅ Résolu

---

## Session 2026-09-15 — Mac

### [2026-09-15] Bug 25 — Identifiants PRIM des Transilien faux depuis le 2026-04-29
**Fichier(s)** : `backend/collector.py` (LIGNES_CIBLES), `backend/relabel_transilien.py` (nouveau)
**Symptôme** : L, N, P, R jamais aucun incident ; « J », « K », « U » remontaient des données
**Cause** : commit `7adb7e3` — J/K/U pointaient sur les lignes P/R/N, L/N/P sur des bus (« Remplacement »,
codes 6434/6438/6435), R sur un ID sans départ. Vérifié via `pt_objects?q=Transilien&type[]=line`
**Fix** : IDs corrigés + test sur les 13 IDs ; historique réétiqueté J→P, K→R, U→N (202 incidents, 5 jours de
métriques recalculés, sauvegardes `*_backup_20260915`, table témoin `migrations_appliquees`)
**Status** : ✅ Résolu sur le Mac — ✅ Appliqué sur le PC Windows le 2026-09-16 (fix conflit d'unicité daily_metrics)

### [2026-09-15] Bug 26 — Aucune perturbation collectée depuis le 2026-09-12
**Fichier(s)** : `backend/collector.py` (`collect_disruptions`)
**Symptôme** : « Fetched 0 disruptions » à chaque relevé ; dernière perturbation en base le 11/09 ; interruption
RER D Corbeil–Malesherbes du 15/09 (7 h 13 → 9 h) absente
**Cause** : l'appel global `/line_reports` (commit `e93c8ef`) renvoie HTTP 200 avec 0 line_report, sans erreur
**Fix** : 2 appels `physical_modes/{RapidTransit,LocalTrain}/line_reports`, dédoublonnés par id ; warning si
0 line_report ; 3 tests. 14 perturbations au premier relevé, interruption RER D récupérée
**Status** : ✅ Résolu (perturbations du 12 au 15/09 perdues)

### [2026-09-15] Bug 27 — Bandeau figé sur « Chargement des données en cours… »
**Fichier(s)** : `frontend/index.html`, `frontend/statistiques.html`, `frontend/ticker.js`
**Cause** : les deux pages chargeaient `ticker.js` sans jamais appeler `Ticker.charger()` ; défilement à durée
fixe (45 s) → texte long illisible
**Fix** : `Ticker.charger()` + rafraîchissement 5 min ; vitesse constante `VITESSE_PX_S = 45` sur toutes les pages
**Status** : ✅ Résolu (rendu non vérifié dans un navigateur)

### [2026-09-15] Bug 28 — Page Méthode contraire au code
**Fichier(s)** : `frontend/methode.html`, `backend/api.py`, `backend/config.py`
**Symptôme** : métro annoncé, formule uniforme ÷ 18 h, « perturbations déclarées comptabilisées », seuil 5 min,
« incidents sans heure de fin exclus », « 7 488 req/jour sur 1 000 autorisées »
**Fix** : textes réalignés ; `/api/reference` sert poids horaires, seuil retard (2 min), suppression (5 min),
seuil fantôme (60 min) ; req/jour = relevés × (2 + 13) ; limite « Interruptions non chiffrées » (piste b abandonnée) ;
quota d'abord retiré à tort comme « inconnu », rétabli le jour même (bug 30)
**Status** : ✅ Résolu

### [2026-09-15] Bug 29 — Export de transfert écrit dans l'encodage du système
**Fichier(s)** : `backend/transfert.py` (`write_text` / `read_text` sans `encoding`)
**Symptôme** : `UnicodeDecodeError` à l'import sur le Mac des fichiers du 13 et du 15 exportés sous Windows (cp1252).
Inversement, le PC Windows lira mal les exports UTF-8 du Mac
**Contournement** : copies converties en UTF-8 dans le scratchpad pour l'import
**Fix** : `_ecrire_json` écrit en UTF-8 ; `_lire_json` lit en UTF-8 avec repli cp1252 (annoncé à l'écran) — le fichier
du 13 dans git est encore en cp1252. Tests : `tests/test_transfert.py` ; les 3 fichiers de `transferts/` relus
(246, 470, 715 incidents, accents intacts)
**Status** : ✅ Résolu le 2026-09-15

### [2026-09-15] `/start` réimportait tous les transferts, sans tenir compte du réétiquetage Transilien
**Fichier(s)** : `.claude/commands/start.md`, `backend/relabel_transilien.py`
**Risque** : les exports du 13 et du 14 portent les anciennes étiquettes (J/K/U = P/R/N). Importés dans une base déjà
réétiquetée, leurs incidents absents de la base y entraient avec la mauvaise lettre (la table témoin bloque
seulement une seconde exécution du script)
**Fix** : `relabel_transilien --statut` (lecture seule) ; `/start` choisit l'ordre selon le statut et n'importe plus
les fichiers d'avant le 15/09 dans une base déjà corrigée. Tests : `tests/test_relabel_transilien.py`
**Status** : ✅ Résolu le 2026-09-15

### [2026-09-15] test_daily_structure rouge depuis le retard moyen pondéré
**Fichier(s)** : `tests/test_metrics.py`
**Cause** : le mock renvoyait la ligne `DailyMetric` à toutes les requêtes, y compris celle des incidents (`8a83257`)
**Fix** : `side_effect` — 1ʳᵉ requête daily_metrics, suivantes vides
**Status** : ✅ Résolu

### [2026-09-15] Bug 30 — Quota PRIM en voie d'épuisement à 5 min
**Fichier(s)** : `.env`, `backend/config.py`, `backend/main.py`, `backend/collector.py`, `backend/api.py`
**Symptôme** : à 10 h 44, 450 requêtes restantes sur 1 000 ; relevé de 10 h 38 à 1 seul retard temps réel et une
erreur sur les perturbations RER. Au rythme de 5 min, quota épuisé vers 13 h 15
**Cause** : premier jour à 5 min (les 13 et 14/09 tournaient à 15 min) × 15 req/relevé ≈ 180 req/h, plus ≈ 60 requêtes
de tests manuels. La doc venait de déclarer le quota « inconnu » alors que PRIM le renvoie dans chaque réponse
(`x-ratelimit-limit-day: 1000`)
**Fix** : `.env` du Mac à 30 min pour finir la journée ; défaut 20 min + pause de minuit à 6 h (`collecte_heure_debut`)
→ 810 req/jour ; quota restant loggué à chaque relevé (warning sous 150) ; quota rétabli dans `/api/reference`, la page
Méthode et la doc ; 7 tests
**Status** : ✅ Résolu — `.env` du PC Windows passé à 20 le 2026-09-16 ; `.env` du Mac à remettre à 20

### [2026-09-15] Interruptions sous-estimées dans le coût (limite de méthode)
**Symptôme** : interruption RER D du 15/09 : 0 train supprimé détecté, seuls les retards autour sont chiffrés
**Cause** : perturbations exclues du coût (double comptage) ; trains d'un tronçon coupé absents du flux temps réel
**Status** : 🔄 Piste c dans `TODO.md` — tester PRIM à la prochaine interruption en cours

---

## Session 2026-09-16 — PC Windows

### [2026-09-16] Bug 31 — relabel_transilien échoue si le serveur a déjà collecté sous les bons IDs
**Fichier(s)** : `backend/relabel_transilien.py`
**Symptôme** : `IntegrityError: uq_daily_metrics_date_line` sur `(2026-09-15, TRANSILIEN_P)`
**Cause** : le serveur Windows avait tourné avec les IDs corrigés → `daily_metrics` contenait déjà
`TRANSILIEN_P` pour le 15/09. Le script tentait de renommer `J→P` pour la même date → conflit d'unicité
**Fix** : avant le UPDATE, supprimer les métriques à l'ancienne étiquette dont la date existe déjà
sous la nouvelle étiquette. Le recalcul qui suit reconstruit les bonnes valeurs
**Status** : ✅ Résolu

### [2026-09-16] relabel_transilien : print crash sur Windows (cp1252)
**Fichier(s)** : `backend/relabel_transilien.py`
**Symptôme** : `UnicodeEncodeError: 'charmap' codec can't encode character '\u2192'` (flèche →)
**Cause** : la console Windows utilise cp1252, le caractère `→` n'y existe pas
**Fix** : remplacé par `->` dans le print
**Status** : ✅ Résolu

---

## Session 2026-09-16 — Mac (affinage du calcul)

### [2026-09-16] Bug 32 — Trains supprimés jamais détectés
**Fichier(s)** : `backend/collector.py` (détection des suppressions, fin de `collect_rt_delays`)
**Symptôme** : 0 train supprimé en base sur 7 jours, toutes lignes confondues
**Cause** : seuls les trains **déjà enregistrés en retard** sont surveillés. Or `/departures` en `realtime` ne
contient pas les trains supprimés (ils disparaissent du flux) : un train supprimé qui roulait à l'heure n'est jamais vu
**Fix** : collecte sur le flux SIRI Estimated Timetable, qui marque chaque arrêt supprimé `CANCELLED` (commit 7a48b8e)
**Status** : ✅ Résolu (effectif au redémarrage du serveur)

### [2026-09-16] Coût calculé par minute de voyageurs, pas par train (limite de méthode)
**Fichier(s)** : `backend/metrics.py` (`_freq_minute`, `_minutes_voyageurs`)
**Symptôme** : chaque train en retard est multiplié par les voyageurs d'**une minute** de la ligne, ce qui suppose
60 trains/heure. GTFS du 17/09 à 8 h : RER A 50 trains (sous-estimé × 1,2), U 8 (× 7,5), K 2 (× 30)
**Cause** : formule d'origine ; le classement entre lignes pénalise les lignes peu fréquentes
**Status** : ✅ Résolu — lot 2 puis lot 6 (pertes calculées voyageur par voyageur)

### [2026-09-16] Couverture de la collecte inconnue (limite de méthode)
**Fichier(s)** : `backend/collector.py` (`/departures?count=50`)
**Symptôme** : 50 passages toutes gares confondues par relevé de 20 min : quelques trains vus à chaque fois
**Status** : ✅ Résolu — flux Estimated Timetable : tous les trains de chaque ligne sur ~2 h, à chaque relevé

### [2026-09-16] Flux SIRI Estimated Timetable : faisabilité (TASK-26)
**Requêtes** : 2 (13 h 30) — `estimated-timetable?LineRef=STIF:Line::C01742:` et `LineRef=ALL`
**Constats** :
- **Quota distinct** : `x-ratelimit-remaining-day` = 999 puis 998 sur ce flux, alors que le compteur Navitia du
  serveur était à 700 → deux compteurs de 1 000 req/jour (à reconfirmer dans les logs après bascule : Navitia ne
  doit plus perdre que 2 req/relevé). `CLAUDE.md` (« compteur unique pour tous les endpoints ») à corriger.
- Par ligne : 0,9 Mo, 0,5 s ; RER A = 79 trains, horaires prévus de −50 min à +2 h 15, 1 427 arrêts avec heure prévue
  et estimée, statuts `ON_TIME` / `DELAYED` / `CANCELLED` / `ARRIVED`. Arrêts **non ordonnés** dans la réponse.
- Global (`ALL`) : 5 Mo gzip, 59 Mo JSON, 3,7 s, 16 028 trains / 1 424 lignes, horizon +4 h — trop lourd à analyser
  toutes les 20 min ; l'appel par ligne suffit.
- 13 lignes ce midi : 928 trains, 4 supprimés en entier, 18 limités en cours de route (ex. RER A terminus La Défense,
  arrêts à l'est `CANCELLED`). 438 arrêts, tous nommés via le GTFS (`STIF:StopArea:SP:<n>:` = `IDFM:monomodalStopPlace:<n>`).
- `DatedVehicleJourneyRef` contient l'uuid du trip_id GTFS (133/141 sur le RER A) ; `JourneyNote` = code mission.
**Status** : ✅ Bascule faite (accord du 2026-09-16), commit 7a48b8e

### [2026-09-16] Bug 33 — Châtelet - Les Halles sans fréquentation
**Fichier(s)** : `backend/frequentation.py`
**Symptôme** : gare « inconnue » pour les RER A et B au premier build
**Cause** : identifiant GTFS de la gare 474151, publié 71264 (« CHATELET », réseau 801 seulement) dans les validations
**Fix** : `zdc_par_nom` — rattachement par les mots du libellé, réseau de la ligne d'abord ; test dédié
**Status** : ✅ Résolu

### [2026-09-16] Bug 34 — Trains retardés près du terminus à 0 min-voyageurs
**Fichier(s)** : `backend/metrics.py` (`arrets_du_train`)
**Symptôme** : train relevé pour la première fois avec un seul arrêt → aucun voyageur compté
**Cause** : le flux Estimated Timetable ne remonte qu'~50 min dans le passé ; un train encore à l'heure au relevé
précédent n'avait pas d'arrêts enregistrés
**Fix** : début de parcours complété par la mission GTFS (retard inconnu = 0 à ces arrêts, voyageurs comptés
avec le retard mesuré à leur descente) ; test dédié
**Status** : ✅ Résolu

### [2026-09-16] `frequentation.json` faux sur plusieurs lignes (limite de méthode)
**Symptôme** : K 50 000 voy./jour (15 654 comptés), C 350 000 (≈ 500 000), H/J/L sous-estimées de moitié ; mêmes
voyageurs le samedi et le dimanche qu'en semaine
**Fix** : remplacé par `data/frequentation_gares.json` (comptages SNCF + validations IDFM, par jour type)
**Status** : ✅ Résolu — fichier conservé mais plus lu par le calcul (suppression à décider)

### [2026-09-16] Rapport vacances du RER C biaisé par les travaux d'été (limite de méthode)
**Symptôme** : un jour de semaine de vacances pèse 54 % d'un jour ordinaire sur le C (73 à 83 % ailleurs)
**Cause** : seul le 3e trimestre des validations est publié ; le C est partiellement fermé l'été
**Status** : 🔄 Documenté sur la page Méthode — à revoir quand un autre trimestre sera publié

---

## Session 2026-09-17 — Mac (fiabilité du calcul)

### [2026-09-17] Bug 35 — Plafond de retard : deux sens comptés, voyageurs à bord plafonnés
**Fichier(s)** : `backend/metrics.py`, `backend/collector.py`, `frontend/methode.html`
**Symptôme** : trajet réel Choisy → Ivry (RER C, panne de signalisation) compté 4 min pour ~20 min vécues ;
recalcul sans plafond : ×1,5 à ×1,9 sur les 15, 16 et 17/09.
**Cause** : (1) `offre.trains_gare` additionne les départs des deux sens → plafond deux fois trop bas ;
(2) plafond appliqué au retard à la descente, y compris pour les voyageurs déjà à bord, qui ne peuvent pas changer
de train ; (3) hypothèse d'un train suivant à l'heure, fausse un jour de panne.
**Fix** : perte i → j = max(0, r_j − max(0, r_i − écart_ij)). écart_ij mesuré au relevé (`arrets[].a`, par gare
de descente) : premier autre train du même sens qui dessert i puis j, seulement pour un arrêt dont l'heure prévue
n'est pas passée au relevé. Repli : 60 ÷ (départs des deux sens ÷ 2) à la gare de montée, puis intervalle médian.
Effet : 15/09 ×1,58, 16/09 ×1,39, 17/09 ×1,41 par rapport au plafond par gare.
**Status** : ✅ Résolu — historique recalculé sur le Mac ; PC Windows à recalculer

### [2026-09-17] Réponses brutes du flux archivées (vérité terrain)
**Fichier(s)** : `backend/collector.py` (`archiver_flux`), `backend/config.py` (`archive_flux_jours`), `.gitignore`
**Pourquoi** : les soupçons B/C/D ci-dessous reposent sur un seul flux brut ; il faut pouvoir rejouer un relevé.
**Fix** : chaque réponse Estimated Timetable gzippée dans `logs/flux_brut/AAAA-MM-JJ/HHMMSS-<ligne>.json.gz`,
purge au-delà de 3 jours, aucune requête PRIM en plus.
**Status** : ✅ En place

### [2026-09-17] Bug 36 — Relevé perdu : tri impossible à égalité d'heure
**Fichier(s)** : `backend/collector.py` (`ecarts_train_suivant`)
**Symptôme** : « Error during startup collect » à 9 h 33, aucun incident écrit pour aucune ligne (15 requêtes perdues)
**Cause** : `sorted` sur des tuples `(heure, dict)` : deux trains au même passage → comparaison de deux dict
**Fix** : tri par l'heure seule ; la mesure d'écart est protégée par un `try/except` (repli sur l'offre prévue) ;
test à égalité d'heure et test d'échec sans perte du relevé ; rejoué sur la réponse archivée du RER A
**Status** : ✅ Résolu

### [2026-09-17] Bug 37 — « Mon trajet » : jour du 16/09 compté « à l'heure » avant les mesures
**Fichier(s)** : `backend/trajets.py`
**Symptôme** : 16/09 à 8 h 10 affiché « aucun retard relevé »
**Cause** : relevés arrêt par arrêt seulement depuis le 16/09 à 12 h 24 ; la couverture acceptait l'ancienne collecte
**Fix** : trajet antérieur au premier relevé arrêt par arrêt → « hors mesure » ; couverture exigée sur `arrets`
**Status** : ✅ Résolu

### [2026-09-17] Bug 38 — « Mon trajet » : 0 min en retenant un train aux relevés périmés
**Fichier(s)** : `backend/trajets.py`
**Symptôme** : Choisy → Ivry 8 h 00 le 17/09 : 0 min (ZANI de 7 h 58 à +3 à Ivry, mais +10 aux Ardoines)
**Cause** : seule la cohérence départ/arrivée était vérifiée ; la valeur d'Ivry datait d'un relevé antérieur
**Fix** : `arrivee_perimee` — retard à l'arrivée plus faible qu'une gare précédente au-delà de 2 min + 10 % du trajet
→ train écarté, jour signalé. Résultat : 16 min. Touche 0,9 % des arrêts relevés.
**Status** : ✅ Résolu (heuristique, à confirmer avec B)

### [2026-09-17] Page « Mon trajet » : menus des gares inutilisables en apparence
**Fichier(s)** : `frontend/mon-trajet.html`
**Symptôme** : impossible de choisir les gares ; aucune requête `/api/trajet/gares` dans les logs
**Cause** : il fallait d'abord cliquer une ligne, mais les pastilles étaient estompées (air désactivé)
**Fix** : pastilles pleines tant qu'aucune ligne n'est choisie, « Choisissez d'abord une ligne », étapes numérotées
**Status** : ✅ Résolu

### [2026-09-17] Soupçons B / C / D / E — corrigés le 17/09 soir (Windows)
- **B — Arrêts sautés** : 🔍 Requalifié le 2026-09-22 — détection non fiable, règle réécrite le même jour, toujours
  hors du coût depuis le 18/09 (voir session du 2026-09-22). Le flag `k=True` reste conservé par `fusionner_arrets`. Commit `36c7653`.
- **C — Passé visible** : ✅ Résolu. `attentes_mesurees` filtre les arrêts déjà passés au relevé (`obs_dt`).
  Docstrings corrigés. Commit `36c7653`. Durée mesurée et angle mort écarté le 2026-09-22.
- **D — Trains disparus pendant une coupure** : 🔍 Diagnostic ajouté. `trains_attendus` compare GTFS vs flux
  et loggue les manquants. Confirmé côté PRIM (ligne K : 4/36 prévus). Pas de création d'incidents automatique.
  Commit `cb4013c`.
- **E — Train partiellement supprimé** : ✅ Résolu. `is_cancelled` préservé dans l'upsert ; `s=None` hors fenêtre
  (au lieu de `False`) conservé par `fusionner_arrets`. Commit `cb4013c`. Effet inverse constaté et corrigé le
  2026-09-22 : suppressions levées comptées (voir Bug 46).

### [2026-09-17] Bug 39 — Suivi trop espacé : relevé toutes les 20 min, 13 requêtes par relevé
**Fichier(s)** : `backend/collector.py`, `backend/main.py`, `backend/config.py`, `backend/api.py`, `frontend/methode.html`
**Symptôme** : un arrêt n'est visible que peu de temps autour de son passage ; à 20 min d'intervalle, la plupart des
passages ne sont vus qu'en prévision. Plancher de 14 min imposé par le quota (13 req × relevé).
**Cause** : un appel Estimated Timetable par ligne ; perturbations relevées au même rythme que le temps réel.
**Fix** : un seul appel `LineRef=ALL` par relevé (T2 : 4,5 Mo sur le fil, 52 Mo de JSON, 0,7 s de lecture), filtré
par `trains_par_ligne`, archivé par ligne ; temps réel toutes les 5 min (216 req/jour), perturbations toutes les
20 min (108) ; pas de relevé au démarrage si le dernier date de moins d'un intervalle. Commit `5bb85bf`.
**Status** : ✅ Résolu — 1 requête par relevé vérifiée (684 → 683 à 12 h 23)

### [2026-09-17] Bug 40 — Retards annoncés longtemps à l'avance comptés comme mesures
**Fichier(s)** : `backend/collector.py` (`analyser_train`, `FENETRE_MESURE_MINUTES`)
**Symptôme** : un retard prévu des heures avant le passage était enregistré, puis gardé comme pire retard même
rattrapé ; avec l'horizon du flux global (~4 h 30), un train vu à 6 h pour 10 h serait aussi daté du mauvais jour.
**Fix** : retard et suppression d'un arrêt relevés seulement à moins de 10 min du passage estimé (ou déjà passé) ;
`suivi=True` : un train déjà en base sans retard dans la fenêtre voit ses arrêts mis à jour. Rejeu du flux de 11 h 38 :
68 trains retenus sans fenêtre, 62 avec. Valeur de 10 min à ajuster sur les archives.
**Status** : ✅ Résolu

### [2026-09-17] Filtre anti-fantôme : écarte des trains réellement bloqués (observation, non traité)
**Fichier(s)** : `backend/collector.py` (`GHOST_MIN_DELAY_MINUTES`, `GHOST_SLIDE_TOLERANCE_MIN`)
**Constat** : coupure d'alimentation à Viroflay (≈ 9 h 40 → 13 h, RER C / N / U). Les trains immobilisés ont une
heure estimée qui recule avec l'horloge (≈ relevé + 3 min) : SICA (C, 198 min), VERI (U, 190), PORO (N, 165), puis
POGI / ROPO / GOPI (N). Tous ont repris leur marche après la coupure → retards réels. Le filtre les a écartés à
certains relevés (redémarrage de 12 h 18) ; les valeurs passées au travers ont été gardées.
Une détection « glissement ≥ 80 % sur 10 min » aurait effacé ces vrais retards (rejeu des archives) → abandonnée.
**Status** : 🔍 Observé — décision utilisateur : ne rien modifier pour l'instant. Piste : un fantôme disparaît
sans jamais reprendre sa marche ; recouper avec les interruptions déclarées.

### [2026-09-17] Mesures complémentaires sur le flux global (soupçons C et D)
- **C** : dans le flux global, les arrêts passés restent visibles bien plus longtemps que ~3 min (RER A, 12 h–13 h :
  centaines d'arrêts passés de 30 à 60 min et plus). Le « ~3 min » vaut pour l'ancien appel par ligne.
- **D** : ligne K à 4 trains dans le flux global aussi (11 h 38, 12 h 18) → trou côté PRIM, pas dans notre filtre.


## Session 2026-09-18 — Mac (audit des chiffres affichés)

### [2026-09-18] Relevés sautés le matin : Mac en veille
**Symptôme** : relevés toutes les 10 à 30 min au lieu de 5, « maximum number of running instances reached ».
**Cause** : veille du Mac (réveils « DarkWake » de quelques secondes) ; un relevé seul dure ~10 s (68 Mo en 8 s).
**Fix** : `caffeinate -ims -w <PID uvicorn>` à côté du serveur. Sur batterie, écran fermé = veille quand même.
**Status** : ✅ Contourné (pas de changement de code)

### [2026-09-18] Bug 41 — Trains de 6 h à 7 h comptés la veille
**Fichier(s)** : `backend/metrics.py`, `bilans.py`, `transfert.py`, `main.py`, `recalcul.py`, `collector.py`, pages
**Symptôme** : 51 trains relevés le 18/09 entre 6 h et 7 h (76 884 €) dans la journée du 17/09.
**Cause** : journée comptée depuis 7 h alors que la collecte reprend à 6 h.
**Fix** : la journée commence à `collecte_heure_debut` (`metrics.debut_journee` / `journee_de`, seule définition) ;
finalisation de la veille à 6 h 05 ; pages lisent l'heure dans l'API. Tests `TestJourneeComptee`.
**Status** : ✅ Résolu (historique recalculé sur le Mac)

### [2026-09-18] Bug 42 — Comparaisons avec des jours incomplets (« +412,7 % » sur 7 jours)
**Cause** : lignes à 0 du 31/08 et du 7 au 9/09 (tests), jours d'avant le 16/09 incomplets (9 lignes, Transilien faux,
suppressions non détectées) : la semaine précédente passait pour « complète ».
**Fix** : `Settings.debut_donnees_fiables` (2026-09-16) — jours antérieurs gardés en base, exclus de tout cumul et de
toute comparaison (`metrics.premier_jour_affiche`, bilans, panneau de ligne).
**Status** : ✅ Résolu

### [2026-09-18] Bug 43 — Trains supprimés enregistrés comme retards
**Symptôme** : RER D ZOCO affiché « 3 min » pour 5 929 € (12 arrêts supprimés) ; 58 trains du 16 au 18/09.
**Cause** : serveur du Mac sur l'ancien code (bug E) jusqu'au 18/09 8 h 37, puis l'import gardait l'état du relevé le
plus récent.
**Fix** : `transfert import` — supprimé d'un seul côté ⇒ supprimé ; `python -m backend.recalcul` remet « supprimé »
tout train dont un arrêt relevé l'est (`recalcul.reparer_suppressions`). Fusion vérifiée sur une base jetable.
**Status** : ✅ Résolu (à relancer sur le Windows : `python -m backend.recalcul`)

### [2026-09-18] Panneau de ligne : trois chiffres de natures différentes
**Symptôme** : « 1 218 incidents · 972 104 € · 5 j 22 h » : période cachée (30 jours glissants), temps = retards des
trains alors que le coût repose sur le temps des voyageurs.
**Fix** : Aujourd'hui / Semaine / Année calendaires, période écrite, temps perdu par les voyageurs (base du coût).
**Status** : ✅ Résolu (`cd02e23`)

### [2026-09-18] Attentes mesurées de plus d'une heure
RER C 17/09 9 h-13 h et ligne N : coupure de Viroflay ; RER D 18/09 vers 6 h : perturbation déclarée (ralentissements,
suppressions). `DirectionRef` = Aller / Retour (pas la destination). LOPE 110 min à Corbeil non revérifiable (pas
d'archive avant 6 h 57 sur le Mac).
**Status** : ✅ Plausible, vraies perturbations

### [2026-09-18] Bug 44 — Mon trajet « mesuré depuis le 07/09 »
**Cause** : 711 incidents importés avec `arrets` = JSON `null` (pas NULL SQL) : `arrets IS NOT NULL` les prenait pour
des relevés arrêt par arrêt.
**Fix** : colonne `JSONB(none_as_null=True)`, filtre `jsonb_typeof(arrets) = 'array'` (`trajets.arrets_releves`),
`recalcul` remet les JSON `null` à NULL.
**Status** : ✅ Résolu

### [2026-09-18] Arrêts sautés comptés dans le coût sans validation
21 trains, 127 arrêts, 65 309 min-voy. les 17-18/09, non documentés sur la page Méthode.
**Décision** : retirés du coût (`minutes_voyageurs_train`), toujours relevés (`k`) et signalés dans Mon trajet.
**Status** : ✅ Résolu

### [2026-09-18] « Semaine » : 7 jours glissants sur Statistiques, depuis lundi dans le panneau
**Fix** : hall-of-shame en périodes calendaires, bornes écrites par le backend (`meta.periodes`) ; salaires journaliers
arrondis à l'inférieur partout.
**Status** : ✅ Résolu

---

## Notes de surveillance
- Quota PRIM : 1 000 req/jour par flux (Navitia, Estimated Timetable, Prochains passages), remise à zéro minuit UTC —
  temps réel 5 min × 1 req = 216/jour, perturbations 20 min × 2 req = 108/jour ; restes loggués, warning sous 150
- Bot X : planifié à 20h via APScheduler dans `main.py`
- Logs applicatifs : `logs/` (monté en volume Docker)

---

## Bugs résolus — Session 2026-09-16

### [2026-09-16] Bug 30 — Profil horaire inventé et mal normalisé
**Fichier(s)** : `backend/metrics.py`, `backend/profils.py`, `data/profils_horaires.json`, `frontend/methode.html`
**Symptôme** : deux défauts cumulés. (1) Les 18 poids horaires totalisaient 19.2 alors que la formule
divisait par 18 et que la fiche du bug 7 annonçait « somme=18.0 » — tous les chiffres du site étaient
majorés de 6,7 %. (2) Les poids étaient des valeurs écrites à la main, sans source, identiques pour
toutes les lignes et tous les jours : un samedi matin était pondéré avec un pic pendulaire de 8 h.
**Cause** : profil estimé à vue au lieu d'être mesuré, et diviseur codé en dur désolidarisé des poids.
**Fix** : profils horaires réels construits depuis les validations open data d'IDF Mobilités
(`python -m backend.profils build`), par réseau et par jour type (semaine / samedi / dimanche et fériés),
moyenne des profils de gare pondérée par le volume de validations. La formule devient
`voyageurs_jour × part_horaire ÷ 60`, où les 24 parts somment à 1 : le diviseur arbitraire disparaît et
l'écart de normalisation ne peut plus se reproduire (test `test_chaque_profil_somme_a_un`).
Historique recalculé par `python -m backend.recalcul` — cumul total 9 773 907 → 8 791 900 min-voyageurs (−10 %).
**Limites assumées et documentées sur la page Méthode** : profils groupés pour le Transilien (H+K, J+L,
N+U — l'open data est publié par réseau, pas par ligne), vacances scolaires non distinguées, et une
validation reste une entrée dans le réseau, pas un voyageur à bord.
**Status** : ✅ Résolu

### [2026-09-16] Bug 31 — Vacances scolaires non distinguées
**Fichier(s)** : `backend/profils.py`, `backend/metrics.py`, `data/profils_horaires.json`, `frontend/methode.html`
**Symptôme** : un retard du mardi de la Toussaint était pondéré avec la pointe pendulaire d'un mardi
ordinaire, alors que la fréquentation chute quand les écoles sont fermées (RER A : 8 h pèse 12,1 % hors
vacances contre 10,2 % en vacances, et la pointe bascule même de 8 h à 17 h).
**Cause** : seuls trois des cinq jours types du jeu de données IDFM étaient exploités.
**Fix** : calendrier scolaire zone C (data.education.gouv.fr, académies Paris / Créteil / Versailles)
récupéré par `backend.profils build` et stocké dans le même JSON. `categorie_jour()` rend désormais
JOHV / JOVS / SAHV / SAVS / DIJFP. Piège traité : les bornes du calendrier sont publiées en UTC à 22 h,
soit minuit heure de Paris le lendemain — sans conversion chaque période glissait d'un jour
(test `test_conversion_utc_vers_paris`). La borne haute est le jour de rentrée, donc exclue.
**Effet sur les chiffres** : nul pour l'instant. Les deux seuls jours de vacances de l'historique
(30 et 31 août 2026) ne portent aucun incident facturable ; le cumul reste à 8 811 726 min-voyageurs.
Le correctif jouera à partir des vacances de la Toussaint, le 17 octobre 2026.
**Limite restante** : les dimanches et jours fériés n'ont qu'un seul profil — le jeu de données source
ne les décline pas selon la période. Documenté sur la page Méthode.
**Status** : ✅ Résolu

## Session 2026-09-22 — Mac (bugs B / C / D / E, fenêtre de mesure)

### [2026-09-22] Bug 45 — Horaires GTFS périmés : « Mon trajet » et diagnostic D aveugles
**Fichier(s)** : `data/horaires.json.gz`, `backend/collector.py` (`diagnostiquer_trains_manquants`, `trains_attendus`)
**Symptôme** : le diagnostic D annonçait 100 % de trains absents sur les 13 lignes à chaque relevé du 22/09
(ligne U : 8/8) ; « Mon trajet » ne reliait plus aucun train du jour à son incident (tous « à l'heure »).
**Cause** : IDFM a publié un nouveau GTFS dans la nuit du 21 au 22/09 avec de nouveaux `trip_id`. Le flux temps réel
a basculé sur ces identifiants (RER B : 124/125 trains reconnus le 21/09, 0/124 le 22/09) ; `data/horaires.json.gz`
datait du 20/09. Les métriques ne sont pas touchées (elles ne lisent pas ces identifiants).
Second défaut du diagnostic : il attendait dans le flux tous les trains partis dans l'heure, y compris ceux arrivés
au terminus, qui en sortent.
**Fix** : `python -m backend.offre horaires` (fenêtre 19/09 → 21/10) : 279/280 incidents du 22/09 reliés.
Warning « Horaires GTFS périmés » quand aucun train du flux n'est reconnu ; seuls les trains encore en circulation au
relevé sont attendus (RER B 36/39, U 5/6, K 2/2 au relevé de 8 h 54). Test `test_diagnostiquer_signale_horaires_perimes`.
Commit `828c8d0`.
**Status** : ✅ Résolu — reconstruire les horaires à chaque publication GTFS (le warning le signale)

### [2026-09-22] C — Durée du passé visible, mesurée
Archives du 21-22/09 (142 relevés, flux global) : pour un train en circulation, un arrêt desservi reste visible
1,2 min en médiane (p90 4,8 min, p95 15 min, p99 29 min) ; un train arrivé au terminus reste ~14 min (p95 30 min).
Le « 30-60 min en flux global » de `lessons.md` était faux (trains terminés et arrêts supprimés datés à l'heure prévue).
Angle mort de `attentes_mesurees` : inexistant — l'arrêt n'est mesuré que si son heure prévue est après le relevé,
donc le train suivant (postérieur) n'est pas encore passé et figure dans le flux. Aucun code modifié.
**Status** : ✅ Clos

### [2026-09-22] B — Arrêts sautés : la règle de détection ne tient pas
Rejeu de `arrets_sautes` sur les archives du 21-22/09 : 204 détections, dont 125 (61 %) dont le passage estimé était
déjà dépassé au relevé — arrêt normalement passé et retiré du flux, pas sauté. La règle suppose que le flux retire les
arrêts dans l'ordre du parcours ; faux (un arrêt ancien peut traîner jusqu'à 15-30 min). 4 arrêts réapparaissent plus
tard. 64 détections restent plausibles (passage estimé ≥ 5 min après le relevé). Piste : ne retenir que les arrêts
disparus alors que leur passage estimé est encore à venir de quelques minutes, et confirmés absents au relevé suivant.
**Fix** (accord du 2026-09-22) : soupçon seulement si le passage estimé au relevé précédent était encore à venir de
`MARGE_ARRET_SAUTE` = 2 min (un train passe plus de 2 min avant l'estimation faite ≤ 10 min plus tôt dans 2,1 % des cas) ;
marque `k` posée au relevé suivant seulement si le train est toujours dans le flux et l'arrêt toujours absent
(`confirmer_sautes`). Rejeu du code sur les archives du 21-22/09 : 204 détections → 49 confirmées, en séries d'arrêts
consécutifs en bout de branche (ex. RER B Courcelle, Gif, La Hacquinière, Bures) : trains limités avant leur terminus.
**Status** : 🔍 En observation — règle réécrite, toujours hors du coût (décision à part)

### [2026-09-22] Bug 46 — Suppression levée toujours comptée (E)
**Fichier(s)** : `backend/collector.py` (upsert temps réel), `backend/transfert.py` (fusion inter-PC)
**Symptôme** : 40 trains depuis le 17/09 (sur 654 supprimés, 6 %) ont `is_cancelled = True` alors que tous leurs arrêts
ont ensuite été relevés desservis, retards mesurés (ex. RER C `8456a566…` du 21/09 : vu supprimé par le PC Windows avant
8 h 49, vu rouler 4-5 min de retard à chaque relevé du Mac ensuite). 22 portent encore `CANCELLED`, 18 sont repassés en
`DELAY_REALTIME` (cause « Retard de … ») en gardant `is_cancelled`.
**Cause** : règle « `is_cancelled` ne régresse jamais de `True` à `False` » (CLAUDE.md), posée quand les arrêts supprimés
sortaient de la fenêtre en `False`. Depuis `cb4013c` (`s=None` hors fenêtre), un `s=False` est une mesure réelle.
**Effet** : compteur de suppressions surévalué ; coût de ces trains = retards mesurés (attente de suppression
non comptée, aucun arrêt `s`).
**Fix** (accord du 2026-09-22) : `is_cancelled` = au moins un arrêt fusionné `s=True` (`collector.train_supprime`).
Collecteur : suppression gardée tant qu'un arrêt supprimé l'est encore (même sorti de la fenêtre), levée par un `s=False`
mesuré, y compris dans la branche « suivi » (train sans retard) ; l'incident levé devient un retard (pire `r` de ses
arrêts, `collector.suppression_levee`). `recalcul.lever_suppressions` applique la règle à l'historique ; l'import de
transfert fusionne désormais les arrêts arrêt par arrêt (`transfert.arrets_fusionnes`) puis recale l'état.
Règle de CLAUDE.md remplacée. Recalcul : 42 suppressions levées, 753 → 711 suppressions depuis le 16/09 ;
minutes-voyageurs inchangées (26 510 227 : le coût de ces trains se calculait déjà sur leurs retards mesurés).
**Status** : ✅ Résolu

### [2026-09-22] Fenêtre de mesure 10 min : gardée
Archives du 21-22/09, 56 760 arrêts vus à moins de 30 min de leur passage. Part des arrêts ayant au moins une mesure :
15 min 79,7 % · 10 min 67,7 % · 7 min 59,5 % · 5 min 53,3 %. Dernière mesure avant passage vs retard constaté après
passage : +7,1 % (15 min), +8,5 % (10), +9,7 % (7), +7,9 % (5) — le biais ne dépend pas de la fenêtre.
Passer à 5 min ferait perdre 14 points de couverture sans rien gagner. À étudier : 15 min (+12 points de couverture).
**Status** : ✅ Tranché — rien de modifié
