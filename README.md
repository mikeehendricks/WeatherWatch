# WeatherWatch

A responsive operations dashboard for current conditions and today's rain/wind forecast at configured Philippine sites. Weather comes from [Open-Meteo](https://open-meteo.com/) and requires no API key.

## Features

- Live dashboard with five-level severity color matrix
- Multi-provider data from Open-Meteo and MET Norway
- Safety-first consensus uses the higher rain/wind risk and averages temperatures
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

## Weather-source selection

WeatherWatch retrieves coordinate-level forecasts from both Open-Meteo and the MET Norway Locationforecast API. Because neither provider supplies independent ground-truth observations at every facility, the application does not make an unsupported claim that one is universally more accurate. It uses a safety-first consensus instead: the higher rainfall and wind-gust forecast controls operational severity, while available temperatures are averaged. If MET Norway is unavailable, Open-Meteo remains available automatically. Results are cached for five minutes to respect provider capacity and stale data is retained during short upstream interruptions. Each site card identifies the active source and method.

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

The updater checks for a clean working tree, fetches `origin/main`, performs a **fast-forward-only** merge, installs pinned Python dependencies, and gracefully reloads Gunicorn so the new version starts automatically. Enable only after deployment is working:

1. Ensure the `weatherwatch` service user can read the repository and authenticate to a private remote (a read-only deploy key is preferred).
2. Set `ENABLE_WEB_UPDATES=1` in `/etc/weatherwatch.env`.
3. Run `sudo systemctl restart weatherwatch`.
4. Use **Check for code update** in the admin portal. Dependencies are installed and the service is gracefully reloaded automatically.

After updating, the worker sends a same-user `SIGHUP` to its Gunicorn master for a graceful reload. No `sudo`, root permission, or service-control permission is granted to the application. Major operating-system or database migration changes should still be applied over SSH.

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
