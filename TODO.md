# TODO — Compteur de Retards IDF

## En cours
- [ ] **Fiabilité du calcul (2026-09-17)** — voir `.claude/DEBUG.md`, session du 17/09 :
  - [x] Plafond remplacé par l'écart mesuré avec le train suivant, par destination (bug 35) ; historique recalculé sur le Mac
  - [x] Réponses brutes du flux archivées dans `logs/flux_brut/` (3 jours)
  - [x] **B — arrêts sautés** : détection validée le 2026-10-04 — 65 trains, 236 arrêts sautés depuis le 22/09
    (nouvelle règle), 64/65 en milieu de trajet (vrais sauts, pas des trains limités). Réintégrés dans le coût :
    `metrics.py:195` traite `k=True` comme `s=True`. Impact : +81 874 min-voy sur la période. Recalcul historique fait
  - [x] **C — passé visible** (2026-09-22) : mesuré 1,2 min en médiane pour un train en circulation (p95 15 min),
    ~14 min après le terminus ; `lessons.md` corrigé ; pas d'angle mort dans `attentes_mesurees`
  - [ ] **D — trains absents du flux** (coupures) : diagnostic réparé le 2026-09-22 (bug 45 : horaires GTFS périmés,
    trains arrivés au terminus attendus à tort). Observer les logs « absents du flux » quelques jours avant d'en tirer
    des suppressions
  - [x] **E — suppression levée toujours comptée** (bug 46, 2026-09-22) : `is_cancelled` dérivé des arrêts
    fusionnés ; 42 suppressions levées au recalcul (753 → 711), minutes-voyageurs inchangées
  - [x] **Requêtes API et quotas** (17/09) : temps réel toutes les 5 min en 1 appel global (`LineRef=ALL`, 216 req/jour),
    perturbations toutes les 20 min (108), pas de relevé au redémarrage si le dernier date de moins d'un intervalle ;
    retard/suppression mesurés seulement à moins de 10 min du passage estimé
  - [x] **Fenêtre de 10 min** (2026-09-22) : gardée — 5 min ferait passer la couverture de 67,7 % à 53,3 % sans
    réduire l'écart au retard constaté (~+8 % quelle que soit la fenêtre). Piste : 15 min (79,7 %)
  - [ ] Surveiller après la bascule : taille de `logs/flux_brut/` (~9 Mo de JSON par relevé avant gzip), durée de
    `compute_daily_metrics` toutes les 5 min, `ECART_MAX_RELEVES` (45 min) pour les arrêts sautés
- [ ] **« Mon trajet » (bêta, aller simple, 2026-09-17)** — suite : aller-retour, correspondances entre lignes,
  garder les horaires passés quand le GTFS est reconstruit (`data/horaires.json.gz` ne couvre que sa fenêtre de 30 jours)
- [ ] **PC Windows** : `git pull`, serveur arrêté, `python -m backend.recalcul` (plafond remplacé le 17/09),
  `POLLING_INTERVAL_MINUTES=5` dans `.env` (collecte globale du 17/09)
- [x] **Mac** : transferts du 15 au 18/09 importés, recalcul fait (2026-09-18)
- [ ] **PC Windows — après `git pull` (2026-09-18)** : serveur arrêté, `python -m backend.recalcul` (journée depuis 6 h,
  trains supprimés réparés, données fiables depuis le 16/09) ; lancer le serveur avec la veille empêchée
- [ ] **Audit des chiffres (2026-09-18)** — faits : panneau de ligne, journée depuis 6 h, données fiables, suppressions,
  bot sans « Métro », séparateur des milliers ; puis Mon trajet (JSON « null »), arrêts sautés hors coût,
  Statistiques en périodes calendaires, page Méthode, salaires journaliers, accord de la Carte. Attentes > 1 h
  vérifiées : vraies perturbations (Viroflay 17/09, RER D 18/09). Reste : `statistiques-{7,30}.json` générés mais
  lus par aucune page (à supprimer ou à brancher)
- [ ] Lot 5 (valeur du temps) : décidé le 2026-09-16 de garder le SMIC seul — TASK-29/30 abandonnées.

## Bugs
- [ ] **Bug : la fonction partager** (bouton Share dans le pick panel) ne fonctionne pas — à investiguer.

## À faire
- [ ] **PC Windows — recalculer l'historique** après `git pull` : `python -m backend.recalcul`.
  Sa base est encore calculée avec les anciens poids horaires ; sans ça les deux PC afficheront des
  chiffres différents pour les mêmes jours.
- [ ] **Régénérer `data/profils_horaires.json` à chaque trimestre** publié par IDFM :
  `python -m backend.profils build`, puis `python -m backend.recalcul` sur chaque PC.
  Le nom du jeu de données porte le trimestre (`…-3eme-trimestre`) — à mettre à jour dans `backend/profils.py`.
- [ ] **Régénérer `data/offre_theorique.json` puis `data/frequentation_gares.json` au moins chaque mois** (le GTFS ne
  couvre que 30 jours ; les jours de vacances y reprennent l'offre hors vacances tant qu'aucun n'est dans la fenêtre ;
  les comptages SNCF sont mis à jour par campagne) : `python -m backend.offre build`,
  `python -m backend.frequentation build`, puis `python -m backend.recalcul` sur chaque PC.
  Avec eux, `python -m backend.offre horaires` (« Mon trajet », fenêtre GTFS actuelle : 19/09 → 21/10).
  **Les horaires se reconstruisent à chaque publication GTFS** (nouveaux `trip_id`, bug 45) : le warning
  « Horaires GTFS périmés » dans les logs le signale.
- [ ] Surveiller `data/frequentation_gares.json` → `perdus` et `origine` « inconnue » après chaque build (gare renommée
  dans le GTFS ou les comptages).
- [ ] Valider la maquette `frontend/carte.html`, puis reprendre le plan X/Instagram :
  script `backend/carte.py`, envoi X avec repli texte seul, module Instagram inerte sans `PUBLIC_BASE_URL`.
- [ ] **Régénérer la clé PRIM** (en clair dans l'historique git, commit `c591442`) — urgent
- [ ] Vérifier visuellement le rendu des durées lisibles (bureau + mobile 390 px)
- [ ] Renseigner les clés Twitter/X dans `.env`
- [ ] Vérifier les causes des perturbations (catégorisation `causes.py` vs motifs réels PRIM)
- [ ] **Piste c — trains supprimés pendant une interruption** (en attente d'une interruption en cours).
  Dès qu'une perturbation `NO_SERVICE` est active :
  1. récupérer pour la ligne touchée les départs prévus (`base_schedule`) et temps réel (`realtime`) ;
  2. vérifier si les trains du tronçon coupé disparaissent du temps réel ou y restent marqués supprimés ;
  3. si PRIM les expose : proposer une détection limitée aux lignes en interruption (quelques requêtes pendant
     la coupure seulement), puis décider du temps compté par train supprimé (forfait 5 min ou attente du suivant).
  Contexte 2026-09-15 : la perturbation PRIM ne liste ni gares ni trains (tronçon en texte libre) ; piste b
  (chiffrer l'interruption depuis le message) abandonnée, expliquée dans `methode.html` → Limites.
  **Test du 2026-09-15 à 10 h 42** (L Versailles RD–Saint-Cloud, D Corbeil–Malesherbes) : les trains du tronçon coupé
  disparaissent des départs `realtime` (présents en `base_schedule`) puis réapparaissent après la coupure ;
  `/vehicle_journeys/{id}` détaille chaque arrêt (`deleted` / `no_boarding` / `delayed`) → suppression partielle
  mesurable. Mais ce détail n'est PAS dans `line_reports` : il faut des requêtes en plus, incompatible avec le budget
  actuel (810 / 1 000 req/jour). À reprendre si du quota se libère.

## Terminé
- [x] Étape 01 — CLAUDE.md structuré créé — 2026-03-11
- [x] Étape 02 — TODO.md créé — 2026-03-11
- [x] Étape 03 — git init + .gitignore + structure dossiers — 2026-03-11
- [x] Étape 04 — Docker + PostgreSQL (docker-compose.yml, Dockerfile) — 2026-03-11
- [x] Étape 05 — Modèles SQLAlchemy (backend/models.py, backend/database.py, backend/config.py) — 2026-03-11
- [x] Étape 06 — Collector PRIM (backend/collector.py, data/frequentation.json) — 2026-03-11
- [x] Étape 07 — Calcul des métriques (backend/metrics.py) — 2026-03-11
- [x] Étape 08 — Endpoints API REST (backend/api.py, backend/main.py) — 2026-03-11
- [x] Étape 09 — Frontend page principale (frontend/index.html) — 2026-03-17
- [x] Étape 10 — Frontend page statistiques (frontend/stats.html) — 2026-03-17
- [x] Étape 11 — Bot X quotidien (backend/bot.py) — 2026-03-17
- [x] Étape 12 — Page /methode (frontend/methode.html) — 2026-03-17
- [x] Étape 13 — Tests unitaires (tests/test_collector.py, tests/test_metrics.py) — 2026-03-17
- [x] Étape 14 — README.md final — 2026-03-17
- [x] Correctifs session 2026-04-28 — endpoint PRIM, duree_minutes, filtres, frontend
- [x] Correctifs session 2026-09-09 — 8 bugs corrigés (double comptage, timezone, trains supprimés, pondération horaire, fake counter, etc.)
- [x] Session 2026-09-10 — setup local Mac, retards RT (gare/train/direction), dédoublonnage par train, fuseau Paris, suppressions, lisibilité accueil
- [x] Durées lisibles min → h → jours → ans (`frontend/duree.js`, `bot.py`, tests) — 2026-09-10
- [x] Pages `/statistiques` et `/annee` (maquettes `docs/maquettes/`, TASK-02 → TASK-12) : bilans JSON
  statiques recalculés toutes les 10 min, totaux réconciliés, causes depuis les motifs opérateur, Chart.js ;
  SMIC 2026 à 12,31 €/h partout ; `stats.html` supprimée (301 vers `/statistiques`) — 2026-09-11
- [x] Menu de l'accueil sur les 4 pages, sélecteur 7 jours · 30 jours · Année — 2026-09-11
- [x] Zéro donnée en dur : coûts calculés par le backend, `/api/reference`, bandeau réel — 2026-09-11
- [x] Récap quotidien de 20 h enregistré dans `publications/` sans compte X — 2026-09-11
- [x] Bug 9 — HOURLY_WEIGHTS aligné sur 19.2 (test corrigé) — 2026-09-11
- [x] Bug 10 — 5 tests collector réalignés (mocks, statuts, heures) — 2026-09-11
- [x] Bug 11 — Logging diagnostic ajouté pour Transilien L/N/P/R à 0 incident — 2026-09-11
- [x] Bug 17 — `_parse_dt` corrigé : timestamps PRIM lus en Europe/Paris au lieu d'UTC — 2026-09-11
- [x] Refonte typo `methode.html` alignée sur l'accueil (--muted #555, --sub #333, 16px, graisse 400) — 2026-09-11
- [x] Bot récap : bilan du jour même au lieu de la veille — 2026-09-11
