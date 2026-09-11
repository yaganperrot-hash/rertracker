# TASKS Deepseek

> TASK-01 (`duree_minutes` / `heure_fin` dans `/api/incidents/current`) : ✅ terminée, déjà en place dans `backend/api.py`.

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
