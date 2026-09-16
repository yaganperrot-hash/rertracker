# TASKS Deepseek

> TASK-01 (`duree_minutes` / `heure_fin` dans `/api/incidents/current`) : ✅ terminée, déjà en place dans `backend/api.py`.

---

# Lot 6 « mesure plutôt qu'estimation » — ✅ livré le 2026-09-16 par Claude Code

Décisions de l'utilisateur : calcul au plus près du réel, estimations maison réduites au minimum ; seuil de retard
gardé à 2 min ; SMIC gardé (lot 5 abandonné). Livré :
- collecte sur le flux SIRI Estimated Timetable, colonne `incidents.arrets` (retard à l'arrivée et attente mesurée
  du train suivant, arrêt par arrêt) — `backend/collector.py`, `models.py`, `database.py`, `transfert.py` ;
- `backend/offre.py` : départs par gare et heure, missions, noms d'arrêts SIRI, id_zdc ; coefficients de gare retirés ;
- `backend/frequentation.py` (nouveau) : montées dans un train par ligne × gare × jour type × heure, comptages SNCF
  (validations IDFM pour les gares non comptées), rapport vacances mesuré ;
- `backend/metrics.py` : perte de chaque voyageur i → j (retard à l'arrivée en j, ou attente au premier arrêt supprimé),
  destinations au prorata des montées du jour des gares suivantes ; historique reconstitué depuis la mission GTFS ;
- page Méthode réécrite (sources, formule, exemple calculé par le backend, périmètre, limites).
Reste : recalcul de l'historique (serveur arrêté), puis vérification du premier relevé.

---

# Lot « Affinage du calcul » — rédigé le 2026-09-16 (lots 0 à 3 livrés ; 4 remplacé par le lot 6 ; 5 abandonné)

Chaque tâche indique son exécutant : **[Deepseek]** (écriture de code uniquement, aucune commande) ou
**[Claude Code]** (vérifications, commandes, requêtes, études). Une tâche marquée ⚠️ touche une zone critique
de `CLAUDE.md` : Claude Code demande l'accord de l'utilisateur **avant** de la confier à Deepseek.

## Contexte commun (à lire avant toute tâche du lot)

### Décisions de l'utilisateur (2026-09-16)
- **Historique recalculé** avec la nouvelle méthode (`python -m backend.recalcul`) pour les lots 2 et 3. Le lot 4
  n'est pas rétroactif : sa date de mise en service est écrite sur la page Méthode.
- Lot 5 (valeur du temps) conservé, appliqué aux minutes-voyageurs de la nouvelle méthode.
- Chaque lot qui change les chiffres ajoute à `TODO.md` : « PC Windows : `git pull` puis `python -m backend.recalcul` ».

### Le défaut principal corrigé
Aujourd'hui `minutes-voyageurs = retard × voyageurs_jour × part_heure ÷ 60`, **par train en retard**. Cela revient
à supposer qu'un train transporte une minute de voyageurs de la ligne, soit 60 trains par heure. Offre réelle
(GTFS IDFM, trains au départ de leur terminus, jeudi 17/09/2026, deux sens confondus) :

| Ligne | Trains/jour | 7 h | 8 h | 12 h | 18 h | Sous-estimation actuelle à 8 h (60 ÷ trains) |
|-------|------------:|----:|----:|-----:|-----:|------------------:|
| RER A | 635 | 51 | 50 | 30 | 50 | × 1,2 |
| RER B | 547 | 41 | 37 | 24 | 40 | × 1,6 |
| L     | 558 | 41 | 42 | 28 | 42 | × 1,4 |
| U     | 93  | 8  | 8  | 4  | 8  | × 7,5 |
| K     | 36  | 4  | 2  | 1  | 4  | × 30  |

Formule cible : `minutes-voyageurs = retard × voyageurs_par_train`, avec
`voyageurs_par_train = voyageurs_jour × part_heure ÷ trains_équivalents_heure` (définition en TASK-16).

### Faits vérifiés par Claude Code (ne pas re-vérifier, ne pas recopier ailleurs sans nécessité)
- **GTFS** : `https://data.iledefrance-mobilites.fr/explore/dataset/offre-horaires-tc-gtfs-idfm/files/a925e164271e4bca93433756d6a340d1/download/`
  — zip de 117 Mo, **30 jours** d'offre à partir du jour de publication, mis à jour chaque jour.
  `stop_times.txt` fait 760 Mo décompressé : **lecture en flux ligne à ligne depuis le zip**, jamais chargé en mémoire.
- `route_id` GTFS = identifiant de ligne PRIM sans le préfixe `line:` (`IDFM:C01742` ↔ `line:IDFM:C01742`, les
  13 lignes de `LIGNES_CIBLES`). Toujours dériver la correspondance de `LIGNES_CIBLES`, jamais la recopier.
- `trip_id` GTFS = identifiant `vehicle_journey` PRIM sans le préfixe `vehicle_journey:`
  (`IDFM:TN:SNCF:<uuid>`). 100 % des trains en base depuis le 13/09 se retrouvent dans le GTFS.
- `trip_headsign` GTFS = code mission PRIM (`QYRO`, `MONA`…) : 2 802 missions en base sur 2 806 retrouvées.
- `stop_name` GTFS = nom de gare PRIM (`Incident.gare`) : 354 gares en base sur 354, correspondance exacte.
- `stops.txt` : l'arrêt parent `parent_station = IDFM:71517` porte l'identifiant `id_zdc = 71517` des jeux
  de validations (`La Défense`).
- Heures GTFS au-delà de 24 h (`25:10:00`) : appartiennent au jour de service de la veille ; heure = `hh % 24`.
- La fenêtre GTFS ne contient pas toujours les cinq jours types : du 16/09 au 15/10/2026, **aucun jour de vacances**.
- `/departures` en `data_freshness=realtime` **ne contient pas** les trains supprimés : ils disparaissent du flux
  (test du 15/09, `TODO.md` piste c). La détection actuelle ne surveille que les trains déjà en retard : un train
  supprimé qui roulait à l'heure n'est jamais vu → **0 suppression en base en 7 jours** (Bug 32, `DEBUG.md`).

### Règles
- `encoding="utf-8"` explicite sur toute lecture/écriture de fichier texte.
- Tout invariant écrit dans un commentaire ou une docstring a son test.
- Deepseek n'envoie aucune requête PRIM et ne lance rien ; les builds open data sont lancés par Claude Code.
- Nouveaux lecteurs de fichiers de données : sur le modèle de `profils.charger()` (lu une fois, `{}` si illisible).

---

## LOT 0 — Diagnostics (aucun chiffre ne change)

## TASK-13 [Deepseek] — Journal de couverture de chaque relevé

### Fichier cible
`backend/collector.py`, `tests/test_collector.py`

### Contexte
`/departures?count=50` renvoie les 50 prochains passages, toutes gares confondues : chaque relevé ne voit
que quelques trains. On ne sait pas quelle part des trains est observée.

### Travail
1. Extraire en fonction pure le calcul de l'identifiant de train déjà fait dans `collect_rt_delays`
   (`vj_id.split(":RealTime:")[0]`) : `_train_id(dep: dict) -> str | None`. `collect_rt_delays` l'utilise.
2. Fonction pure `couverture_releve(departures: list[dict]) -> dict` :
   `{"trains": int, "passages": int, "debut": datetime | None, "fin": datetime | None}` — trains distincts
   (tous, en retard ou non, `data_freshness == "realtime"`), nombre de passages, plus petite et plus grande
   heure **prévue** (`base_departure_date_time`, en UTC).
3. Dans `collect_rt_delays`, pour chaque ligne, un log INFO :
   `Couverture RER_A : 7 trains, 50 passages, départs prévus 08:02 → 08:11 (9 min)` (heures de Paris).

### Critères d'acceptation
- Aucune requête supplémentaire, aucun changement de ce qui est enregistré en base.
- Tests : réponse vide ; deux passages du même train (suffixes `:RealTime:` différents) = 1 train ; passage
  `base_schedule` ignoré ; bornes début/fin correctes.

---

## TASK-14 [Deepseek] — Test qui reproduit le Bug 32

### Fichier cible
`tests/test_collector.py`

### Travail
Sur le modèle des tests existants de détection des suppressions (`mock_settings.cancel_default_impact_minutes`),
un test : un train **à l'heure** présent dans un relevé, absent du suivant alors que son départ prévu est
dans le futur → aucune ligne `is_cancelled` n'est créée. Marqué
`@pytest.mark.xfail(strict=True, reason="Bug 32 : suppression d'un train à l'heure non détectée — TASK-27")`.

### Critères d'acceptation
- Le test est « xfailed » aujourd'hui ; il passera (et le marqueur sera retiré) avec TASK-27.

---

## TASK-15 [Claude Code] — Rapport de couverture

Après au moins une journée complète de logs de TASK-13 et le fichier de TASK-16 : taux de couverture par ligne
(trains distincts vus / trains prévus au GTFS sur la journée, et fenêtre moyenne en minutes). Consigné dans
`DEBUG.md`. Sert à décider de TASK-26.

---

## LOT 1 — Offre théorique (données, hors zone critique)

## TASK-16 [Deepseek] — `backend/offre.py` : trains équivalents et intervalles par heure

### Fichiers cibles
`backend/offre.py` (nouveau), `tests/test_offre.py` (nouveau)

### Contexte
Même architecture que `backend/profils.py` : `python -m backend.offre build` télécharge et agrège hors ligne,
écrit `data/offre_theorique.json` (versionné) ; à l'exécution le backend ne lit que ce fichier.

### Définitions (à reprendre dans la docstring du module)
- **Trains équivalents de l'heure h** d'une ligne, pour une date : Σ sur les trains du jour de
  `(arrêts du train dont l'heure de départ prévue est dans h) ÷ (arrêts du train)`.
  Un train de 7 h 50 à 8 h 30 avec la moitié de ses arrêts avant 8 h compte 0,5 à 7 h et 0,5 à 8 h.
  **Invariant : Σ des 24 heures = nombre de trains du jour.**
  Justification : les voyageurs qui montent pendant h se répartissent sur les trains qui desservent des gares
  pendant h ; ainsi Σ_trains voyageurs_par_train = voyageurs du jour.
- **Intervalle de l'heure h** : pour chaque couple (arrêt parent, `direction_id`) desservi pendant h, nombre de
  départs dans h ; intervalle = `60 ÷ médiane de ces nombres`, borné à 60 min. `null` si aucun départ.
  C'est l'attente du train suivant pour un voyageur dont le train est supprimé.

### Travail
1. Constantes : URL du GTFS (Contexte commun), chemin `data/offre_theorique.json`. Lignes :
   `{LIGNES_CIBLES[k]: k.removeprefix("line:") for k in LIGNES_CIBLES}` (import depuis `backend.collector`).
2. Téléchargement du zip dans un fichier temporaire (`tempfile`), supprimé à la fin, même en cas d'erreur.
3. Jours actifs de chaque `service_id` : `calendar.txt` (jours de la semaine entre `start_date` et `end_date`)
   puis `calendar_dates.txt` (`exception_type` 1 = ajout, 2 = retrait).
4. `trips.txt` : garder les trains des 13 `route_id`.
5. `stop_times.txt` en flux : pour chaque train retenu, liste de (heure de départ prévue `hh % 24`, `stop_id`).
   `stops.txt` : `stop_id` → arrêt parent.
6. Pour chaque date de la fenêtre : jour type `profils.categorie_jour(date)` ; trains équivalents et intervalles
   par ligne et par heure.
7. Moyenne par ligne × jour type × heure, sur les dates de ce jour type. **Repli** si un jour type est absent de la
   fenêtre : `JOVS` ← `JOHV`, `SAVS` ← `SAHV` ; `DIJFP` absent → erreur explicite. Replis listés dans
   `_source.replis`.
8. Écriture :
   ```json
   {
     "_source": {"portail": "...", "jeu": "offre-horaires-tc-gtfs-idfm", "genere_le": "AAAA-MM-JJ",
                 "fenetre": ["AAAA-MM-JJ", "AAAA-MM-JJ"], "replis": {"JOVS": "JOHV"},
                 "methode": "trains équivalents : part des arrêts du train dans l'heure"},
     "lignes": {"RER_A": "IDFM:C01742", "...": "..."},
     "trains_heure": {"RER_A": {"JOHV": [24 nombres, 2 décimales], "...": []}},
     "intervalle_min": {"RER_A": {"JOHV": [24 nombres ou null, 1 décimale], "...": []}}
   }
   ```
   Affichage console par ligne comme `profils.build` (trains/jour, trains à 8 h en JOHV).
9. Lecteur : `charger() -> dict` et `trains_heure(line_id, quand: datetime) -> float | None`,
   `intervalle_min(line_id, quand: datetime) -> float | None` (heure de Paris, jour type via `categorie_jour`).

### Tests (`tests/test_offre.py`)
Un mini GTFS construit **dans le test** avec `zipfile` dans `tmp_path` (pas de binaire versionné), fonctions
d'agrégation appelées sur ce zip sans réseau :
- un train dont les arrêts chevauchent deux heures est réparti au prorata ;
- `calendar_dates` retire et ajoute bien un jour ;
- heure `25:10:00` → heure 1 ;
- intervalle : 4 départs dans l'heure sur un arrêt/sens → 15 min ; borne 60 ;
- repli `JOVS` ← `JOHV` noté dans `_source.replis`.
Sur le fichier réel `data/offre_theorique.json` (tests sautés s'il est absent) :
- **invariant** : pour chaque ligne et jour type, Σ `trains_heure` = trains du jour à 1 % près (écrire aussi
  `trains_jour` dans le JSON pour ce test) ;
- les 13 lignes et les 5 jours types présents, 24 valeurs chacun ;
- RER A `JOHV` 8 h entre 30 et 80 trains équivalents.

### Critères d'acceptation
- Aucun appel PRIM. Aucun fichier du zip écrit dans le projet.
- `backend/profils.py` inchangé.

---

## TASK-17 [Claude Code] — Construire et contrôler l'offre

`python -m backend.offre build`, contrôle des ordres de grandeur contre le tableau du Contexte commun, taille
du JSON (< 1 Mo), tests verts, commit du fichier. Ajout à `TODO.md` : régénérer `offre_theorique.json` en même
temps que les profils.

---

## LOT 2 — Nouveau calcul

## TASK-18 [Deepseek] ⚠️ — Voyageurs par train, heure prévue, suppression = intervalle

### Fichiers cibles
`backend/metrics.py`, `backend/api.py` (référence), `tests/test_metrics.py`, `tests/test_api.py`

### Travail
1. `_voyageurs_par_train(line_id, quand) -> float` remplace `_freq_minute` :
   `voyageurs_jour × part_horaire ÷ max(trains_heure, 1.0)`. Plancher à 1 train : une heure creuse à 0,3 train
   équivalent ne doit pas multiplier les voyageurs.
   **Repli** (ligne sans profil ou sans offre, ou `quand` inconnu) : l'ancien calcul `_freq_minute`, conservé
   sous ce nom, avec un `logger.warning` **une seule fois par ligne** (ensemble module).
2. `_minutes_voyageurs(duree, line_id, quand)` = `round(duree × _voyageurs_par_train(...))`.
3. `_incident_dt_paris` : `heure_theorique` si renseignée, sinon `heure_debut`. La **sélection des incidents
   du jour** dans `compute_daily_metrics` reste sur `heure_debut` (ne pas changer la fenêtre 7 h → 7 h).
4. Train supprimé (`is_cancelled`) : durée = `round(intervalle_min(line_id, quand))` si disponible, sinon
   `settings.cancel_default_impact_minutes`. Calculé dans `incident_minutes_voyageurs`, **pas** lu dans
   `duree_minutes` (le collecteur y écrit 5, et l'historique doit se recalculer).
5. Retard moyen pondéré (`metrics.py`, boucle `poids = _freq_minute(...)`) : poids = `_voyageurs_par_train`.
6. `/api/reference` : ajouter `offre_trains_heure` (le `trains_heure` du JSON), `offre_intervalle_min`,
   `offre_source` ; garder `suppression_minutes` (valeur de repli).

### Tests
- Mettre à jour les valeurs attendues des tests existants qui supposent l'ancienne formule
  (`test_rer_a_known_value`, `test_rer_b_known_value`, `test_repli_plat_sans_instant`, `tests/test_api.py`),
  en calculant l'attendu à partir des fichiers de données, jamais en dur.
- **Invariant** : pour chaque ligne et jour type, Σ sur les heures où `trains_heure ≥ 1` de
  `voyageurs_par_train × trains_heure` = `voyageurs_jour × Σ part` de ces heures (à 0,1 % près).
- Transilien K, mardi hors vacances 8 h : minutes-voyageurs d'un retard de 10 min ≥ 10 × l'ancienne formule.
- RER A, mardi 8 h : voyageurs par train entre 1 000 et 3 000.
- Un incident avec `heure_theorique` à 8 h 55 et `heure_debut` à 9 h 05 est pondéré à 8 h.
- Suppression RER A mardi 8 h : durée entre 2 et 6 min ; Transilien K mardi 14 h : ≥ 20 min ; ligne sans offre :
  `cancel_default_impact_minutes`.
- Repli : une ligne absente de l'offre donne le même résultat que `_freq_minute`, et un seul warning pour deux appels.

### Critères d'acceptation
- `cout_eur`, `bilans.py` et la réconciliation des totaux inchangés (tests de `test_bilans.py` verts sans modification).

---

## TASK-19 [Claude Code] — Étude : source de `voyageurs_jour`

`data/frequentation.json` contient des chiffres ronds d'origine inconnue. Les validations open data ne peuvent
pas les remplacer telles quelles : elles sont par réseau (H+K, J+L, N+U regroupés) et ne comptent pas les
correspondances sans valideur (métro → RER à Châtelet), ce qui sous-compte fortement les RER dans Paris.
Comparer les deux sources par ligne, chercher les chiffres officiels publiés (IDFM, RATP, SNCF), présenter
un tableau et une recommandation à l'utilisateur. **Aucun changement sans son accord.**

> **Résultat (2026-09-16)** — source trouvée : SNCF Open Data `comptage-voyageurs-trains-transilien`
> (voyageurs **montants** comptés dans les trains, correspondances comprises, par ligne × gare × jour type
> JOB/SAM/DIM × 5 tranches horaires, hors travaux et vacances ; comptage automatique annuel ou manuel ~tous les 4 ans).
> Montants par jour ouvré comparés à `frequentation.json` :
>
> | Ligne | JOB | SAM | DIM | Année | `frequentation.json` |
> |---|---:|---:|---:|---|---:|
> | C | 508 651 | 284 502 | 201 993 | 2025 | 350 000 |
> | D | 630 841 | 427 752 | 329 673 | 2024 | 530 000 |
> | E | 306 281 | 174 020 | 125 810 | 2022 | 180 000 |
> | H | 239 376 | 154 959 | 114 094 | 2025 | 110 000 |
> | J | 279 878 | 169 308 | 120 633 | 2025-26 | 130 000 |
> | K | 15 654 | 2 846 | 1 440 | 2025 | 50 000 |
> | L | 296 827 | 162 753 | 112 391 | 2025 | 170 000 |
> | N | 131 828 | 88 356 | 59 231 | 2025 | 100 000 |
> | P | 101 493 | 58 668 | 43 411 | 2023 | 80 000 |
> | R | 71 422 | 55 729 | 47 067 | 2025 | 70 000 |
> | U | 47 248 | 16 634 | 12 021 | 2024 | 40 000 |
> | A | *11 gares SNCF seulement* | | | 2022 | 900 000 |
> | B | *16 gares SNCF seulement* | | | 2019/2023 | 650 000 |
>
> Constats : `frequentation.json` sous-estime C, E, H, J, L d'environ ×1,5 à ×2,2 et surestime K ×3 ;
> le samedi pèse ~55-65 % d'un jour ouvré, le dimanche ~40 % (aujourd'hui : 100 %). A et B n'y sont que pour la
> partie SNCF : il faut une autre source (chiffres publiés RATP / IDFM) pour ces deux lignes.
> Recommandation : voyageurs par jour **par ligne et par jour type** depuis ce jeu (A et B : chiffre officiel publié),
> dans un `backend/frequentation.py` construit hors ligne comme `profils.py`. Ce jeu donne aussi les montants
> par gare de chaque ligne, meilleurs que les validations pour les coefficients de gare (lot 3). En attente de décision.

---

## TASK-20 [Deepseek] — Page Méthode alignée sur le nouveau calcul

### Fichier cible
`frontend/methode.html`

### Travail
1. Formule : 
   ```
   minutes-voyageurs = retard du train (min) × voyageurs_par_train
   voyageurs_par_train = voyageurs_par_jour × part_de_l'heure ÷ trains_de_l'heure
   coût = minutes-voyageurs × … €/h ÷ 60
   ```
2. Note sous la formule : paragraphe sur les **trains de l'heure** (offre théorique GTFS d'IDFM, par ligne et jour
   type ; un train à cheval sur deux heures compte pour partie dans chacune). « L'heure retenue est l'heure prévue
   du train. » « Un train supprimé compte pour l'intervalle jusqu'au train suivant à cette heure-là » suivi de deux
   exemples (RER A à 8 h, Transilien K à 14 h, jour de semaine) — valeurs lues dans `/api/reference`, jamais en dur.
3. Exemple recalculé en JS à partir de `ref.offre_trains_heure.RER_A.JOHV[8]` :
   `… voy./jour × … % ÷ … trains = … voy./train · 45 × … = … min-voy. · coût estimé = … €`
   (même arrondi que le backend).
4. Périmètre : « Trains supprimés … comptés … min chacun » → « comptés pour l'intervalle jusqu'au train suivant ».
5. Limites : nouveau paragraphe **« Offre prévue, pas offre réalisée »** : le nombre de trains vient des horaires
   prévus ; un jour de service réduit, les trains restants sont plus chargés que ne le suppose le calcul.

### Critères d'acceptation
- Ton froid et factuel, aucune valeur numérique écrite en dur hors exemple de libellé.
- Placeholders « — » conservés si `/api/reference` échoue.

---

## TASK-21 [Claude Code] — Recalcul et vérification du lot 2

Tests verts ; serveur arrêté ; `python -m backend.recalcul` ; comparer avant/après par ligne sur 7 jours
(attendu : Transilien nettement en hausse, RER A proche) ; relecture de `/methode` ; `TODO.md` (recalcul PC
Windows) ; commit.

---

## LOT 3 — Pondération par gare

## TASK-22 [Deepseek] ⚠️ — Coefficient de gare par mission

### Fichiers cibles
`backend/offre.py`, `tests/test_offre.py`

### Principe
Un retard constaté à la gare G ne touche que les voyageurs qui descendent **après** G (ceux déjà à bord et ceux
qui montent plus loin). Coefficient `coef(mission, G)` = part des voyageurs du train qui descendent après G.
Modèle, pour une mission (suite ordonnée de gares g₁ … gₙ) :
- poids de chaque gare `w_i` = validations moyennes par jour de la gare (jeu
  `validations-reseau-ferre-nombre-validations-par-jour-3eme-trimestre`, champ `nb_vald`, par `id_zdc`) ;
  gare sans volume connu : médiane des gares de la mission ;
- montées `m_i = w_i` pour i < n, `m_n = 0` ;
- destination d'un voyageur monté en i : gare j > i avec probabilité `w_j ÷ Σ_{k>i} w_k` ;
- `coef(G = g_k) = [ Σ_{i<k} m_i × P(dest > k | i) + Σ_{i≥k} m_i ] ÷ Σ_i m_i`.

### Travail
1. Réutiliser `profils._volumes_par_gare` (réseaux de `LIGNE_RESEAU`) : volume par `id_zdc`, sommé sur les
   réseaux quand une gare en a plusieurs.
2. Missions : trains GTFS regroupés par (`route_id`, `trip_headsign`, suite d'arrêts parents). Une même mission
   avec plusieurs suites d'arrêts : garder la plus fréquente.
3. JSON : `"coef_gare": {"RER_A": {"QYRO": {"La Défense": 0.62, "...": 0.0}}}` (clé = `stop_name`, 3 décimales)
   et `"coef_gare_ligne": {"RER_A": {"La Défense": 0.55}}` (moyenne sur les missions pondérée par leur nombre de trains).
4. Lecteur `coef_gare(line_id, mission, gare) -> float` : mission connue → ligne → **1.0**.

### Tests
- **Invariants** : coefficient dans [0, 1] ; égal à 1 au premier arrêt ; non croissant le long de la mission ;
  0 au terminus.
- Mission à 3 gares de poids égaux : valeurs calculées à la main.
- Replis : mission inconnue → coefficient de ligne ; gare inconnue → 1.0.

---

## TASK-23 [Deepseek] ⚠️ — Appliquer le coefficient de gare

### Fichiers cibles
`backend/metrics.py`, `tests/test_metrics.py`, `frontend/methode.html`

### Travail
- `incident_minutes_voyageurs` : `minutes-voyageurs × coef_gare(line_id, mission, gare)` pour les retards et les
  suppressions (`gare` / `mission` nulles → 1.0).
- Méthode : formule complétée (`× part_des_voyageurs_après_la_gare`), paragraphe explicatif ; Limites :
  « Fréquentation par ligne » réécrit (la gare est prise en compte, la destination est estimée au prorata de la
  fréquentation des gares suivantes) ; nouvelle limite : la gare retenue est celle du pire retard observé, pas
  celle où le retard est né.

### Tests
- Même incident au premier arrêt et à l'avant-dernier : le second coûte moins.
- Incident sans gare : identique au lot 2.

## TASK-24 [Claude Code] — Recalcul et vérification du lot 3
Comme TASK-21.

---

## LOT 4 — Suppressions, interruptions, couverture

> **2026-09-16 — TASK-26 faite, TASK-25 et TASK-27 remplacées.** Le flux SIRI Estimated Timetable (voir
> `DEBUG.md`) donne tous les trains d'une ligne sur ~2 h, arrêt par arrêt, avec le statut `CANCELLED` explicite
> (train entier ou fin de parcours). Plus besoin de l'offre GTFS du jour : la collecte passe sur ce flux (TASK-31).

## TASK-31 [Claude Code] ⚠️ — Collecte des retards et suppressions sur le flux Estimated Timetable

13 appels `estimated-timetable?LineRef=STIF:Line::<code>:` à la place des 13 appels `/departures` ; noms de gares
via `offre.nom_arret` (`arrets` de `offre_theorique.json`, fait) ; suppression = premier arrêt `CANCELLED` ;
pire retard sur les arrêts non supprimés ; filtre des trains fantômes conservé ; deux compteurs de quota suivis.
Même `navitia_id` qu'avant (`rt_vehicle_journey:IDFM:TN:SNCF:<uuid>_AAAAMMJJ`). **En attente de l'accord de
l'utilisateur** (zone critique : endpoint et quota PRIM). Puis TASK-28 (page Méthode) et `CLAUDE.md` (quota).

## TASK-25 [Claude Code] ⚠️ — Offre du jour pour la détection des suppressions (remplacée par TASK-31)

Avant TASK-27, valider avec l'utilisateur : téléchargement quotidien du GTFS (117 Mo) par le scheduler, durée du
build sur la machine, emplacement `data/offre_jour/` (à ajouter au `.gitignore`).

## TASK-26 [Claude Code] ⚠️ — Faisabilité du flux SIRI Estimated Timetable

Avec l'accord de l'utilisateur, un seul serveur en marche, **3 requêtes au plus** : taille de la réponse, lignes
présentes, statut des trains supprimés, en-têtes `x-ratelimit-*-day`. Conclusion dans `DEBUG.md` avec le rapport
TASK-15. Si le flux est viable, Claude Code rédige ici la tâche de remplacement des 13 appels `/departures`.
Sinon, tâche d'extrapolation par le taux de couverture, présentée comme estimation.

## TASK-27 [Deepseek] ⚠️ — Détecter les trains prévus absents du flux (Bug 32 + interruptions)

### Fichiers cibles
`backend/offre.py`, `backend/collector.py`, `backend/main.py`, `.gitignore`, `tests/test_offre.py`,
`tests/test_collector.py`

### Travail
1. `python -m backend.offre jour AAAA-MM-JJ` et fonction `construire_jour(date)` : écrit
   `data/offre_jour/AAAA-MM-JJ.json` = `{line_id: {trip_id_sans_prefixe: [[stop_name, "HH:MM:SS"], ...]}}`
   (heures GTFS brutes, départs prévus). Garde les 3 derniers fichiers. `data/offre_jour/` dans `.gitignore`.
2. Scheduler (`main.py`) : chaque jour à 4 h 30 (heure de Paris), construire le jour et le lendemain ; en cas
   d'échec, warning et détection désactivée pour la journée (jamais d'exception qui tue le scheduler).
3. `collect_rt_delays`, par ligne, après la collecte : fenêtre = `[relevé + CANCEL_MARGIN_MIN, fin − CANCEL_MARGIN_MIN]`
   où `fin` = plus grande heure prévue des passages reçus (TASK-13). Trains attendus = trains de l'offre du jour
   ayant au moins un départ prévu dans la fenêtre. Un train attendu dont l'identifiant n'apparaît dans **aucun**
   passage reçu (toutes gares) est supprimé.
4. Garde-fou : si plus de la moitié des trains attendus d'une ligne manquent **et** qu'aucune perturbation active
   `NO_SERVICE` / `REDUCED_SERVICE` n'existe en base sur la ligne, warning « écart massif offre / temps réel »
   et rien n'est enregistré (probable décalage de données, pas une interruption).
5. Enregistrement : même `navitia_id` que les retards (`rt_vehicle_journey:<trip>_<AAAAMMJJ>`), `is_cancelled=True`,
   `type_incident="CANCELLED"`, `heure_theorique` et `gare` = premier départ prévu dans la fenêtre, `mission` =
   `trip_headsign`. Insertion sans écraser un incident existant (`on_conflict_do_nothing`). Un train qui réapparaît
   est déjà remis en retard par l'upsert existant.
6. La détection existante (trains en retard disparus) est conservée.

### Tests
- TASK-14 passe : retirer `xfail`.
- Train attendu présent dans les passages → rien ; absent → une suppression, avec gare et heure prévue.
- Départ prévu hors fenêtre → rien.
- Garde-fou : 6 trains attendus sur 10 absents sans perturbation → rien et warning ; avec perturbation
  `NO_SERVICE` → 6 suppressions.
- Offre du jour absente → aucune détection, un warning.

### Critères d'acceptation
- Aucune requête PRIM supplémentaire.

## TASK-28 [Deepseek] — Page Méthode : suppressions et interruptions
Périmètre : les trains prévus absents du flux sont comptés, y compris pendant une interruption, **depuis le
<date de mise en service>** ; Limites : « Interruptions non chiffrées » réécrit (les trains supprimés du tronçon
sont comptés ; les voyageurs qui renoncent à voyager ne le sont pas).

---

## LOT 5 — Valeur du temps

## TASK-29 [Claude Code] — Sourcer la valeur tutélaire du temps

Référentiel officiel (France Stratégie / DGITM, fiches outils de l'évaluation des projets de transport) :
valeur du temps des déplacements en Île-de-France, et coefficient de pénibilité de l'attente ou du retard.
Valeurs, année de référence et lien consignés ici ; validation par l'utilisateur avant TASK-30.

> **Résultat (2026-09-16)** — Haut-commissariat à la Stratégie et au Plan, *Investissements de transport : une
> évaluation renouvelée face aux nouveaux défis*, juin 2026, chapitre 2, tableau 2 p. 56 (valeurs du rapport
> Ayoun-Bréhier IGEDD 2023, validées par le conseil scientifique les 10 mars et 21 mai 2025) :
> valeur du temps **courte distance / urbain, Île-de-France, tous motifs : 13,8 €₂₀₂₂/h** (domicile-travail/études 15,5 ;
> professionnel 27,3 ; autres 10,7). Temps d'attente pondéré **× 1,5** (rapport Quinet 2013, repris p. 58).
> Aucun coefficient propre au retard subi n'est fixé : l'étude IDFM 2005 citée p. 62 conclut que la conséquence
> principale est le retard à l'arrivée, sans chiffre. Proposition : second chiffre = minutes-voyageurs × 13,8 €/h
> (valeur 2022, non actualisée), sans coefficient ; × 1,5 réservé aux suppressions (temps d'attente). À valider.

## TASK-30 [Deepseek] — Second chiffre en valeur tutélaire
Détaillée par Claude Code après TASK-29 : `config.py` (valeur, source), `/api/reference`, `bilans.py`
(`cout_tutelaire`, même règle d'arrondi par ligne × jour), Statistiques et Méthode. Le SMIC reste le chiffre principal.

---

# Lot « Bilans » — pages `/statistiques` et `/annee`

> ✅ Lot implémenté directement par Claude Code le 2026-09-11 (à la demande de l'utilisateur), tests verts.
> Écart avec TASK-03 : les messages PRIM contiennent souvent « Motif : … » ; ce motif déclaré est lu en
> priorité, puis un avis planifié (période, dates) est classé en travaux avant les autres mots-clés.

## Contexte commun (à lire avant toute tâche du lot)

**Maquettes de référence** : `docs/maquettes/statistiques.html` et `docs/maquettes/annee.html`.
Elles fixent le **layout et le style** (couleurs, tailles, espacements, composants). **Tous les chiffres et
libellés qu'elles contiennent sont fictifs** : rien n'est recopié en dur, tout vient du JSON généré.
Le cadre beige arrondi autour de `.page` (`body{background:#e6ded0}`, `border-radius:14px`) est un artifice de
présentation : on ne le garde pas. La page est sur fond crème `#F4EFE6`, colonne centrée de 760 px max.
**Exception à la fidélité** : les couleurs de ligne des maquettes ne sont **pas** reprises ; on garde celles de
l'accueil (`frontend/index.html`, `LINE_META`), détaillées en TASK-06 — décision du 2026-09-11.

**Principe d'architecture** : aucune requête base par visiteur. Toutes les 10 min, le backend calcule les bilans
et écrit des **fichiers JSON statiques** dans `frontend/data/`. Les pages HTML ne font que `fetch` ces fichiers.

**Règles éditoriales** (impératives) :
- Ton froid et factuel. Pas d'adjectif, pas d'exclamation.
- **Deux unités seulement à l'écran : euros et minutes.** Jamais de « jours cumulés », « ans », « heures »
  (ne pas utiliser `frontend/duree.js` sur ces pages). Un nombre d'incidents n'est pas une unité, il est permis.
- Accents : noir `#1a1a17` et rouge uniquement, plus les couleurs officielles des lignes.

**Règle de cohérence (bug à corriger)** : aujourd'hui le chiffre du haut de `stats.html` est écrit en dur et
contredit la somme par ligne. Désormais :
- le coût en € est calculé **par ligne de `daily_metrics`** (une ligne × un jour) :
  `cout = floor(minutes_voyageurs × smic_horaire / 60)` ;
- **tout agrégat est une somme de ces coûts** : total période = Σ lignes ; total année = Σ mois = Σ lignes.
  On ne recalcule jamais `floor(Σ minutes × smic / 60)`, qui produirait un écart d'arrondi.

**Fenêtres temporelles** : le sélecteur 7 j / 30 j / 90 j pilote **toute** la page `/statistiques`.
Fenêtre courante = les N derniers jours, aujourd'hui inclus (`du = aujourd'hui − (N−1)`, `au = aujourd'hui`,
aujourd'hui = date calendaire à Paris, comme `compute_daily_metrics`). Fenêtre précédente = les N jours juste
avant. Les deltas ne sont calculés que si la fenêtre précédente est **entièrement couverte** par les données
(sinon `null`, affiché « n.d. »). La base ne contient des données que depuis le 2026-09-10 : les états vides
sont le cas normal au démarrage et doivent être propres.

**Ordre des tâches** : 02 → 03 → 04 → 05 → 06 → 07 → 08 → 09 → 10 → 11 → 12.
Ne pas modifier ce qui n'est pas mentionné. `backend/main.py`, `backend/collector.py` et
`tests/test_collector.py` contiennent des modifications non commitées de l'utilisateur : les conserver telles
quelles.

---

## TASK-02 — Taux SMIC et période de recalcul dans la configuration

### Fichier cible
`backend/config.py`

### Contexte
Le taux SMIC est dupliqué en dur (`frontend/index.html`, `backend/bot.py`, `frontend/methode.html`) et vaut
encore 11,88 € (taux 2025). Taux retenu : **12,31 € brut/heure, en vigueur depuis le 1er juin 2026**
(arrêté du 22 mai 2026 ; 12,02 € de janvier à mai 2026). Les données en base commencent le 2026-09-10 : un
seul taux s'applique. Les bilans lisent une source unique, recopiée dans le JSON (`meta.smic_horaire`).

### Travail
Ajouter à `Settings` :
```python
smic_horaire: float = 12.31           # € brut / heure, en vigueur depuis le 1er juin 2026 — base du coût estimé
bilans_interval_minutes: int = 10     # période de régénération des JSON de bilans
```
Ajouter les deux variables commentées dans `.env.example` (`SMIC_HORAIRE=12.31`, `BILANS_INTERVAL_MINUTES=10`).

### Critères d'acceptation
- `get_settings().smic_horaire == 12.31` sans variable d'environnement.
- Aucun autre fichier modifié (l'alignement de `index.html`, `bot.py` et `methode.html` est fait en TASK-12).

---

## TASK-03 — Classement des motifs opérateur en catégories de causes

### Fichier cible
`backend/causes.py` (nouveau)

### Contexte
Les motifs déclarés par l'opérateur sont dans `Incident.cause` pour les lignes `source = 'disruption'`.
C'est du **texte libre**, souvent en HTML avec entités (`P&#233;riode`, `<br>`). Les incidents
`source = 'realtime'` ont un motif synthétique (« Retard de 4 min à … ») et **ne sont pas** utilisés pour les
causes. Exemples réels relevés en base :
```
<p>P&#233;riode : en semaine, le soir &#224; partir de 23h.<br><br>Dates : du lundi 07 au vendredi 11 septembre.
<p>P&#233;riode : du lundi au vendredi<br><br>Dates : du 24/08 au 18/09<br><br>Les horaires de d&#233;part…
Trafic interrompu entre Sarcelles – Persan/Luzarches
Ligne P : Paris Est - Provins 7/09 - 11/12
RER D : Combs-la-Ville <-> Melun interrompu du 31/08-18/09
Trafic perturbé
RER E : Nanterre - Villiers 7 - 11/09
RER C : Bibliothèque <-> Chaville - Vélizy trafic perturbé
<p>La gare de Clamart en direction de Paris Montparnasse n'est pas desservie jusqu'à 11h36.<br><br>…
```

### Travail
```python
CATEGORIES: tuple[str, ...] = (
    "Signalisation / infrastructure",
    "Panne matériel",
    "Incident voyageur",
    "Mouvement social",
    "Météo",
    "Travaux",
    "Non précisé",
)

def normaliser(texte: str | None) -> str: ...
def categoriser_cause(texte: str | None) -> str: ...
```
`normaliser` : `html.unescape`, suppression des balises (`re.sub(r"<[^>]+>", " ", …)`), suppression des
accents (`unicodedata.normalize("NFKD")` puis retrait des caractères combinants), minuscules, espaces
multiples réduits à un seul, `strip()`. `None` → `""`.

`categoriser_cause` : sur le texte normalisé, tester les catégories **dans cet ordre de priorité**, première
correspondance gagnante :

| Catégorie | Motifs (sous-chaînes du texte normalisé, sauf mention regex) |
|---|---|
| Mouvement social | `greve`, `mouvement social`, `preavis` |
| Incident voyageur | `malaise`, `accident de personne`, `personne sur les voies`, `incident voyageur`, `voyageur malade`, `colis suspect`, `bagage`, `objet abandonne`, `intrusion`, `heurt`, `signal d'alarme` |
| Signalisation / infrastructure | `signalisation`, `aiguillage`, `catenaire`, `alimentation electrique`, `panne electrique`, `infrastructure`, `rupture de rail`, `passage a niveau` |
| Panne matériel | `train en panne`, `panne d'un train`, `panne de train`, `materiel roulant`, `incident technique sur un train`, `avarie`, `panne materiel` |
| Météo | `intemperie`, `neige`, `verglas`, `tempete`, `orage`, `chute d'arbre`, `vegetation`, `canicule`, `inondation`, `vent violent` |
| Travaux | `travaux`, `chantier`, `maintenance`, `modernisation`, regex `periode\s*:`, regex `dates?\s*:`, regex `\bdu\s+\d{1,2}/\d{1,2}`, regex `\b\d{1,2}(?:/\d{1,2})?\s*[-–]\s*\d{1,2}/\d{1,2}\b` |
| Non précisé | tout le reste, texte vide ou `None` |

Ne **pas** utiliser le mot seul `voyageur` : il apparaît dans les formules types (« les voyageurs sont
invités à… ») des messages de travaux.

### Critères d'acceptation
- Les 9 exemples réels ci-dessus donnent, dans l'ordre : Travaux, Travaux, Non précisé, Travaux, Travaux,
  Non précisé, Travaux, Non précisé, Non précisé.
- `categoriser_cause(None) == "Non précisé"`.
- La valeur retournée appartient toujours à `CATEGORIES`.
- Aucune dépendance nouvelle (stdlib uniquement).

---

## TASK-04 — Calcul des bilans (fonctions pures + requêtes)

### Fichier cible
`backend/bilans.py` (nouveau)

### Contexte
Source unique des chiffres des deux pages : la table `daily_metrics` (`backend/models.py`, `DailyMetric` :
`date`, `line_id`, `nb_incidents`, `minutes_voyageurs`), la même que lit l'accueil. Les causes viennent de la
table `incidents` (`source = 'disruption'`) via `backend/causes.py`. La liste des 13 lignes est
`list(LIGNES_CIBLES.values())` (`backend/collector.py`), ordre RER A→E puis Transilien H→U.

**Séparer le calcul (fonctions pures, testables sans base) des requêtes (fonctions async).**
Les fonctions pures reçoivent des objets ayant les attributs `date`, `line_id`, `nb_incidents`,
`minutes_voyageurs` (des `DailyMetric` en production, des `SimpleNamespace` dans les tests).
Les lignes dont `line_id` n'est pas dans `LIGNES` sont ignorées.

### 1. Utilitaires
```python
LIGNES: list[str] = list(LIGNES_CIBLES.values())
SEUIL_CREUX = 0.6      # mois « creux » : coût < 60 % de la moyenne des mois complets
MIN_MOIS_CREUX = 3     # pas de creux calculé avec moins de 3 mois complets

def cout_eur(minutes_voyageurs: int, smic_horaire: float) -> int:
    """floor(minutes × smic / 60). Appliqué à UNE ligne de daily_metrics, jamais à une somme."""

def delta_pct(actuel: int, precedent: int | None) -> float | None:
    """(actuel − precedent) / precedent × 100, arrondi à 1 décimale. None si precedent est None ou 0."""

def repartition_causes(categories: list[str]) -> dict:
    """{"total": n, "repartition": [{"categorie", "n", "pct"}]}.
    Tri par n décroissant puis ordre de CATEGORIES. pct entiers dont la somme vaut exactement 100 quand
    total > 0 (méthode du plus fort reste). total == 0 → repartition == []."""
```

### 2. `construire_statistiques(periode_jours, aujourdhui, lignes_metriques, categories_causes, debut_donnees, smic_horaire, genere_a) -> dict`
- `lignes_metriques` : toutes les lignes `daily_metrics` de `du_prec` à `au` (la fonction répartit entre les
  deux fenêtres).
- `categories_causes` : catégories (déjà classées) des perturbations dont la journée tombe dans la fenêtre
  **courante**.
- `debut_donnees` : plus petite `date` de `daily_metrics` (ou `None` si la table est vide).
- `genere_a` : `datetime` aware, heure de Paris.

Sortie, **exactement** ce schéma :
```jsonc
{
  "meta": {
    "genere_a": "2026-09-11T14:10:00+02:00",
    "periode_jours": 30,
    "du": "2026-08-13", "au": "2026-09-11",
    "precedente": { "du": "2026-07-14", "au": "2026-08-12" },
    "smic_horaire": 12.31,
    "debut_donnees": "2026-09-10",          // null si aucune donnée
    "jours_couverts": 2,                     // jours de la fenêtre courante ≥ debut_donnees
    "precedente_complete": false             // debut_donnees ≤ precedente.du
  },
  "total":      { "cout_eur": 587053, "minutes": 2964914, "incidents": 752 },   // = Σ lignes
  "total_prec": { "cout_eur": 0, "minutes": 0, "incidents": 0 } | null,          // null si !precedente_complete
  "delta_pct":  { "cout_eur": 24.1, "minutes": 22.0, "incidents": 18.2 } | null, // null si total_prec null
  "lignes": [   // toujours les 13, tri minutes décroissantes puis ordre de LIGNES
    { "id": "RER_B", "cout_eur": 183800, "minutes": 928300, "incidents": 139,
      "delta_pct_minutes": 12.4 }            // null si !precedente_complete ou minutes_prec == 0
  ],
  "pire_ligne": { "id": "RER_B", "minutes": 928300, "incidents": 139, "delta_pct_minutes": 12.4 } | null,
  "causes": { "total": 13, "repartition": [ { "categorie": "Travaux", "n": 6, "pct": 46 } ] }
}
```
Règles : `cout_eur` d'une ligne = Σ `cout_eur(row.minutes_voyageurs)` de ses lignes `daily_metrics` ;
`total.*` = Σ des `lignes[].*` ; `pire_ligne` = `lignes[0]` si ses minutes > 0, sinon `null`.

### 3. `construire_annee(annee, aujourdhui, lignes_metriques, categories_par_mois, debut_donnees, smic_horaire, genere_a) -> dict`
- `lignes_metriques` : lignes `daily_metrics` de l'année `annee` **et** de l'année `annee − 1`.
- `categories_par_mois` : `dict[int, list[str]]`, catégories des perturbations de l'année par mois (1–12).
- `au_effectif = min(aujourdhui, date(annee, 12, 31))`.
- Mois `m` **renseigné** si son intervalle recoupe `[debut_donnees, au_effectif]`. Sinon toutes ses valeurs
  sont `null`. `jours_couverts` = jours du mois dans cet intervalle ; `partiel = jours_couverts < jours du mois`.
- Comparaison avec l'année précédente **à date équivalente** : période `[annee−1-01-01, au_effectif − 1 an]`
  (29 février → 28 février). Disponible seulement si `debut_donnees ≤ date(annee − 1, 1, 1)`.

Sortie :
```jsonc
{
  "meta": {
    "annee": 2026, "au": "2026-09-11", "en_cours": true,
    "genere_a": "…", "smic_horaire": 12.31, "debut_donnees": "2026-09-10",
    "mois_renseignes": [9],
    "annee_prec_disponible": false
  },
  "total": { "cout_eur": …, "minutes": …, "incidents": … },     // = Σ mois renseignés = Σ lignes
  "mois": [   // toujours 12 entrées, mois 1 → 12
    { "mois": 1, "cout_eur": null, "minutes": null, "incidents": null,
      "jours_couverts": 0, "partiel": false, "cause_principale": null },
    { "mois": 9, "cout_eur": 587053, "minutes": 2964914, "incidents": 752,
      "jours_couverts": 2, "partiel": true, "cause_principale": "Travaux" }
  ],
  "pire_mois": 9 | null,       // mois renseigné de coût max (> 0) ; égalité → le plus ancien
  "creux": [7, 8],             // voir règle ci-dessous
  "lignes": [ { "id": "RER_B", "cout_eur": …, "minutes": …, "incidents": …,
                "delta_pct_minutes": -31.0 | null } ],      // 13 lignes, même tri que /statistiques
  "meilleure_progression": { "id": "RER_D", "delta_pct_minutes": -31.0,
                             "nb_lignes_en_recul": 1 } | null
}
```
Règles :
- `cause_principale` : catégorie la plus fréquente du mois en **ignorant « Non précisé »** s'il existe une autre
  catégorie ; `null` si aucune perturbation.
- `creux` : parmi les mois renseignés **non partiels** (au moins `MIN_MOIS_CREUX`, sinon `[]`), ceux dont le
  coût est `< SEUIL_CREUX ×` moyenne de ces mois, en excluant `pire_mois`. Trié croissant. Un mois partiel
  n'est jamais un creux (le mois en cours paraîtrait toujours bas).
- `meilleure_progression` : ligne au `delta_pct_minutes` le plus négatif (< 0) ; `null` si aucune ligne ne
  baisse ou si l'année précédente est indisponible. `nb_lignes_en_recul` = nombre de lignes avec delta < 0.

### 4. Requêtes et écriture des fichiers
```python
def journee_paris(dt: datetime) -> date:
    """Date calendaire à Paris de l'horodatage (même convention que compute_daily_metrics)."""

async def generer_bilans(db: AsyncSession | None = None, dossier: Path = DOSSIER_BILANS) -> None: ...
```
- `DOSSIER_BILANS = Path(__file__).parent.parent / "frontend" / "data"` (créé s'il manque).
- `aujourdhui = datetime.now(PARIS_TZ).date()` ; `genere_a = datetime.now(PARIS_TZ)` (réutiliser `PARIS_TZ`
  de `backend/metrics.py`).
- `debut_donnees` : `select(func.min(DailyMetric.date))`.
- Pour `p` dans `(7, 30, 90)` → `statistiques-{p}.json`.
- `annee-{aujourdhui.year}.json` toujours ; `annee-{aujourdhui.year − 1}.json` seulement si
  `debut_donnees ≤ 31/12` de cette année-là.
- Perturbations : `select(Incident.cause, Incident.heure_debut).where(Incident.source == "disruption", …)`,
  filtrées par `journee_paris(heure_debut)` puis classées avec `categoriser_cause`.
- Écriture **atomique** : `json.dumps(…, ensure_ascii=False, separators=(",", ":"))` dans `nom.json.tmp`
  puis `os.replace` vers `nom.json` (jamais de fichier à moitié écrit servi à un visiteur).
- Toute exception est journalisée (`logger.exception`) et n'interrompt pas le scheduler ; les anciens
  fichiers restent en place.
- Session : même motif que `compute_daily_metrics` (`db` fourni, sinon `AsyncSessionLocal()`).

### Critères d'acceptation
- Aucune fonction pure n'importe ni n'appelle la base.
- Invariants toujours vrais : `total == Σ lignes` (3 champs) pour les deux sorties ;
  `total == Σ mois renseignés` pour l'année.
- Table vide : les 4 fichiers sont écrits, tous les totaux à 0, `pire_ligne`, `pire_mois`,
  `meilleure_progression`, `delta_pct`, `total_prec` à `null`, `lignes` contient les 13 lignes à 0.

---

## TASK-05 — Scheduler, routes, redirection et en-têtes de cache

### Fichiers cibles
`backend/main.py`, `.gitignore`

### Travail
1. `main.py` — **conserver les modifications existantes** (commentaires `coalesce` / `misfire_grace_time`).
   Ajouter un job :
   ```python
   scheduler.add_job(
       generer_bilans, "interval",
       minutes=settings.bilans_interval_minutes,
       id="generer_bilans",
       next_run_time=datetime.now(timezone.utc),   # premier calcul dès le démarrage
   )
   ```
2. Routes, **déclarées avant** `app.mount("/", StaticFiles…)` (sinon le mount les masque), exclues du schéma
   OpenAPI (`include_in_schema=False`) :
   - `GET /statistiques` → `FileResponse(frontend_dir / "statistiques.html")`
   - `GET /annee` → `FileResponse(frontend_dir / "annee.html")`
   - `GET /stats.html` → `RedirectResponse("/statistiques", status_code=301)` (anciens liens)
3. Middleware HTTP ajoutant `Cache-Control` selon le chemin :
   | Chemin | Valeur |
   |---|---|
   | commence par `/data/` | `public, max-age=600, stale-while-revalidate=600` |
   | `/statistiques`, `/annee` | `public, max-age=600` |
   | `/bilan.css`, `/bilan.js` | `public, max-age=86400` (les pages les chargent avec `?v=1`) |
   Ne rien changer pour les autres chemins (accueil, `/api/*`).
4. `.gitignore` : ajouter `frontend/data/` (fichiers générés).

### Critères d'acceptation
- Au démarrage, `frontend/data/statistiques-30.json` apparaît sans attendre 10 min.
- `/statistiques` et `/annee` servent les pages ; `/stats.html` renvoie 301 vers `/statistiques`.
- `/data/statistiques-30.json` porte l'en-tête `Cache-Control` ci-dessus ; `/api/stats/today` n'en porte pas.

---

## TASK-06 — Feuille de style et script communs aux bilans

### Fichiers cibles
`frontend/bilan.css` (nouveau), `frontend/bilan.js` (nouveau)

### `bilan.css`
Reprendre **fidèlement** le CSS des deux maquettes (classes `.page`, `.head`, `.brand`, `.eyebrow`, `.toggle`,
`.hero`, `.big`, `.sub`, `.note`, `.card`, `.worst`, `.best`, `.badge`, `.delta`, `.row`, `.lbl`, `.track`,
`.fill`, `.val`, `.two`, `.line`, `.mini`, `.chart-wrap`, `.big2`), en le fusionnant et avec ces changements :
- Variables sur `:root` : `--creme:#F4EFE6; --encre:#1a1a17; --brun:#4a463d; --gris:#8a8478;
  --gris-clair:#a39c8c; --sable:#e8e1d4; --filet:#f0ebe1; --creux:#c9c1b1; --rouge:#E1251B;
  --rouge-fonce:#A32D2D; --rouge-pale:#FCEBEB`.
- `body { background: var(--creme); }` sans le cadre beige ; `.page` sans `border-radius` ni fond propre,
  `max-width: 760px; margin: 0 auto; padding-block: 32px; padding-inline: 16px` (30 px au-delà de 600 px).
- `.toggle` : les options sont des `<button>` (reset `border:0; background:none; font:inherit; cursor:pointer`),
  l'option active porte `aria-pressed="true"` et le style `.on` de la maquette.
- Deltas : `.delta.hausse` = style `.up` de la maquette (`#FCEBEB` / `#A32D2D`) ;
  `.delta.baisse` = fond `var(--sable)`, texte `var(--brun)` ; `.delta.nd` = fond `var(--sable)`, texte
  `var(--gris-clair)`. Idem `.mini.hausse` (rouge foncé), `.mini.baisse` (brun), `.mini.nd` (gris clair).
- Navigation `.liens` sous `.head` : liens 12 px `var(--gris)`, séparés par ` · `, lien actif `var(--encre)`
  poids 500, sans soulignement ; `margin-bottom: 20px`.
- État de chargement : `main[aria-busy="true"] { opacity: .45; transition: opacity .15s; }`.
- Repli « voir tout » : `.plie[hidden]` masqué (le reset global gère `[hidden]`, sinon l'ajouter).
- Pied de page `.pied` : 11 px, `var(--gris-clair)`, `margin-top: 36px`.
- **Mobile ≤ 480 px** : `.big` 44 px (`small` 28 px), `.sub` 19 px, `.row .lbl` 48 px de large,
  `.val` 80 px, `.two .card` `min-width: 100%`, rien ne déborde horizontalement à 360 px.

### `bilan.js`
Même motif que `frontend/duree.js` : une IIFE qui expose `window.Bilan = { … }`.
```js
LIGNES   // id → { nom, lbl, fond, texte, encre }
         // Couleurs = celles de l'accueil (frontend/index.html, LINE_META), PAS celles des maquettes :
         //   RER_A #E2231A, RER_B #5191CF, RER_C #C8A800 (texte #1a1a17), RER_D #00814F, RER_E #B04191
         //     — lbl "RER A"… nom "RER A"…
         //   H #7B7B7B, J #D2B464 (texte #1a1a17), K #8C4B31, L #9F3E96, N #333333,
         //   P #E87722, R #228B22, U #7B0F1F — lbl "H"… nom "Transilien H"…
         //   texte #fff sauf mention
         // encre = couleur de la ligne lisible sur fond blanc : = fond, sauf RER_C #8A7400, J #8F7431
MOIS, MOIS_COURT   // ['janvier', …], ['jan', 'fév', 'mar', 'avr', 'mai', 'jun', 'jul', 'aoû', 'sep', 'oct', 'nov', 'déc']
esc(s)                 // échappement HTML (& < > " ')
fmtNombre(n)           // n.toLocaleString('fr-FR')
fmtEuros(n)            // "587 053 €"
fmtEurosCompact(n)     // ≥ 1 000 000 → "4,7 M€" ; ≥ 10 000 → "587 k€" ; sinon fmtEuros
fmtMinutes(n)          // → { valeur, suffixe }
                       //   < 100 000        : exact           → { "84 210", "minutes perdues" }
                       //   < 10 000 000     : arrondi au millier → { "2 965 000", "minutes perdues" }
                       //   ≥ 10 000 000     : "35,4 M"        → { "35,4 M", "de minutes perdues" }
                       //   n ≤ 1 → suffixe singulier "minute perdue"
fmtDelta(pct)          // null → { texte: "n.d.", classe: "nd" } ; |pct| < 0.5 → { "= 0 %", "nd" }
                       // > 0 → { "▲ 18 %", "hausse" } ; < 0 → { "▼ 31 %", "baisse" } (entier, espace fine avant %)
fmtHeure(iso)          // "14 h 10" (heure de Paris)
fmtDate(iso)           // "10/09"
chargerJSON(url)       // fetch → objet ; 404 → null ; autre erreur → throw
renderClassement(el, lignes)
```
`renderClassement(el, lignes)` (même composant pour les deux pages, `lignes` déjà triées par le backend) :
- Lignes avec `minutes > 0` : une `.row` chacune — `.lbl` aux couleurs `fond`/`texte`, `.track` > `.fill`
  largeur `minutes / minutes_max × 100 %` (minimum 2 %), couleur `fond`, `.val` = `fmtEuros(cout_eur)`.
  `title` sur la ligne : « RER B — 928 300 minutes perdues · 139 incidents ».
- Lignes à 0 : dans un bloc `.plie` masqué (`hidden`), mêmes `.row` avec piste vide et `.val` « 0 € ».
  Sous la liste, style de la maquette (12 px, `padding-left: 66px`) :
  « + 4 lignes sans incident · <button>voir tout</button> » ; le bouton bascule `hidden` et devient
  « masquer ». Pas de ligne de repli s'il n'y a aucune ligne à 0.
- Toutes à 0 : « Aucune minute perdue sur la période. » puis le repli.
- Ne jamais injecter une chaîne du JSON sans `esc()`. Ignorer un `id` absent de `LIGNES`.

### Critères d'acceptation
- Aucun framework, aucune dépendance ; le fichier JS s'exécute sans erreur seul.
- `fmtMinutes(2964914).valeur === "2 965 000"` (séparateur de milliers de `toLocaleString('fr-FR')`).

---

## TASK-07 — Page `/statistiques`

### Fichier cible
`frontend/statistiques.html` (nouveau — remplace `stats.html`, que Claude Code supprimera après recette)

### Structure (ordre de la maquette `docs/maquettes/statistiques.html`)
`<link rel="stylesheet" href="bilan.css?v=1">`, `<script src="bilan.js?v=1">`, Roboto 400/500/700 via
Google Fonts. `<title>RETARDS IDF — Statistiques</title>`, `lang="fr"`.

1. **`.head`** : `.brand` « RETARDS <span rouge>IDF</span> » (lien vers `/`) ; à droite `.eyebrow`
   « 30 DERNIERS JOURS · TOUTES LIGNES » (N suit le sélecteur).
2. **`.liens`** : Aujourd'hui (`/`) · **Statistiques** (actif) · Année (`/annee`) · Méthode (`/methode.html`).
3. **`.toggle`** : trois `<button>` « 7 j », « 30 j », « 90 j ». Défaut 30. La période est lue/écrite dans
   `?p=7|30|90` (`history.replaceState`, valeur invalide → 30).
4. **`.hero`** : eyebrow « COÛT ESTIMÉ · SMIC BRUT » ; `.big` = `fmtNombre(total.cout_eur)` + `<small>€</small>` ;
   `.sub` = `fmtMinutes(total.minutes)` (valeur + `<small>suffixe</small>`) ; ligne 13 px
   « 752 incidents recensés » (singulier si 1, « Aucun incident recensé » si 0).
5. **`.note`** : « Somme exacte du classement par ligne ci-dessous. <a href="/methode.html#bilans">Méthode →</a> »
   et, si `jours_couverts < periode_jours` : « Données disponibles depuis le 10/09 (2 j sur 30). »
6. **Carte pire ligne** (`.card.worst`) : `border-left-color` = couleur de la ligne ; eyebrow
   « PIRE LIGNE · 30 J » ; badge aux couleurs de la ligne + « 928 300 minutes perdues · 139 incidents »
   (**pas de jours cumulés**) ; à droite pastille `.delta` via `fmtDelta(pire_ligne.delta_pct_minutes)`, avec
   `title="vs 30 jours précédents"` ou `title="période précédente incomplète"` si `null`.
   `pire_ligne === null` → bordure `var(--creux)`, texte « Aucune ligne touchée sur la période. », pas de pastille.
7. **Classement** : eyebrow « CLASSEMENT PAR TEMPS PERDU », `Bilan.renderClassement(el, data.lignes)`.
8. **`.two`** — deux cartes :
   - **Comparaison** : eyebrow « 30 J <span gris>vs</span> 30 J PRÉCÉDENTS ». Lignes `.line` :
     Incidents = `fmtNombre(total.incidents)` + `.mini` `fmtDelta(delta_pct.incidents)` ;
     Coût = `fmtEurosCompact(total.cout_eur)` + `.mini` `fmtDelta(delta_pct.cout_eur)` ;
     Pire ligne = nom de `pire_ligne` (ou « — »).
     Les valeurs affichées sont **celles de la période courante** (= les chiffres du haut), le delta porte sur
     elles. Si `delta_pct === null` : ligne 12 px gris clair sous la carte « Période précédente incomplète :
     comparaison indisponible. »
   - **Causes** : eyebrow « CAUSES ». Si ≤ 4 catégories : une `.line` par catégorie (`categorie` / `pct %`).
     Sinon les 3 premières puis une 4ᵉ ligne grisée (style de la maquette) regroupant le reste :
     libellés joints par « · » (2 max, puis « … »), pourcentage = 100 − somme des 3 premières.
     Sous la liste, 12 px gris clair : « Sur 13 perturbations déclarées par l'opérateur. »
     `total === 0` → « Aucune perturbation déclarée sur la période. »
9. **`.pied`** : « Données API PRIM · IDF Mobilités · mis à jour à 14 h 10 · recalcul toutes les 10 min ».

### Comportement
- `load(p)` : `main.setAttribute('aria-busy','true')`, `Bilan.chargerJSON('/data/statistiques-' + p + '.json')`,
  rendu complet de **tous** les blocs ci-dessus, puis `aria-busy` retiré. Les anciennes valeurs restent
  affichées pendant le chargement (pas de squelette ni de clignotement).
- Clics rapides : un compteur de requêtes ignore les réponses obsolètes.
- `null` (fichier absent) : message dans `main` « Bilan en cours de calcul, réessayer dans quelques minutes. »
  Erreur réseau : « Données indisponibles. »
- Aucun chiffre en dur dans le HTML : placeholders « — » avant le premier chargement.

### Critères d'acceptation
- Changer de période modifie les 3 chiffres du haut, la carte pire ligne, le classement, la comparaison et les
  causes.
- Le coût du haut est égal à la somme des `.val` du classement (visibles + repliées).
- Aucun « jours », « ans » ou « heures » affiché comme unité de durée.
- Lisible sans défilement horizontal à 360 px de large.

---

## TASK-08 — Page `/annee`

### Fichier cible
`frontend/annee.html` (nouveau)

### Structure (ordre de la maquette `docs/maquettes/annee.html`)
Mêmes `<head>`, `bilan.css`, `bilan.js` que TASK-07, plus
`<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>` (version déjà
utilisée par `stats.html`). `<title>RETARDS IDF — Bilan annuel</title>`.

Année affichée : `?annee=AAAA` (regex `^\d{4}$`), sinon année courante. Fichier `/data/annee-AAAA.json`.

1. **`.head`** : brand ; eyebrow « BILAN 2026 · TOUTES LIGNES », suivi de « · EN COURS » si `meta.en_cours`.
2. **`.liens`** : Aujourd'hui · Statistiques · **Année** (actif) · Méthode.
3. **`.hero`** : eyebrow « COÛT ESTIMÉ SUR L'ANNÉE · SMIC BRUT » ; `.big` coût total ; `.sub` minutes
   (`fmtMinutes`) ; « N incidents recensés ».
4. **`.note`** : 12 mois renseignés → « Cumul des 12 bilans mensuels. » ; sinon « Cumul des bilans mensuels
   disponibles : septembre (partiel). » (liste des `mois_renseignes`, « (partiel) » si `partiel`) ;
   puis « <a href="/methode.html#bilans">Méthode →</a> ».
5. **Graphe** (`.chart-wrap`) : eyebrow « COÛT MENSUEL — 2026 · € » ; à droite (style de la maquette), texte
   **calculé** « pic : janv. · creux : juil., août » à partir de `pire_mois` / `creux` (partie omise si
   absente, rien si les deux sont vides). `<canvas>` dans un conteneur `position:relative; height:210px`.
6. **`.two`** :
   - **Pire mois** (`.card.worst`, `border-left-color: var(--rouge)`, comme la barre du pic) : eyebrow
     « PIRE MOIS » ; `.big2` nom du mois (« Septembre ») ; ligne 13 px « 587 053 € · cause principale :
     travaux » (sans cause : « 587 053 € · 752 incidents ») ; « (mois partiel) » si `partiel`.
     `pire_mois === null` → « Aucune donnée. »
   - **Meilleure progression** (`.card.best`, bordure = couleur de la ligne) : eyebrow « MEILLEURE
     PROGRESSION » ; badge de la ligne + delta en 20 px couleur `encre` de la ligne (« −31 % ») ; ligne
     13 px « vs 2025 à date équivalente · seule ligne en recul » (ou « · 3 lignes en recul »).
     `null` et `annee_prec_disponible === false` → bordure `var(--creux)`, « Pas de comparaison : données 2025
     indisponibles. » ; `null` sinon → « Aucune ligne en recul vs 2025. »
7. **Classement** : eyebrow « CLASSEMENT ANNUEL PAR TEMPS PERDU », `Bilan.renderClassement`.
8. **`.pied`** : comme TASK-07.

### Graphe Chart.js (remplace les barres CSS statiques de la maquette)
- `type: 'bar'`, `labels` = `MOIS_COURT`, `data` = `mois[].cout_eur` (`null` → pas de barre).
- Couleur par barre : `pire_mois` → `#E1251B` ; mois dans `creux` → `#c9c1b1` ; mois `partiel` (hors pic) →
  `rgba(74,70,61,.45)` ; autres → `#4a463d`. `hoverBackgroundColor` identique.
- `borderRadius: { topLeft: 4, topRight: 4 }`, `borderSkipped: 'bottom'`, `maxBarThickness: 34`,
  `categoryPercentage: .9`, `barPercentage: .9`.
- **Axes épurés** : `y.display: false` (`beginAtZero: true`, `grace: '12%'` pour la place des étiquettes) ;
  `x.grid.display: false`, `x.border.color: '#e2dccf'`, ticks 10.5 px `#8a8478`, Roboto, en majuscules.
- `plugins.legend.display: false`.
- **Tooltip** : fond `#1a1a17`, titre = mois + année (« Septembre 2026 »), corps = `fmtEuros(cout)`, puis
  « 752 incidents », puis « mois partiel » si besoin. `displayColors: false`. Pas de tooltip sur un mois `null`.
- **Étiquettes au-dessus des barres** (comme la maquette) : petit plugin inline `afterDatasetsDraw` qui écrit
  la valeur en 10 px `#8a8478` au-dessus de chaque barre : ≥ 1 000 000 → « 1,2 M », ≥ 1 000 → « 720 k »,
  sinon la valeur. Si `chart.width < 420`, n'écrire que l'étiquette du pic.
- `responsive: true`, `maintainAspectRatio: false`.

### Comportement
Mêmes états que TASK-07 (`aria-busy`, `null` → « Pas de bilan pour 2025. », erreur réseau).

### Critères d'acceptation
- Coût du haut = Σ des coûts mensuels du graphe = Σ du classement.
- La barre rouge est toujours le mois de la carte « Pire mois ».
- Survol d'une barre : mois, coût, incidents.
- Pas d'axe Y ni de quadrillage ; lisible à 360 px.

---

## TASK-09 — Liens de navigation vers les nouvelles pages

### Fichiers cibles
`frontend/index.html`, `frontend/methode.html`

### Travail
- Dans `<nav>` (`.nav-links`) : `stats.html` → `/statistiques` ; ajouter `<li><a href="/annee">Année</a></li>`
  juste après Statistiques.
- Remplacer tout autre lien `stats.html` restant par `/statistiques`.
- Ne rien modifier d'autre (ni styles, ni scripts, ni couleurs de lignes).

### Critères d'acceptation
- `grep stats.html frontend/index.html frontend/methode.html` ne renvoie rien.

---

## TASK-10 — Tests unitaires

### Fichiers cibles
`tests/test_causes.py`, `tests/test_bilans.py` (nouveaux)

### Contexte
Style de `tests/test_metrics.py` : classes `TestXxx`, pytest, `asyncio_mode = auto` (`pytest.ini`).
Tester **uniquement les fonctions pures** (pas de base) ; les lignes `daily_metrics` sont des
`types.SimpleNamespace(date=…, line_id=…, nb_incidents=…, minutes_voyageurs=…)`.

### Cas à couvrir
`test_causes.py` :
- les 9 exemples réels de TASK-03 avec leur catégorie attendue (paramétré) ;
- un cas par catégorie : « Malaise voyageur à Châtelet » → Incident voyageur ; « Panne de signalisation à
  Gare du Nord » → Signalisation / infrastructure ; « Train en panne à Juvisy » → Panne matériel ;
  « Mouvement social local » → Mouvement social ; « Chute d'arbre sur les voies » → Météo ;
  « Travaux de modernisation » → Travaux ;
- « Les voyageurs sont invités à emprunter la ligne P » → **pas** Incident voyageur ;
- `None`, `""`, `"<p></p>"` → Non précisé ; `normaliser("P&#233;riode <br>")` → `"periode"`.

`test_bilans.py` :
- `cout_eur` : arrondi inférieur (`cout_eur(97, 12.31) == 19`, car 97 × 12,31 / 60 = 19,90) ;
- `delta_pct` : `None` si précédent `None` ou 0 ; `delta_pct(118, 100) == 18.0` ;
- `repartition_causes` : somme des pct = 100 pour 3 catégories à 1/3 ; tri ; liste vide ;
- `construire_statistiques` :
  - **invariant** `total == Σ lignes` sur un jeu de plusieurs lignes et jours dont les minutes produisent des
    arrondis (le total diffère de `cout_eur(Σ minutes)` : vérifier qu'on renvoie bien la somme des arrondis) ;
  - 13 lignes toujours présentes, triées par minutes décroissantes ; `line_id` inconnu ignoré ;
  - `pire_ligne` = première ligne ; `null` si tout est à 0 ;
  - fenêtre précédente incomplète → `total_prec`, `delta_pct`, deltas par ligne à `null` ;
  - fenêtre précédente complète → deltas calculés ;
  - une ligne `daily_metrics` datée de `du_prec − 1` n'est comptée nulle part ;
- `construire_annee` :
  - `total == Σ mois renseignés == Σ lignes` ;
  - mois hors `[debut_donnees, au_effectif]` → valeurs `null` ; mois en cours → `partiel: true` ;
  - `pire_mois` = coût max ; `creux` exclut les mois partiels et vaut `[]` avec moins de 3 mois complets ;
  - un mois à 50 % de la moyenne est un creux, un mois à 70 % ne l'est pas ;
  - `meilleure_progression` : la baisse la plus forte, `nb_lignes_en_recul` correct ; `null` si l'année
    précédente est indisponible ;
  - comparaison à date équivalente : une donnée de l'année précédente postérieure à `au_effectif − 1 an`
    n'entre pas dans le delta ;
  - `cause_principale` ignore « Non précisé » quand une autre catégorie existe.

### Critères d'acceptation
- Aucun test n'ouvre de connexion base ni réseau.

---

## TASK-11 — Page Méthode : section « Bilans »

### Fichier cible
`frontend/methode.html`

### Travail
Ajouter après la section `#perimetre` (et avant `#limites`, renuméroter `04` → `05`) une section
`<section id="bilans">` numérotée `04`, même structure HTML et mêmes classes que les sections voisines,
titre « Bilans statistiques et annuels ». Contenu, ton factuel :
- Les bilans sont recalculés toutes les 10 minutes à partir des métriques journalières par ligne.
- Le coût est arrondi à l'euro inférieur **par ligne et par jour**, puis additionné : le total affiché est
  exactement la somme du classement par ligne.
- `/statistiques` : fenêtres glissantes de 7, 30 ou 90 jours ; comparaison avec la période précédente de même
  durée, seulement si celle-ci est entièrement couverte par les données.
- `/annee` : cumul des bilans mensuels ; comparaison avec l'année précédente à date équivalente.
- Causes : réparties à partir des motifs des perturbations déclarées par l'opérateur (messages PRIM), classés
  par mots-clés en 7 catégories (lister `CATEGORIES`). Les retards temps réel n'ont pas de motif et n'entrent
  pas dans cette répartition. Un motif sans mot-clé reconnu est compté « Non précisé ».

### Critères d'acceptation
- Le lien `/methode.html#bilans` des deux pages pointe sur cette section.
- Aucun autre texte de la page modifié.

---

## TASK-12 — Aligner tout le site sur le SMIC 2026 (12,31 €/h)

### Fichiers cibles
`backend/bot.py`, `frontend/index.html`, `frontend/methode.html`

### Contexte
Après TASK-02, les bilans calculent à 12,31 €/h. L'accueil, le bot X et la page Méthode doivent utiliser le
même taux, sinon les pages se contredisent.

### Travail
1. `backend/bot.py` : supprimer la constante `SMIC_HORAIRE = 11.88` et lire `get_settings().smic_horaire`
   (déjà importable depuis `backend.config`). Le texte du tweet « Base SMIC 11,88€/h » affiche le taux lu, au
   format français : `f"{taux:.2f}".replace(".", ",")` → « Base SMIC 12,31€/h ».
2. `frontend/index.html` (l. 670-673) :
   ```js
   const SMIC_HORAIRE = 12.31;             // € brut/h depuis le 1er juin 2026 — même valeur que SMIC_HORAIRE (backend/config.py)
   const EUR_PAR_MIN  = SMIC_HORAIRE / 60;
   const SALAIRE_JOUR = SMIC_HORAIRE * 7;  // salaire journalier SMIC brut (7 h) ≈ 86 €
   ```
   Mettre à jour le commentaire au-dessus (« identiques à bot.py / backend/config.py »). Rien d'autre.
3. `frontend/methode.html` :
   - l. 446 : « 12,31 €/h depuis le 1er juin 2026 · source : arrêté du 22 mai 2026 · utilisé comme unité de
     mesure de l'impact humain » ;
   - l. 468 : `coût = minutes-voyageurs × 12,31 €/h ÷ 60` ;
   - l. 475 : exemple recalculé → « coût estimé = <strong>7 693 €</strong> » (37 500 × 12,31 / 60 = 7 693,75,
     arrondi à l'euro inférieur comme partout ailleurs).

### Critères d'acceptation
- `grep -rn "11[.,]88" backend frontend` ne renvoie rien.
- Le tweet, l'accueil, `/statistiques`, `/annee` et la page Méthode affichent ou utilisent 12,31 €/h.

---

## Vérification (Claude Code, après Deepseek)
1. `./venv/bin/python -m pytest` : tout vert, dont les nouveaux tests.
2. Lancer l'app, vérifier les 4 JSON dans `frontend/data/` et les invariants sur les vraies données.
3. `curl -I` : en-têtes `Cache-Control`, 301 de `/stats.html`.
4. Recette visuelle bureau + 390 px des deux pages, comparaison avec les maquettes ; changement de période.
5. `git rm frontend/stats.html`, mise à jour de `CLAUDE.md` / `TODO.md`, commit.
