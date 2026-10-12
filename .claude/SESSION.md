# SESSION — État courant

## 2026-10-11 — Windows (historique : `.claude/archive/`)

### Objectif
Carrousel Instagram (5 slides PNG) + corrections carte X + fix durée.

### Avancement
- **Carrousel Instagram** : `frontend/carousel.html` — 5 slides 1080×1080 (coût du jour, équivalent
  salaire infirmier mensuel arrondi en dessous, pire/meilleure ligne par ratio, CTA).
  Génération PNG via Playwright : `backend/bot.py:generer_carousel_png()` → `output/AAAA-MM-JJ/slide-N.png`.
  Appelée dans `post_daily_recap()` après la carte.
- **Endpoint `/api/stats/today/lines`** : métriques du jour par ligne + `trains_prevus` (GTFS + catégorie jour).
- **Fix durée** : jours ≥ 7 → omettre les heures (`duree.js` + `bot.py:_fmt_duree()`).
- **Fix carte X** (`carte.html`) :
  - Hero centré, montant en noir (pas rouge), durée en rouge.
  - Bandeau noir viré → "soit X jours de vie perdus collectivement" en rouge.
  - Chiffres des barres en euros (pas en minutes-voyageurs).
- **TODO.md** : bug partager noté. `.gitignore` : `output/` ajouté.
- **Tests** : 328/328 OK.

### Blocages
- **Clé PRIM à régénérer** (inchangé).

### Prochaine étape
1. Régénérer la clé PRIM.
2. Publication automatique Instagram (API Graph) si pertinent.
3. Investiguer le bug du bouton partager.

### Serveur
- **Production sur le VPS OVH depuis le 2026-10-12** : seul serveur qui collecte. Aucun serveur à lancer sur les PC.
- 2026-10-12 (Mac) : `--workers 1` dans `docker-compose.prod.yml` (un scheduler par worker = relevés PRIM en double),
  redéployé et vérifié sur le VPS (un relevé par intervalle). Doc et commandes `/start`, `/wrap` alignées sur le VPS.
- VPS : `ssh ubuntu@149.56.102.94` (clé du Mac installée), application dans `/home/ubuntu/rertracker` — il n'y a pas
  d'utilisateur `rertracker`. Image du bot du 11/10 générée par le VPS mise de côté dans `~/sauvegarde-publications/`.
- Ce Mac n'a plus ni venv, ni Python 3.12, ni Docker : les tests se lancent sur le VPS, hors réseau —
  `docker run --rm --network none -e DATABASE_URL=postgresql://test:test@127.0.0.1:1/test -e PRIM_API_KEY=test rertracker-backend python -m pytest -q`
  (328 passés le 12/10).
