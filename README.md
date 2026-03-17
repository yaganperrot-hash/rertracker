# RETARDS IDF — Compteur de retards en temps réel

Tableau de bord qui comptabilise les incidents, les minutes-voyageurs perdues
et le coût humain estimé des retards sur les lignes **RER et Transilien
d'Île-de-France**, en temps réel.

---

## Aperçu

- **Compteur live** : euros de temps de travail volé, calculé au SMIC brut 2025
- **Incidents en cours** : liste mise à jour toutes les 5 minutes depuis l'API PRIM
- **Tableau par ligne** : incidents, minutes-voyageurs, coût jour/mois
- **Page statistiques** : classements et graphiques par période (7 / 30 / 90 jours)
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
| `http://localhost:8000/stats.html` | Statistiques par ligne |
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
coût = minutes-voyageurs × 11,88 €/h (SMIC brut 2025) ÷ 60
```

Voir la [page Méthode](http://localhost:8000/methode.html) pour le détail complet,
les hypothèses et les limites.

---

## Bot X quotidien

Le bot poste un résumé chaque jour à **20h00** :

```
📊 Bilan RER & Transilien IDF — 16/03/2026

🚨 23 incidents
⏱ 2 847 340 min-voyageurs perdues
💶 9 377 € de temps de travail volé

📍 Lignes touchées : RER B · RER D · RER E

retardsidf.fr · #RER #Transilien #SNCF #RATP
```

Le bot est silencieux si les clés Twitter/X ne sont pas configurées.

---

## Structure du projet

```
/
├── backend/
│   ├── main.py          # FastAPI + scheduler (collect + metrics + bot)
│   ├── api.py           # Endpoints REST
│   ├── collector.py     # Polling API PRIM
│   ├── metrics.py       # Calcul agrégats quotidiens
│   ├── bot.py           # Post quotidien X (Twitter)
│   ├── models.py        # SQLAlchemy (Incident, DailyMetric)
│   ├── database.py      # Session async
│   └── config.py        # Settings (pydantic-settings)
├── frontend/
│   ├── index.html       # Compteur live
│   ├── stats.html       # Statistiques & graphiques
│   └── methode.html     # Transparence méthodologique
├── data/
│   └── frequentation.json  # Fréquentation par ligne (màj mensuelle)
├── tests/
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
- Quota : 20 000 req/jour — polling 5 min ≈ 288 req/jour
