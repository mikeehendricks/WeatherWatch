# WeatherWatch

A responsive operations dashboard for current conditions and today's rain/wind forecast at configured Philippine sites. Weather comes from [Open-Meteo](https://open-meteo.com/) and requires no API key.

## Features

- Live dashboard with five-level severity color matrix
- Five-day forecast for every monitored site
- 11 preloaded locations from the supplied list
- Automatic refresh every five minutes and visible application version
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

## One-command Ubuntu installation

On Ubuntu 22.04, 24.04, or 26.04 LTS (including 26.04.1), clone the repository and run the included installer:

```bash
git clone https://github.com/mikeehendricks/WeatherWatch.git
cd WeatherWatch
sudo bash install.sh
```

For a domain, automatic HTTPS, and the optional admin web updater:

```bash
sudo bash install.sh \
  --domain weather.example.com \
  --email admin@example.com \
  --https \
  --enable-web-updates
```

Point the domain's DNS record to the server before using `--https`. The script installs all packages, creates a restricted service account, configures the Python environment, systemd and nginx, generates the application secret, starts the services, and runs a health check. It is safe to rerun for configuration repair or an update.

Visit `/admin` once to create the sole administrator. Registration is unavailable afterward. HTTPS is strongly recommended before using the admin portal.

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
