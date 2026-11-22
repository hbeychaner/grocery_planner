#!/usr/bin/env bash
set -euo pipefail

# Lightweight GCP Compute Engine deployment script (no Terraform required).
# Defaults to us-central1-a e2-micro (eligible for GCP Always Free tier).
# For EU low-latency (~15ms from Prague), run:
#   ZONE=europe-central2-a REGION=europe-central2 ./scripts/deploy_gcp_vm.sh

_read_env_var() {
  local key="$1"
  if [ -f ".env" ]; then
    grep -E "^${key}=" .env 2>/dev/null | tail -n 1 | cut -d '=' -f2- | tr -d '"' | tr -d "'" | tr -d '\r' || true
  fi
}

PROJECT_ID="${PROJECT_ID:-${GCP_PROJECT_ID:-$(_read_env_var GCP_PROJECT_ID)}}"
if [ -z "$PROJECT_ID" ]; then
  PROJECT_ID="$(gcloud config get-value project 2>/dev/null || true)"
fi
PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-$(_read_env_var PUBLIC_DOMAIN)}"
DUCKDNS_DOMAIN="${DUCKDNS_DOMAIN:-$(_read_env_var DUCKDNS_DOMAIN)}"
DUCKDNS_TOKEN="${DUCKDNS_TOKEN:-$(_read_env_var DUCKDNS_TOKEN)}"
REGION="${REGION:-us-central1}"
ZONE="${ZONE:-us-central1-a}"
VM_NAME="${VM_NAME:-grocery-planner-vm}"
IP_NAME="${IP_NAME:-grocery-planner-ip}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-micro}"
APP_DIR="/opt/grocery_planner"

if [ -z "$PROJECT_ID" ]; then
  echo "ERROR: Set GCP_PROJECT_ID in .env, pass PROJECT_ID=<id>, or run 'gcloud config set project <id>'."
  exit 1
fi

echo "==> Project: $PROJECT_ID | Zone: $ZONE | Machine: $MACHINE_TYPE"

# 1. Build frontend locally so the VM doesn't need Node.js
echo "==> Building React frontend locally..."
(cd frontend && npm run build)

# 2. Reserve static external IP (idempotent)
if ! gcloud compute addresses describe "$IP_NAME" --region="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "==> Creating static external IP '$IP_NAME'..."
  gcloud compute addresses create "$IP_NAME" --region="$REGION" --project="$PROJECT_ID"
fi
VM_IP="$(gcloud compute addresses describe "$IP_NAME" --region="$REGION" --project="$PROJECT_ID" --format='get(address)')"
echo "==> Static VM IP: $VM_IP"

# 3. Ensure HTTP (80) and HTTPS (443) firewall rules exist
if ! gcloud compute firewall-rules describe allow-http-https-grocery --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "==> Creating firewall rule for TCP 80 & 443..."
  gcloud compute firewall-rules create allow-http-https-grocery \
    --project="$PROJECT_ID" \
    --allow=tcp:80,tcp:443 \
    --target-tags=http-server,https-server \
    --source-ranges=0.0.0.0/0
fi

# 4. Create Compute Engine VM if it doesn't exist
if ! gcloud compute instances describe "$VM_NAME" --zone="$ZONE" --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "==> Creating VM '$VM_NAME'..."
  gcloud compute instances create "$VM_NAME" \
    --project="$PROJECT_ID" \
    --zone="$ZONE" \
    --machine-type="$MACHINE_TYPE" \
    --address="$VM_IP" \
    --tags=http-server,https-server \
    --image-family=debian-12 \
    --image-project=debian-cloud \
    --boot-disk-size=20GB \
    --boot-disk-type=pd-standard
  echo "    Waiting 20s for SSH to become ready..."
  sleep 20
fi

# 5. Package project (excluding .venv, node_modules, .git, local *.pem)
TAR_PATH="/tmp/grocery_planner_deploy.tar.gz"
COPYFILE_DISABLE=1 tar --no-xattrs --no-mac-metadata -czf "$TAR_PATH" \
  --exclude=".git" \
  --exclude=".venv" \
  --exclude="frontend/node_modules" \
  --exclude="*.pem" \
  --exclude="__pycache__" \
  --exclude=".pytest_cache" \
  .

echo "==> Uploading app bundle to $VM_NAME..."
gcloud compute scp "$TAR_PATH" "$VM_NAME:/tmp/grocery_planner_deploy.tar.gz" --zone="$ZONE" --project="$PROJECT_ID"
if [ -f ".env" ]; then
  gcloud compute scp ".env" "$VM_NAME:/tmp/.env.upload" --zone="$ZONE" --project="$PROJECT_ID"
fi

# 6. Provision Python, Caddy, systemd services on the VM
if [ -n "${DUCKDNS_DOMAIN:-}" ] && [ -n "${DUCKDNS_TOKEN:-}" ]; then
  DUCKDNS_SUB="${DUCKDNS_DOMAIN%.duckdns.org}"
  echo "==> Updating DuckDNS record '${DUCKDNS_SUB}.duckdns.org' -> $VM_IP..."
  curl -sf "https://www.duckdns.org/update?domains=${DUCKDNS_SUB}&token=${DUCKDNS_TOKEN}&ip=${VM_IP}" >/dev/null
  DEFAULT_DOMAIN="${DUCKDNS_SUB}.duckdns.org"
else
  DEFAULT_DOMAIN="${PUBLIC_DOMAIN:-${VM_IP//./-}.sslip.io}"
fi
echo "==> Provisioning VM (domain: $DEFAULT_DOMAIN)..."
gcloud compute ssh "$VM_NAME" --zone="$ZONE" --project="$PROJECT_ID" --command="bash -s" <<REMOTE_EOF
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
sudo -E apt-get update -qq
sudo -E apt-get install -y -qq python3 python3-venv python3-pip debian-keyring debian-archive-keyring apt-transport-https curl

# Install Caddy if missing
if ! command -v caddy >/dev/null 2>&1; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo -E apt-get update -qq && sudo -E apt-get install -y -qq caddy
fi

# Add 2GB swap on e2-micro for safety
if [ ! -f /swapfile ]; then
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

sudo mkdir -p "$APP_DIR"
sudo chown -R "\$USER":"\$USER" "$APP_DIR"
tar -xzf /tmp/grocery_planner_deploy.tar.gz -C "$APP_DIR"
rm -f /tmp/grocery_planner_deploy.tar.gz

if [ -f /tmp/.env.upload ]; then
  mv /tmp/.env.upload "$APP_DIR/.env"
fi

# Force lightweight cloud settings in deployed .env
cd "$APP_DIR"
touch .env
sed -i '/^ENVIRONMENT=/d;/^REQUIRE_AUTH=/d;/^COMPARISON_LLM_PROVIDER=/d;/^EMBEDDING_PROVIDER=/d;/^OLLAMA_ENABLED=/d;/^GOOGLE_REDIRECT_URI=/d' .env
cat >> .env <<ENV_APPEND
ENVIRONMENT=production
REQUIRE_AUTH=true
COMPARISON_LLM_PROVIDER=gemini
EMBEDDING_PROVIDER=gemini
OLLAMA_ENABLED=false
ENV_APPEND

python3 -m venv .venv
./.venv/bin/pip install --upgrade pip -q
./.venv/bin/pip install -r requirements-deploy.txt -q

# Systemd service for FastAPI
sudo tee /etc/systemd/system/grocery-planner.service >/dev/null <<SERVICE_EOF
[Unit]
Description=Grocery Planner FastAPI
After=network.target

[Service]
User=\$USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SERVICE_EOF

# Configure Caddy reverse proxy -> 127.0.0.1:8000 (HTTP backend)
sudo tee /etc/caddy/Caddyfile >/dev/null <<CADDY_EOF
$DEFAULT_DOMAIN {
    reverse_proxy 127.0.0.1:8000
}
CADDY_EOF

sudo systemctl daemon-reload
sudo systemctl enable --now grocery-planner
sudo systemctl restart grocery-planner
sudo systemctl restart caddy
REMOTE_EOF

echo ""
echo "✅ Deployment complete!"
echo "   Static IP    : $VM_IP"
echo "   HTTPS URL    : https://$DEFAULT_DOMAIN"
echo ""
echo "👉 One-time Google OAuth setup (Google has no CLI/API to edit Web OAuth redirect URIs):"
echo "   Open: https://console.cloud.google.com/apis/credentials?project=$PROJECT_ID"
echo "   Add Authorized JavaScript origin : https://$DEFAULT_DOMAIN"
echo "   Add Authorized redirect URI      : https://$DEFAULT_DOMAIN/auth/google/callback"
