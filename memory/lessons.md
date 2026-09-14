# Leçons apprises

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
- Le ticker CSS+JS est aussi dupliqué dans chaque page. Vitesse = 45s.
- Pour déborder un élément hors de son conteneur max-width : `margin-inline: calc(-50vw + 50%)`.

## APScheduler — race conditions
- Ne jamais lancer en parallèle des jobs qui ont une dépendance séquentielle (ex: collecte → métriques). Utiliser un seul job qui enchaîne les étapes, ou `await` séquentiel au démarrage.
- `next_run_time=datetime.now()` sur plusieurs jobs = exécution simultanée = race condition garantie.
- Pour les métriques quotidiennes avec fenêtre 07h-07h : prévoir un recalcul de la veille au démarrage ET un cron à 07h05 pour finaliser.

## Travail sur deux PC
- Chaque PC a **sa propre base PostgreSQL** : seul git est partagé. Un compteur à 0 sur un PC alors que l'autre affiche des chiffres n'est pas une perte de données — demander d'abord sur quel PC les chiffres ont été vus.
- Un seul serveur à la fois : les deux PC partagent la même clé PRIM, deux collectes simultanées (~896 req/j chacune) dépassent le quota de 1 000.
- En début de session : `git fetch` + `git pull --ff-only`. Les `publications/*.txt` générés localement entrent en conflit avec ceux du distant → garder la version du PC dont la base est la plus complète.
- Le `.env` n'est pas versionné : quand un défaut change dans `config.py` (ex. polling 5 → 15 min), vérifier que le `.env` de chaque PC ne l'écrase pas.
- Changer de PC en cours de journée : `python -m backend.transfert export` (serveur arrêté), commit + push, puis `import` sur l'autre PC avant de lancer son serveur. Les ids (`rt_{train}_{AAAAMMJJ}`, id de disruption PRIM) sont identiques d'un PC à l'autre, donc la fusion ne crée pas de doublon.

## Tester une opération sur la base sans risque
- Copie jetable : `createdb X && pg_dump -t incidents -t daily_metrics retards_idf | psql -d X`, puis lancer le script avec `DATABASE_URL=postgresql://…/X` (la variable d'environnement prime sur `.env`). Attention : `generer_bilans()` écrit dans `frontend/data/` quelle que soit la base → régénérer depuis la vraie base après le test.
- Un réimport de ses propres données doit laisser la base strictement identique (même `count`, même `sum`, mêmes totaux du jour) : bon test d'idempotence.
