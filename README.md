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
POLLING_INTERVAL_MINUTES=5
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
| GET | `/api/reference` | Paramètres de calcul (SMIC, relevés, quota PRIM, fréquentation) |
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
│   ├── main.py          # FastAPI + scheduler (collect + metrics + bilans + bot)
│   ├── api.py           # Endpoints REST
│   ├── collector.py     # Polling API PRIM
│   ├── metrics.py       # Calcul agrégats quotidiens
│   ├── bilans.py        # Bilans /statistiques et /annee → frontend/data/*.json
│   ├── causes.py        # Motifs PRIM → catégories de causes, texte lisible
│   ├── bot.py           # Post quotidien X (Twitter)
│   ├── models.py        # SQLAlchemy (Incident, DailyMetric)
│   ├── database.py      # Session async
│   └── config.py        # Settings (pydantic-settings)
├── frontend/
│   ├── index.html       # Compteur live
│   ├── statistiques.html  # Bilan 7 / 30 jours
│   ├── annee.html       # Bilan annuel (Chart.js)
│   ├── bilan.css / bilan.js  # Communs aux deux bilans
│   ├── nav.css          # Menu de navigation, commun aux 4 pages
│   ├── methode.html     # Transparence méthodologique
│   └── data/            # JSON des bilans, générés (ignorés par git)
├── data/
│   └── frequentation.json  # Fréquentation par ligne (màj mensuelle)
├── publications/        # Récaps quotidiens du bot, un fichier par jour (AAAA-MM-JJ.txt)
├── docs/maquettes/      # Maquettes de référence des bilans
├── tests/
│   ├── test_bilans.py
│   ├── test_bot.py
│   ├── test_causes.py
│   ├── test_collector.py
│   └── test_metrics.py
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
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
- Quota : 20 000 req/jour — polling 5 min ≈ 7 488 req/jour (13 lignes × 2 appels par relevé)
