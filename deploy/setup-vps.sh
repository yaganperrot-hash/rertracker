#!/usr/bin/env bash
# setup-vps.sh — Configuration initiale du VPS OVH pour rertracker
# À exécuter une seule fois en root sur un Ubuntu 24 fraîchement installé.
# Usage : ssh root@<IP> 'bash -s' < deploy/setup-vps.sh
set -euo pipefail

REPO_URL="https://github.com/<VOTRE-USER>/rertracker.git"
APP_USER="rertracker"
APP_DIR="/home/$APP_USER/rertracker"

echo "=== 1/7 Mise à jour système ==="
apt update && apt upgrade -y

echo "=== 2/7 Installation de Docker ==="
apt install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "=== 3/7 Création de l'utilisateur $APP_USER ==="
if ! id "$APP_USER" &>/dev/null; then
  adduser --disabled-password --gecos "" "$APP_USER"
  usermod -aG docker "$APP_USER"
  echo "Utilisateur $APP_USER créé et ajouté au groupe docker."
else
  echo "Utilisateur $APP_USER existe déjà."
  usermod -aG docker "$APP_USER"
fi

echo "=== 4/7 Firewall (ufw) ==="
apt install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp   # SSH
ufw allow 80/tcp   # HTTP
ufw --force enable
ufw status verbose

echo "=== 5/7 Clonage du repo ==="
if [ ! -d "$APP_DIR" ]; then
  su - "$APP_USER" -c "git clone $REPO_URL $APP_DIR"
else
  echo "Le dossier $APP_DIR existe déjà — git pull."
  su - "$APP_USER" -c "cd $APP_DIR && git pull"
fi

echo "=== 6/7 Configuration ==="
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo ""
  echo ">>> IMPORTANT : éditez $APP_DIR/.env avec vos vraies clés :"
  echo "    nano $APP_DIR/.env"
  echo ""
  echo "    Variables à remplir :"
  echo "    - PRIM_API_KEY"
  echo "    - POSTGRES_USER / POSTGRES_PASSWORD (choisir un vrai mot de passe)"
  echo "    - DATABASE_URL (mettre le même user/password)"
  echo "    - EMAIL_PASSWORD (App Password Gmail pour le récap quotidien)"
  echo ""
  echo ">>> Puis relancez l'étape 7 manuellement :"
  echo "    su - $APP_USER"
  echo "    cd $APP_DIR"
  echo "    docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build"
  exit 0
fi

echo "=== 7/7 Lancement de l'application ==="
su - "$APP_USER" -c "
  cd $APP_DIR
  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
"

echo ""
echo "=== Setup terminé ==="
echo "Vérification : curl http://localhost"
curl -s -o /dev/null -w "HTTP %{http_code}" http://localhost || echo " (pas encore prêt, attendre ~15s)"
echo ""
echo "Logs : su - $APP_USER -c 'cd $APP_DIR && docker compose logs -f backend'"
