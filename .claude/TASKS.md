# TASKS — Pour Deepseek

> Règle absolue : **ne jamais lancer de commande terminal.**
> Lire les fichiers, écrire du code, c'est tout.

---

## TASK-01 — Corriger l'endpoint PRIM dans collector.py

**Fichier cible** : `backend/collector.py`

**Contexte**
Le swagger PRIM (`swagger.json`) révèle que l'API est :
- `basePath` : `/marketplace/v2/navitia/line_reports`
- Endpoints : `GET /line_reports` et `GET /{uri}/line_reports`

Le code actuel appelle `/marketplace/disruptions/` qui n'existe pas dans ce swagger.

**Ce qu'il faut changer**

1. Remplacer `PRIM_BASE_URL` :
   ```python
   # Avant
   PRIM_BASE_URL = "https://prim.iledefrance-mobilites.fr/marketplace"
   # Après
   PRIM_BASE_URL = "https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia"
   ```

2. Remplacer l'endpoint dans `collect_disruptions()` :
   ```python
   # Avant
   f"{PRIM_BASE_URL}/disruptions/"
   # Après
   f"{PRIM_BASE_URL}/line_reports"
   ```

3. Ajouter `disable_geojson=true` aux params pour réduire la taille des réponses.

4. Adapter la clé de parsing de la réponse :
   - L'endpoint `line_reports` retourne probablement `{ "line_reports": [...], "disruptions": [...] }`
   - Les disruptions sont dans la clé `"disruptions"` au niveau racine de la réponse (structure Navitia standard)
   - Vérifier que `data.get("disruptions", [])` reste correct, sinon adapter

**Critères d'acceptation**
- `PRIM_BASE_URL` pointe vers `/marketplace/v2/navitia`
- L'URL appelée est `…/line_reports` (pas `/disruptions/`)
- `disable_geojson=true` est dans les params
- Le parsing `impacted_objects → pt_object → id` reste intact (il est correct)

---

## TASK-02 — Corriger la constante PRIM dans CLAUDE.md

**Fichier cible** : `CLAUDE.md`

**Contexte**
La ligne suivante dans CLAUDE.md est incorrecte :
```
- Endpoint : `https://prim.iledefrance-mobilites.fr/marketplace/`
```

**Ce qu'il faut changer**
Remplacer par :
```
- Endpoint : `https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia/line_reports`
```

**Critères d'acceptation**
- L'URL dans CLAUDE.md reflète le bon endpoint documenté dans le swagger

---

## TASK-03 — Mettre à jour le test unitaire collector

**Fichier cible** : `tests/test_collector.py`

**Contexte**
Le test mock l'URL `/disruptions/` qui va changer en `/line_reports`.
Il faut lire le fichier test actuel et adapter les mocks/fixtures en conséquence.

**Ce qu'il faut changer**
1. Lire `tests/test_collector.py`
2. Remplacer toute occurrence de `/disruptions` par `/line_reports` dans les mocks httpx
3. Adapter le payload de réponse mocké si nécessaire (vérifier la clé `disruptions` vs `line_reports`)

**Critères d'acceptation**
- Les mocks httpx pointent vers la nouvelle URL
- Le payload mocké correspond à la structure réelle retournée par `/line_reports`
