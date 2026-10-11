#!/usr/bin/env bash
# migrate-data.sh — Migrer la base PostgreSQL locale vers le VPS
# Usage : bash deploy/migrate-data.sh <VPS_IP> [DUMP_FILE]
set -euo pipefail

VPS_IP="${1:?Usage: $0 <VPS_IP> [DUMP_FILE]}"
DUMP_FILE="${2:-dump.pgdump}"
VPS_USER="rertracker"
APP_DIR="/home/$VPS_USER/rertracker"

echo "=== Migration de la base PostgreSQL vers $VPS_IP ==="

# --- Étape 1 : Export local ---
if [ ! -f "$DUMP_FILE" ]; then
  echo "1/4 Export de la base locale..."
  pg_dump -Fc retards_idf > "$DUMP_FILE"
  echo "    Dump créé : $DUMP_FILE ($(du -h "$DUMP_FILE" | cut -f1))"
else
  echo "1/4 Dump existant trouvé : $DUMP_FILE ($(du -h "$DUMP_FILE" | cut -f1))"
fi

# --- Étape 2 : Copie vers le VPS ---
echo "2/4 Copie du dump vers le VPS..."
scp "$DUMP_FILE" "$VPS_USER@$VPS_IP:/tmp/dump.pgdump"

# --- Étape 3 : Import dans le conteneur PostgreSQL ---
echo "3/4 Import dans le conteneur Docker PostgreSQL..."
ssh "$VPS_USER@$VPS_IP" bash -s <<'REMOTE'
  cd ~/rertracker
  # Nom du conteneur db
  DB_CONTAINER=$(docker compose ps -q db)
  if [ -z "$DB_CONTAINER" ]; then
    echo "ERREUR : le conteneur db n'est pas en cours d'exécution."
    exit 1
  fi
  # Copier le dump dans le conteneur
  docker cp /tmp/dump.pgdump "$DB_CONTAINER":/tmp/dump.pgdump
  # Restaurer (--clean supprime les objets existants avant de recréer)
  docker compose exec -T db pg_restore \
    --clean --if-exists --no-owner --no-privileges \
    -U "${POSTGRES_USER:-user}" -d "${POSTGRES_DB:-retards_idf}" \
    /tmp/dump.pgdump || true
  # Nettoyage
  docker exec "$DB_CONTAINER" rm -f /tmp/dump.pgdump
  rm -f /tmp/dump.pgdump
REMOTE

# --- Étape 4 : Vérification ---
echo "4/4 Vérification..."
ssh "$VPS_USER@$VPS_IP" bash -s <<'VERIFY'
  cd ~/rertracker
  echo "Nombre d'incidents :"
  docker compose exec -T db psql -U "${POSTGRES_USER:-user}" -d "${POSTGRES_DB:-retards_idf}" \
    -c "SELECT COUNT(*) FROM incidents;" 2>/dev/null || echo "  (table incidents non trouvée)"
  echo "Nombre de daily_metrics :"
  docker compose exec -T db psql -U "${POSTGRES_USER:-user}" -d "${POSTGRES_DB:-retards_idf}" \
    -c "SELECT COUNT(*) FROM daily_metrics;" 2>/dev/null || echo "  (table daily_metrics non trouvée)"
VERIFY

echo ""
echo "=== Migration terminée ==="
echo "Pensez à recalculer les bilans : ssh $VPS_USER@$VPS_IP 'cd $APP_DIR && docker compose exec backend python -m backend.recalcul'"
