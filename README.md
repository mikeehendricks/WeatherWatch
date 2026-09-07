# WeatherWatch

A responsive operations dashboard for current conditions and today's rain/wind forecast at configured Philippine sites. Weather comes from [Open-Meteo](https://open-meteo.com/) and requires no API key.

## Features

- Live dashboard with five-level severity color matrix
- 11 preloaded locations from the supplied list
- Automatic refresh every five minutes
- Unlinked `/admin` portal
- One-time administrator registration (closes after the first account)
- Scrypt password hashing, CSRF protection, secure cookies, security headers, parameterized SQL
- Add/delete locations
- Optional authenticated, fast-forward-only Git updater
- SQLite persistence outside the source tree
- Gunicorn + nginx + systemd production setup

## Severity logic

The highest category triggered by today's forecast precipitation or maximum wind gust is used:

| Level | Rule |
|---|---|
| Normal | Dry and gust below 40 kph |
| WeatherWatch | Rain 1–29 mm or gust 40–74 kph |
| Moderate | Rain 30–49 mm or gust 75–99 kph |
| Heavy / Strong | Rain 50–100 mm or gust 100–130 kph |
| Extreme | Rain >100 mm or gust >130 kph |

The image did not specify numeric thresholds for WeatherWatch, so 1 mm rain / 40 kph gust was selected as the watch floor.

## Ubuntu deployment

```bash
sudo apt update && sudo apt install -y python3-venv nginx git
sudo useradd --system --home /opt/weatherwatch --shell /usr/sbin/nologin weatherwatch
sudo git clone https://github.com/YOUR_ACCOUNT/WeatherWatch.git /opt/weatherwatch
sudo python3 -m venv /opt/weatherwatch/.venv
sudo /opt/weatherwatch/.venv/bin/pip install -r /opt/weatherwatch/requirements.txt
sudo install -d -o weatherwatch -g weatherwatch /var/lib/weatherwatch
sudo chown -R weatherwatch:weatherwatch /opt/weatherwatch
SECRET=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
sudo tee /etc/weatherwatch.env >/dev/null <<EOF
SECRET_KEY=$SECRET
COOKIE_SECURE=1
ENABLE_WEB_UPDATES=0
WEATHERWATCH_DATA_DIR=/var/lib/weatherwatch
EOF
sudo chmod 600 /etc/weatherwatch.env
sudo cp /opt/weatherwatch/deploy/weatherwatch.service /etc/systemd/system/
sudo cp /opt/weatherwatch/deploy/nginx.conf /etc/nginx/sites-available/weatherwatch
sudo ln -s /etc/nginx/sites-available/weatherwatch /etc/nginx/sites-enabled/weatherwatch
# Edit server_name in /etc/nginx/sites-available/weatherwatch, then:
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl daemon-reload && sudo systemctl enable --now weatherwatch
```

Add HTTPS with Certbot before using the admin portal. Visit `/admin` once to create the sole administrator. Registration is unavailable afterward.

## Web updater

The updater runs `git fetch` and a **fast-forward-only** merge. Enable only after deployment is working:

1. Ensure the `weatherwatch` service user can read the repository and authenticate to a private remote (a read-only deploy key is preferred).
2. Set `ENABLE_WEB_UPDATES=1` in `/etc/weatherwatch.env`.
3. Run `sudo systemctl restart weatherwatch`.
4. Use **Check for code update** in the admin portal.
5. After a successful update, run `sudo systemctl restart weatherwatch` to load new Python code. Dependency or database migration changes should be applied over SSH.

Do **not** place GitHub tokens in the repository or `.env` committed to Git.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
COOKIE_SECURE=0 flask --app app run --debug
```

## License

MIT © 2026 Mikee Hendricks
