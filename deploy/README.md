# Déploiement — VPS OVH

VPS : 2 vCPU, 4 Go RAM, 40 Go SSD, Ubuntu 24.

## Premier déploiement

### 1. Setup du VPS

```bash
# Depuis votre machine locale, en root sur le VPS
ssh root@<VPS_IP> 'bash -s' < deploy/setup-vps.sh
```

Le script installe Docker, crée l'utilisateur `rertracker`, configure le firewall (SSH + HTTP),
et clone le repo. Il s'arrête pour vous laisser configurer `.env`.

### 2. Configurer les variables d'environnement

```bash
ssh rertracker@<VPS_IP>
cd ~/rertracker
nano .env
```

Variables obligatoires :
- `PRIM_API_KEY` — clé API PRIM IDF Mobilités
- `POSTGRES_USER` / `POSTGRES_PASSWORD` — credentials PostgreSQL (choisir un vrai mot de passe)
- `DATABASE_URL` — doit correspondre aux credentials ci-dessus

### 3. Lancer l'application

```bash
cd ~/rertracker
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Vérifier : `curl http://localhost` doit retourner la page d'accueil.

### 4. Migrer les données existantes

Depuis le PC qui a la base locale :

```bash
bash deploy/migrate-data.sh <VPS_IP>
```

---

## Opérations courantes

### Mise à jour du code

```bash
ssh rertracker@<VPS_IP>
cd ~/rertracker
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

### Voir les logs

```bash
# Tous les logs
docker compose logs -f

# Backend uniquement
docker compose logs -f backend

# Les 100 dernières lignes
docker compose logs --tail=100 backend
```

### Backup de la base

```bash
docker compose exec db pg_dump -U ${POSTGRES_USER:-user} -Fc ${POSTGRES_DB:-retards_idf} > backup-$(date +%Y%m%d).pgdump
```

### Restaurer un backup

```bash
# Copier le dump dans le conteneur
docker cp backup.pgdump $(docker compose ps -q db):/tmp/backup.pgdump

# Restaurer
docker compose exec -T db pg_restore \
  --clean --if-exists --no-owner --no-privileges \
  -U ${POSTGRES_USER:-user} -d ${POSTGRES_DB:-retards_idf} \
  /tmp/backup.pgdump
```

### Recalculer les bilans

```bash
docker compose exec backend python -m backend.recalcul
```

### Reconstruire les données statiques

```bash
docker compose exec backend python -m backend.profils build
docker compose exec backend python -m backend.offre build
docker compose exec backend python -m backend.frequentation build
docker compose exec backend python -m backend.recalcul
```

### Redémarrer un service

```bash
docker compose restart backend
docker compose restart db
```

---

## Architecture Docker

```
docker-compose.yml          — config de base (dev)
docker-compose.prod.yml     — override prod (restart, logs, port 80, pas de --reload)
```

Lancement prod : toujours les deux fichiers :
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml <commande>
```

### Volumes persistants
| Volume | Contenu |
|--------|---------|
| `pgdata` | Données PostgreSQL |
| `./logs` | Logs applicatifs |
| `./data` | Données statiques (fréquentation, GTFS) |
| `./frontend/data` | Bilans JSON générés |
| `./transferts` | Exports/imports inter-PC |
| `./publications` | Publications bot X |
