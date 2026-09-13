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

## APScheduler — race conditions
- Ne jamais lancer en parallèle des jobs qui ont une dépendance séquentielle (ex: collecte → métriques). Utiliser un seul job qui enchaîne les étapes, ou `await` séquentiel au démarrage.
- `next_run_time=datetime.now()` sur plusieurs jobs = exécution simultanée = race condition garantie.
- Pour les métriques quotidiennes avec fenêtre 07h-07h : prévoir un recalcul de la veille au démarrage ET un cron à 07h05 pour finaliser.
