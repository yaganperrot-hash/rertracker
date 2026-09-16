# RETARDS IDF — Compteur de retards en temps réel

Tableau de bord qui comptabilise les incidents, les minutes-voyageurs perdues
et le coût humain estimé des retards sur les lignes **RER et Transilien
d'Île-de-France**, en temps réel.

---

## Aperçu

- **Compteur live** : euros de temps de travail volé, calculé au SMIC brut (12,31 €/h depuis le 1er juin 2026)
- **Incidents en cours** : liste mise à jour toutes les 5 minutes depuis l'API PRIM
- **Tableau par ligne** : incidents, minutes-voyageurs et coût du jour
- **Statistiques** (`/statistiques`) : coût, minutes perdues et incidents sur 7 / 30 jours,
  classement par ligne, comparaison avec la période précédente, causes déclarées par l'opérateur
- **Bilan annuel** (`/annee`) : cumul des bilans mensuels, coût mois par mois, classement annuel
- Bilans recalculés toutes les 10 minutes en fichiers JSON statiques (aucune requête base par visiteur)
- **Bot X quotidien** : résumé automatique posté à 20h00

---

## Stack technique

| Composant       | Technologie              |
|----------------|--------------------------|
| Backend         | Python 3.12 + FastAPI    |
| Base de données | PostgreSQL 16            |
| ORM             | SQLAlchemy 2.x async     |
| Scheduler       | APScheduler 3.x          |
| Frontend        | HTML / CSS / JS vanilla  |
| Bot             | Tweepy 4.x               |
| Conteneurisation| Docker + docker-compose  |

---

## Lancement rapide

### Prérequis
- Docker et docker-compose installés

### 1. Variables d'environnement

```bash
cp .env.example .env
# Éditer .env avec vos credentials
```

Contenu de `.env` :

```env
PRIM_API_KEY=your_prim_api_key
TWITTER_API_KEY=your_twitter_key
TWITTER_API_SECRET=your_twitter_secret
TWITTER_ACCESS_TOKEN=your_access_token
TWITTER_ACCESS_SECRET=your_access_secret
DATABASE_URL=postgresql://user:password@db:5432/retards_idf
POLLING_INTERVAL_MINUTES=12
LOG_LEVEL=INFO
# SMIC_HORAIRE=12.31            # optionnel — € brut/h, base du coût estimé
# BILANS_INTERVAL_MINUTES=10    # optionnel — recalcul des bilans
```

> Les clés Twitter/X sont optionnelles — le bot est ignoré si elles sont absentes.
> `PRIM_API_KEY` est nécessaire pour la collecte réelle. Sans elle, le backend
> démarre mais ne collecte aucun incident.

### 2. Démarrer

```bash
docker-compose up -d
```

### 3. Accéder

| URL | Contenu |
|-----|---------|
| `http://localhost:8000` | Frontend (compteur live) |
| `http://localhost:8000/statistiques` | Bilan sur 7 / 30 jours |
| `http://localhost:8000/annee` | Bilan annuel |
| `http://localhost:8000/methode.html` | Méthode & transparence |
| `http://localhost:8000/docs` | API Swagger |

### 4. Logs

```bash
docker-compose logs -f backend
```

---

## API REST

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| GET | `/api/stats/today` | Stats agrégées du jour |
| GET | `/api/stats/line/{line_id}?period=30` | Stats d'une ligne sur N jours |
| GET | `/api/incidents/current` | Incidents ouverts en ce moment |
| GET | `/api/incidents/history` | Historique (filtres : ligne, dates) |
| GET | `/api/reference` | Paramètres de calcul (SMIC, relevés, quotas PRIM, fréquentation, offre, exemple calculé) |
| POST | `/api/admin/collect` | Déclencher une collecte manuelle |

**Exemple `line_id`** : `RER_A`, `RER_B`, `TRANSILIEN_J`, etc.

---

## Lignes couvertes

| RER | Transilien |
|-----|-----------|
| A · B · C · D · E | H · J · K · L · N · P · R · U |

---

## Méthode de calcul

### Minutes-voyageurs perdues

```
minutes-voyageurs = durée_incident (min) × (voyageurs_par_jour ÷ 18h ÷ 60 min)
```

### Coût estimé en euros

```
coût = minutes-voyageurs × 12,31 €/h (SMIC brut depuis le 1er juin 2026) ÷ 60
```

Dans les bilans, le coût est arrondi à l'euro inférieur par ligne et par jour, puis additionné :
un total affiché est toujours la somme exacte de son détail (lignes, mois).

Voir la [page Méthode](http://localhost:8000/methode.html) pour le détail complet,
les hypothèses et les limites.

---

## Bot X quotidien

Chaque jour à **20h00**, le bot rédige le bilan de la veille, l'enregistre dans
`publications/AAAA-MM-JJ.txt` (date de publication) et le poste sur X si les clés sont configurées :

```
📊 Bilan RER & Transilien IDF — 16/03/2026

🚨 23 incidents
⏱ 5 ans 152 jours de vie perdus collectivement
💶 9 377 € de temps de travail volé

📍 Lignes touchées : RER B · RER D · RER E

retardsidf.fr · #RER #Transilien #SNCF #RATP
```

Sans clés Twitter/X, la publication est seulement enregistrée dans le projet.
Le serveur doit tourner à 20h00 (tolérance d'1 h en cas de retard du scheduler).

---

## Structure du projet

```
/
├── backend/
│   ├── main.py            # FastAPI + scheduler
│   ├── api.py             # Endpoints REST
│   ├── collector.py       # Polling API PRIM (Estimated Timetable + perturbations Navitia)
│   ├── metrics.py         # Calcul minutes-voyageurs (voyageur par voyageur)
│   ├── profils.py         # Profils horaires depuis l'open data (build hors ligne) + jours types
│   ├── offre.py           # Offre GTFS : départs par gare, intervalles, missions (build hors ligne)
│   ├── frequentation.py   # Montées par train : comptages SNCF + validations IDFM (build hors ligne)
│   ├── recalcul.py        # Reconstruction des métriques depuis les incidents bruts
│   ├── bilans.py          # Génération JSON bilans
│   ├── causes.py          # Extraction causes incidents
│   ├── bot.py             # Récap quotidien X + publications/
│   ├── transfert.py       # Export/import incidents entre PC
│   ├── models.py          # SQLAlchemy (Incident, DailyMetric)
│   ├── database.py        # Session async PostgreSQL
│   ├── config.py          # Settings (pydantic-settings)
│   ├── relabel_transilien.py  # Migration unique : J/K/U → P/R/N (IDs PRIM corrigés le 15/09)
│   └── migrate_source.py
├── frontend/
│   ├── index.html         # Dashboard « aujourd'hui »
│   ├── statistiques.html  # Bilans 7j / 30j / année
│   ├── annee.html         # Vue par ligne (année)
│   ├── ligne.html         # Détail d'une ligne
│   ├── temps-reel.html    # Vue temps réel
│   ├── methode.html       # Page méthodologie
│   ├── carte.html         # Carte récap 1080×1080 (maquette réseaux sociaux)
│   ├── bilan.css / .js    # Styles + logique bilans
│   ├── nav.css            # Navigation unifiée
│   ├── pick.css / .js     # Sélecteur de ligne
│   ├── ticker.js          # Bandeau incidents
│   ├── duree.js           # Formatage durées
│   └── data/              # JSON statiques (gitignored)
├── data/
│   ├── frequentation.json      # Ancienne fréquentation par ligne (plus utilisée par le calcul)
│   ├── frequentation_gares.json # Montées dans un train par ligne, gare, jour type et heure
│   ├── offre_theorique.json    # Offre GTFS : départs par gare, intervalles, missions, noms d'arrêts
│   └── profils_horaires.json   # Profils horaires par réseau et jour type + vacances scolaires
├── docs/maquettes/        # Maquettes de référence
├── publications/          # Récaps quotidiens (AAAA-MM-JJ.txt)
├── tests/                 # pytest (test_*.py)
├── transferts/            # Exports JSON incidents inter-PC
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── pytest.ini
├── .env.example
└── .gitignore
```

---

## Tests

```bash
# Dans le container ou avec un venv local
pytest tests/ -v
```

---

## Source de données

- **API PRIM** — Île-de-France Mobilités
- Endpoint : `https://prim.iledefrance-mobilites.fr/marketplace/`
- Licence : Open Data Etalab
- Quota : 1 000 req/jour (en-têtes `x-ratelimit-*`) — relevé toutes les 20 min de 6 h à minuit,
  2 appels perturbations + 13 appels départs par relevé (810 req/jour)