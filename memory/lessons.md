# Leçons apprises

## Pièges Python / FastAPI
- `pydantic-settings` est un package séparé depuis Pydantic v2 — `BaseSettings` n'est plus dans `pydantic`. Toujours l'ajouter à `requirements.txt`.
- `DATABASE_URL` avec préfixe `postgresql://` ne fonctionne pas avec asyncpg — convertir en `postgresql+asyncpg://` au runtime dans `database.py`.

## Pastilles / badges de ligne
- Ne jamais utiliser `grid-template-columns: repeat(N, 1fr)` pour des cercles : les colonnes `1fr` étirent les éléments. Utiliser `display:flex; flex-wrap:wrap` avec `flex:none` sur chaque pastille.
- Taille fixe en px par contexte (grille: 88px, en-tête panneau: 40px, tableau: 28px). Font = ~0.42 × diamètre.
- Centrage par flexbox uniquement (`display:flex; align-items:center; justify-content:center; line-height:1`). Jamais de padding ou line-height pour centrer.
- Contraste : fonds clairs (RER C, Transilien J/K/P/R) → texte `#1A1916` via `data-tc="dark"`.

## LINE_META dupliqué
- `LINE_META` est copié dans 3 fichiers (`index.html`, `temps-reel.html`, `ligne.html`). Toute modification (ex: ajout `textColor`) doit être propagée aux 3. Piste future : factoriser dans un fichier partagé.

## Picker
- Le composant `Pick` (pick.js + pick.css) est partagé entre `/` et `/:slug`. Les onglets réseau ont été remplacés par des groupes toujours visibles — plus simple et plus scannable.

## Bilans / JSON statiques
- Le pattern `_ecrire()` (écriture atomique .tmp → rename) est réutilisable pour tout nouveau JSON statique.
- Toujours appeler `generer_bilans()` manuellement après ajout d'un nouveau fichier JSON, sinon la page affiche "Bilan en cours de calcul" jusqu'au prochain cycle scheduler.
- Les données `hall-of-shame.json` contiennent les 3 périodes (semaine/mois/année) dans un seul fichier — le frontend filtre côté client.

## Cohérence cross-pages
- Les styles hero/cumul sont dupliqués dans chaque HTML (pas de CSS partagé). Toute modification de taille/couleur doit être propagée sur les 5 pages : `index.html`, `temps-reel.html`, `statistiques.html`, `ligne.html`, `methode.html`.
- Valeurs de référence (accueil) : compteur `clamp(52px, 10.4vw, 112px)` 900, cumul `clamp(24px, 4vw, 35px)` 700 red, subtitle `clamp(16px, 2.4vw, 22px)` 500, labels 10-11px.
- Le ticker CSS est dupliqué dans chaque page, le JS partagé (`ticker.js`). Chaque page doit appeler
  `Ticker.charger()` (ou `Ticker.render()`), sinon le bandeau reste sur « Chargement… ». Vitesse constante
  `VITESSE_PX_S = 45` : une durée CSS fixe fait défiler un texte long beaucoup trop vite.
- Pour déborder un élément hors de son conteneur max-width : `margin-inline: calc(-50vw + 50%)`.

## APScheduler — race conditions
- Ne jamais lancer en parallèle des jobs qui ont une dépendance séquentielle (ex: collecte → métriques). Utiliser un seul job qui enchaîne les étapes, ou `await` séquentiel au démarrage.
- `next_run_time=datetime.now()` sur plusieurs jobs = exécution simultanée = race condition garantie.
- Pour les métriques quotidiennes avec fenêtre 07h-07h : prévoir un recalcul de la veille au démarrage ET un cron à 07h05 pour finaliser.

## Travail sur deux PC
- Chaque PC a **sa propre base PostgreSQL** : seul git est partagé. Un compteur à 0 sur un PC alors que l'autre affiche des chiffres n'est pas une perte de données — demander d'abord sur quel PC les chiffres ont été vus.
- En début de session : `git fetch` + `git pull --ff-only`. Les `publications/*.txt` générés localement entrent en conflit avec ceux du distant → garder la version du PC dont la base est la plus complète.
- Le `.env` n'est pas versionné : quand un défaut change dans `config.py` (ex. polling 5 → 15 min), vérifier que le `.env` de chaque PC ne l'écrase pas.
- Changer de PC en cours de journée : `python -m backend.transfert export` (serveur arrêté), commit + push, puis `import` sur l'autre PC avant de lancer son serveur. Les ids (`rt_{train}_{AAAAMMJJ}`, id de disruption PRIM) sont identiques d'un PC à l'autre, donc la fusion ne crée pas de doublon.

## Métriques "par usager" — piège de la dilution
- Diviser `minutes_voyageurs` par la fréquentation totale du jour donne un chiffre minuscule : on répartit le retard sur TOUS les voyageurs, y compris les 99% non impactés.
- Diviser le coût total collectif par le nombre d'incidents n'a pas de sens non plus : c'est un coût agrégé de milliers de voyageurs.
- La bonne formule pour "retard moyen vécu par un usager retardé" : `Σ(durée_i × poids_horaire_i) / Σ(poids_horaire_i)` — moyenne des durées pondérée par le flux de voyageurs à l'heure de l'incident.
- Ce calcul nécessite de requêter les incidents individuels (pas les DailyMetric agrégés), mais reste performant même sur 782 incidents.

## Tester une opération sur la base sans risque
- Copie jetable : `createdb X && pg_dump -t incidents -t daily_metrics retards_idf | psql -d X`, puis lancer le script avec `DATABASE_URL=postgresql://…/X` (la variable d'environnement prime sur `.env`). Attention : `generer_bilans()` écrit dans `frontend/data/` quelle que soit la base → régénérer depuis la vraie base après le test.
- Un réimport de ses propres données doit laisser la base strictement identique (même `count`, même `sum`, mêmes totaux du jour) : bon test d'idempotence.

## PRIM / Navitia
- `line_reports` global (sans filtre) répond 200 avec 0 résultat ; `physical_modes/physical_mode:RapidTransit` (5 RER)
  et `physical_mode:LocalTrain` (8 Transilien) renvoient tout, en 1 appel chacun.
- Une interruption (`NO_SERVICE`) ne liste que la ligne dans `impacted_objects` : ni gares, ni tronçon, ni trains —
  le tronçon n'existe qu'en texte libre. Inexploitable pour chiffrer une coupure.
- La plupart des perturbations d'une ligne sont des pannes d'ascenseur en `SIGNIFICANT_DELAYS` valables 1 an :
  l'effet PRIM ne mesure rien, d'où le filtre > 12 h.
- `data_freshness` d'un départ : `base_schedule` sur une ligne de bus (pas de temps réel) — un ID qui ne remonte
  jamais de retard est d'abord un ID à vérifier.
- « Ça tenait les autres jours » : vérifier le rythme réel en base (relevés distincts par heure) avant de le croire —
  les 13 et 14/09 tournaient à 15 min, pas à 5.
- Pendant une interruption, les trains du tronçon coupé disparaissent des départs `realtime` ; le détail par arrêt
  (`deleted`, `no_boarding`) n'existe que via `/vehicle_journeys/{id}`, pas dans `line_reports`.

## Migration de données + transferts entre PC
- Un script qui corrige des étiquettes en base doit être lancé entre les imports : d'abord les exports faits
  avant le correctif, puis le script, puis ceux faits après. Sinon les données déjà justes sont « corrigées » à tort.
- Table témoin (`migrations_appliquees`) + sauvegarde `CREATE TABLE … AS SELECT` : migration rejouable sans risque.

## Exploitation
- Jamais de `git stash` (ni de checkout) pendant qu'un serveur démarre en parallèle : il peut importer l'ancien code.
- Une page qui décrit le calcul (Méthode) dérive du code : servir chaque paramètre par `/api/reference` et tester
  que les valeurs servies sont celles du code.
- Un état horodaté (dernier relevé, quota restant) se relit dans les logs à chaque question, avec `date` : un chiffre
  donné une heure plus tôt paraît être une panne de collecte alors qu'il est seulement périmé.
