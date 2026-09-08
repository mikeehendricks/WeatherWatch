#!/usr/bin/env bash
# WeatherWatch one-command installer for Ubuntu 22.04/24.04/26.04 LTS.
# Usage: sudo bash install.sh [--domain weather.example.com] [--email you@example.com]
#        [--repo https://github.com/ACCOUNT/WeatherWatch.git] [--enable-web-updates]
set -Eeuo pipefail

APP_DIR="/opt/weatherwatch"
DATA_DIR="/var/lib/weatherwatch"
ENV_FILE="/etc/weatherwatch.env"
SERVICE="weatherwatch"
REPO_URL="https://github.com/mikeehendricks/WeatherWatch.git"
DOMAIN="_"
EMAIL=""
ENABLE_UPDATES="0"
INSTALL_HTTPS="0"

log(){ printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die(){ printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
trap 'die "Installation stopped at line $LINENO. Review the message above."' ERR

while (( $# )); do
  case "$1" in
    --domain) [[ $# -ge 2 ]] || die "--domain requires a value"; DOMAIN="$2"; shift 2 ;;
    --email) [[ $# -ge 2 ]] || die "--email requires a value"; EMAIL="$2"; shift 2 ;;
    --repo) [[ $# -ge 2 ]] || die "--repo requires a value"; REPO_URL="$2"; shift 2 ;;
    --enable-web-updates) ENABLE_UPDATES="1"; shift ;;
    --https) INSTALL_HTTPS="1"; shift ;;
    -h|--help)
      sed -n '2,4p' "$0"; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ ${EUID:-$(id -u)} -eq 0 ]] || die "Run this installer as root: sudo bash install.sh"
[[ -r /etc/os-release ]] || die "This installer requires Ubuntu."
. /etc/os-release
[[ "${ID:-}" == "ubuntu" ]] || die "Unsupported OS: ${PRETTY_NAME:-unknown}. Ubuntu is required."
case "${VERSION_CODENAME:-}" in
  jammy|noble|resolute) ;;
  plucky) die "Ubuntu 25.04 (Plucky) reached end of life and its archive packages are no longer served normally. Reinstall/upgrade this server to Ubuntu 24.04 or 26.04 LTS, then run this installer again." ;;
  *) die "Unsupported Ubuntu release: ${PRETTY_NAME:-unknown}. Use Ubuntu 22.04, 24.04, or 26.04 LTS." ;;
esac
if [[ "$INSTALL_HTTPS" == "1" ]]; then
  [[ "$DOMAIN" != "_" ]] || die "--https requires --domain."
  [[ -n "$EMAIL" ]] || die "--https requires --email."
fi

export DEBIAN_FRONTEND=noninteractive
log "Installing operating-system packages"
apt-get update
apt-get install -y python3 python3-venv python3-pip git nginx ca-certificates curl
if [[ "$INSTALL_HTTPS" == "1" ]]; then apt-get install -y certbot python3-certbot-nginx; fi

log "Creating the service account and directories"
if ! id weatherwatch >/dev/null 2>&1; then
  useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin weatherwatch
fi
install -d -o weatherwatch -g weatherwatch -m 0750 "$DATA_DIR"

log "Installing WeatherWatch in $APP_DIR"
# If this script is being run from a checked-out WeatherWatch tree, install that
# exact tree. Otherwise clone the configured repository.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$SCRIPT_DIR" == "$APP_DIR" ]]; then
  # Re-running the installer from the installed application: update in place.
  if [[ -d "$APP_DIR/.git" ]]; then
    git -C "$APP_DIR" fetch --prune origin
    git -C "$APP_DIR" merge --ff-only '@{u}'
  fi
elif [[ -f "$SCRIPT_DIR/app.py" && -f "$SCRIPT_DIR/requirements.txt" ]]; then
  install -d -m 0755 "$APP_DIR"
  tar --exclude='.git' --exclude='.venv' --exclude='data' --exclude='preview-data' \
      -C "$SCRIPT_DIR" -cf - . | tar -C "$APP_DIR" -xf -
  if [[ -d "$SCRIPT_DIR/.git" ]]; then
    rm -rf "$APP_DIR/.git"
    cp -a "$SCRIPT_DIR/.git" "$APP_DIR/.git"
  fi
elif [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" fetch --prune origin
  git -C "$APP_DIR" merge --ff-only '@{u}'
else
  rm -rf "$APP_DIR"
  git clone --branch main --single-branch "$REPO_URL" "$APP_DIR"
fi

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install --requirement "$APP_DIR/requirements.txt"

# The service needs source-tree write access only when the optional web updater
# is enabled. Repository credentials are never written by this installer.
if [[ "$ENABLE_UPDATES" == "1" ]]; then
  chown -R weatherwatch:weatherwatch "$APP_DIR"
else
  chown -R root:root "$APP_DIR"
  chmod -R a+rX "$APP_DIR"
fi

log "Writing secure application configuration"
if [[ -f "$ENV_FILE" ]]; then
  SECRET_KEY="$(sed -n 's/^SECRET_KEY=//p' "$ENV_FILE" | head -n1)"
fi
SECRET_KEY="${SECRET_KEY:-$(python3 -c 'import secrets; print(secrets.token_hex(32))')}"
if [[ "$DOMAIN" == "_" ]]; then
  TRUSTED_HOSTS="localhost,127.0.0.1,$(hostname -I | tr ' ' ',' | sed 's/,$//')"
else
  TRUSTED_HOSTS="$DOMAIN,localhost,127.0.0.1"
fi
umask 077
cat >"$ENV_FILE" <<EOF
SECRET_KEY=$SECRET_KEY
COOKIE_SECURE=$([[ "$INSTALL_HTTPS" == "1" ]] && echo 1 || echo 0)
ENABLE_WEB_UPDATES=$ENABLE_UPDATES
WEATHERWATCH_DATA_DIR=$DATA_DIR
TRUSTED_HOSTS=$TRUSTED_HOSTS
MET_NORWAY_USER_AGENT=WeatherWatch/2.0 (+https://github.com/mikeehendricks/WeatherWatch)
VISITOR_RETENTION_DAYS=30
EOF
chown root:weatherwatch "$ENV_FILE"
chmod 0640 "$ENV_FILE"

log "Configuring systemd"
cat >"/etc/systemd/system/$SERVICE.service" <<EOF
[Unit]
Description=WeatherWatch web application
After=network-online.target
Wants=network-online.target

[Service]
User=weatherwatch
Group=weatherwatch
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/.venv/bin/gunicorn --workers 2 --threads 4 --bind 127.0.0.1:8000 --access-logfile - --error-logfile - app:app
ExecReload=/bin/kill -HUP \$MAINPID
Restart=on-failure
RestartSec=5
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$DATA_DIR$([[ "$ENABLE_UPDATES" == "1" ]] && printf ' %s' "$APP_DIR")
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
# Remove the legacy reload rule, if present. Reloads now use a same-user
# Gunicorn signal and remain compatible with NoNewPrivileges=true.
rm -f /etc/sudoers.d/weatherwatch-reload
systemctl daemon-reload
systemctl enable --now "$SERVICE"
systemctl restart "$SERVICE"

log "Configuring nginx"
cat >"/etc/nginx/sites-available/$SERVICE" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;
    server_tokens off;
    client_max_body_size 64k;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 10s;
        proxy_read_timeout 30s;
    }
}
EOF
ln -sfn "/etc/nginx/sites-available/$SERVICE" "/etc/nginx/sites-enabled/$SERVICE"
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx
systemctl reload nginx

if [[ "$INSTALL_HTTPS" == "1" ]]; then
  log "Requesting a Let's Encrypt certificate"
  certbot --nginx --non-interactive --agree-tos --redirect --email "$EMAIL" -d "$DOMAIN"
  # Secure cookies can now be required.
  sed -i 's/^COOKIE_SECURE=.*/COOKIE_SECURE=1/' "$ENV_FILE"
  systemctl restart "$SERVICE"
fi

log "Running health check"
for _ in {1..15}; do
  if curl --fail --silent http://127.0.0.1:8000/health >/dev/null; then break; fi
  sleep 1
done
curl --fail --silent http://127.0.0.1:8000/health >/dev/null || {
  journalctl -u "$SERVICE" --no-pager -n 30 >&2
  die "WeatherWatch did not pass its health check."
}

URL="http://$(hostname -I | awk '{print $1}')"
[[ "$DOMAIN" != "_" ]] && URL="http://$DOMAIN"
[[ "$INSTALL_HTTPS" == "1" ]] && URL="https://$DOMAIN"
printf '\n\033[1;32mWeatherWatch installation complete.\033[0m\n'
printf 'Open: %s\n' "$URL"
printf 'One-time administrator setup: %s/admin\n' "$URL"
printf 'Service logs: sudo journalctl -u %s -f\n' "$SERVICE"
if [[ "$ENABLE_UPDATES" == "1" ]]; then
  printf 'Web updater: enabled. A public repository or a read-only deploy key is required.\n'
else
  printf 'Web updater: disabled (recommended). Re-run with --enable-web-updates to enable it.\n'
fi
