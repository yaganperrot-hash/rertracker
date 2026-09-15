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
**Status** : 🔄 En cours — à requalifier

### [2026-09-10 → 2026-09-11] Bug 11 — Transilien L, N, P, R remontent 0 incident
**Fichier(s)** : `backend/collector.py` (LIGNES_CIBLES)
**Symptôme** : sur la collecte du 2026-09-10, H, J, K et U remontent des incidents mais
L, N, P et R sont à zéro
**Cause** : inconnue — probablement légitime ou payload vide
**Fix** : logging diagnostic ajouté dans `collect_disruptions` et `collect_rt_delays` quand
une ligne ne remonte aucun résultat. Permettra de confirmer si c'est légitime ou un bug de parsing
**Status** : 🔄 Diagnostic en place — à surveiller dans les logs

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
**Fix** : à diagnostiquer — vérifier la console navigateur (`F12`) au prochain clic
**Status** : 🔄 En cours — en attente de diagnostic console (non repris le 2026-09-14)

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

## Notes de surveillance
- Quota PRIM : 1 000 req/jour officiel mais toléré largement — polling 5 min, 13 lignes departures + 1 global disruptions
- Bot X : planifié à 20h via APScheduler dans `main.py`
- Logs applicatifs : `logs/` (monté en volume Docker)
