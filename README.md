# WeatherWatch

A responsive operations dashboard for current conditions and multi-provider forecasts at configured Philippine sites. Its interface follows Apple Human Interface Guidelines principles: clear hierarchy, content-first layouts, familiar controls, comfortable touch targets, accessible contrast, reduced-motion support, and automatic light/dark appearance.

## Features

- Live dashboard with five-level severity color matrix
- Direct ECMWF IFS HRES forecasts at native 9 km resolution
- Explicit modeled-versus-observed labeling throughout the dashboard
- Animated interactive five-day forecast cards: select a day to correlate it with that site's hourly weather, or select the same day again to collapse the hourly panel
- Five-day coordinate-level forecasts updated from ECMWF's six-hourly model runs
- Interactive three-hour rain timeline with full-screen map, centered scrubber, large media-style SVG play/pause control, two hours of observed RainViewer radar, and the next-hour ECMWF precipitation forecast
- Five-day forecast for every monitored site
- Vivid Philippine sky-and-island welcome scene before selection, plus clickable site cards with distinct cinematic scenes for sunny, partly cloudy, overcast, drizzle, rain, showers, fog, and thunderstorms
- 11 preloaded locations from the supplied list
- Branded favicon and Apple touch icon
- Automatic refresh every five minutes, immediate cross-worker location synchronization, and visible application version
- Unlinked `/admin` portal
- One-time administrator registration (closes after the first account)
- Scrypt password hashing, CSRF protection, secure cookies, security headers, parameterized SQL
- Add, edit, and delete locations
- Admin-configurable weather severity matrix with immediate forecast recalculation
- Admin-only active visitor view with IP and ISP information
- Date/time-filtered visitor-event export to CSV
- Automatic visitor-data retention (30 days by default)
- Authenticated, fast-forward-only Git updater with live progress, automatic dependency installation, and automatic admin-page refresh
- One-click rollback to the exact version active before the last update
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

The initial values follow the supplied matrix, with 0.1 mm rain / 40 kph gust as the WeatherWatch floor. Administrators can recalibrate all rain and gust thresholds from `/admin`; values are validated as strictly increasing and forecast colors refresh immediately across Gunicorn workers and CDN/browser caches. Every site card identifies the rain and/or gust value currently driving its color.

## Weather source

WeatherWatch uses the ECMWF Integrated Forecasting System High Resolution Forecast (IFS HRES) at its native 9 km global resolution. Data is requested by exact site coordinates through Open-Meteo's ECMWF delivery API using the explicit `ecmwf_ifs` model selector; Open-Meteo is the transport/API layer, not an additional forecast vote. Results are cached for five minutes, and the last matching-location result remains available during short upstream interruptions. Values are numerical-model forecasts rather than on-site instrument observations.

## Rain timeline

After a site is selected, the dashboard centers an interactive OpenStreetMap on its exact coordinates, overlays RainViewer's available two-hour observed-radar history in 10-minute frames, and shows the next hour's ECMWF precipitation forecast, forming a clearly labeled three-hour rain timeline. The map opens at close facility-level zoom (level 14), supports pan and zoom, marks the selected facility, displays a rain-intensity legend, and inspects loaded radar-tile transparency to distinguish observed precipitation from a valid clear radar frame or unavailable coverage. Radar coverage can vary by location and provider availability. RainViewer attribution is displayed in the interface. Before production use, confirm that your deployment qualifies under RainViewer's current API terms; its public service is intended for personal, educational, and small-scale community use and has no availability SLA.

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

The updater runs in the background, reports each phase live in the admin portal, checks for a clean working tree, fetches `origin/main`, performs a **fast-forward-only** merge, installs pinned Python dependencies, and gracefully reloads Gunicorn. The admin page refreshes automatically when the operation finishes. Enable only after deployment is working:

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
