import hmac
import json
import os
import secrets
import sqlite3
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo
import re

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("WEATHERWATCH_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "weatherwatch.db"
VERSION_FILE = BASE_DIR / "VERSION"
APP_VERSION = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.exists() else "dev"
DUMMY_PASSWORD_HASH = "scrypt:32768:8:1$0ZQlMO29KrbGTodV$15ff43ebbcff60f820f090a9f02af5a33682d757db92ad1c584581819183a210c3271ad9d8ea45df68deeed3b5fb1976a1a85b4bef17bd37b9f727588193330e"
DATA_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "1") == "1",
    PERMANENT_SESSION_LIFETIME=1800,
    MAX_CONTENT_LENGTH=64 * 1024,
    TRUSTED_HOSTS=([x.strip() for x in os.getenv("TRUSTED_HOSTS", "").split(",") if x.strip()] or None),
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

WEATHER_CACHE = {"expires": 0.0, "payload": None}
WEATHER_CACHE_LOCK = threading.Lock()
MANILA_TZ = ZoneInfo("Asia/Manila")
MET_USER_AGENT = os.getenv(
    "MET_NORWAY_USER_AGENT",
    "WeatherWatch/1.3 (+https://github.com/mikeehendricks/WeatherWatch)",
)

SEED_LOCATIONS = [
    ("Malabon Admin", "123 Gov. Pascual Ave, Malabon City", 14.669781379303119, 120.97125462121843, "MX9C+WF Malabon, Metro Manila"),
    ("Therma Mobile Inc (Navotas)", "Navotas Fish port complex, Baradero St. Navotas City", 14.636547074765481, 120.95513550525777, "JXP3+CXW, Navotas, Metro Manila"),
    ("Therma Power Visayas (TPVI)", "Naga Power Plant Complex Barangay Colon, Naga City, Cebu", 10.217832747228655, 123.76215488434681, "6Q95+8G6, City of Naga, Cebu"),
    ("Cebu Private Power Corp. (CPPC)", "Old Veco Compound, Brgy. Ermita, Cebu City", 10.289895996366731, 123.8975115670205, "7VQX+W2C, Cebu City, 6000 Cebu"),
    ("East Asia Utilities Corp. (EAUC)", "Brgy. IBO Mepz 1 Lapu-Lapu City", 10.289859672369271, 123.89793652306979, "8XMP+98V, M.L. Quezon National Highway, Lapu-Lapu City, Cebu"),
    ("Therma Marine Inc (Nasipit)", "Mobile 2, Sta Ana, Lawis, Nasipit, Agusan Del Norte", 8.978086549325166, 125.3316639246825, "X8HJ+5M6, Bay, Nasipit, Agusan Del Norte"),
    ("Therma Marine Inc (Maco)", "Mobile 1, Maco, Davao de Oro (Formerly Compostela Valley)", 8.977561795178149, 125.33081782631388, "8VX3+W8 Maco, Davao de Oro"),
    ("Therma Luzon Inc - Pagbilao", "ISLA GRANDE ST BGY IBABANG POLO PAGBILAO QUEZON", 13.893206200855342, 121.74521195171631, "VPVW+54R, Pagbilao, 4302 Quezon"),
    ("Therma Luzon Inc - UBP", "UnionBank Plaza, Meralco Ave. cor. Onyx & Sapphire Roads, Ortigas Center, Pasig City 1605", 14.587197464906863, 121.06342676707148, "H3P7+R9 Pasig, Metro Manila"),
    ("Therma Visayas Inc", "Brgy Bato, Toledo City, Cebu", 10.351677825030333, 123.60135675286276, "9J22+8H9, Bocalor, Bato, Toledo, Cebu"),
    ("Therma South Inc", "Binugao, Toril, Davao City", 6.964664022396035, 125.47946066463481, "XF7H+RQ7, Toril, Davao City, Davao del Sur"),
]


def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY CHECK (id = 1), username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                address TEXT NOT NULL, latitude REAL NOT NULL CHECK(latitude BETWEEN -90 AND 90),
                longitude REAL NOT NULL CHECK(longitude BETWEEN -180 AND 180),
                plus_code TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS login_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT NOT NULL,
                username TEXT NOT NULL, attempted_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS login_attempts_lookup
                ON login_attempts(ip, username, attempted_at);
        """)
        if conn.execute("SELECT COUNT(*) FROM locations").fetchone()[0] == 0:
            now = datetime.now(timezone.utc).isoformat()
            conn.executemany("INSERT INTO locations(name,address,latitude,longitude,plus_code,created_at) VALUES(?,?,?,?,?,?)", [(*x, now) for x in SEED_LOCATIONS])


init_db()


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token
app.jinja_env.globals["app_version"] = APP_VERSION


@app.before_request
def verify_csrf():
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf", "")
        if not token or not expected or not hmac.compare_digest(token, expected):
            return "Invalid or expired security token.", 400


@app.after_request
def secure_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    if request.path.startswith("/admin"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    if request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)
    return wrapped


def admin_exists():
    with db() as conn:
        return conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


@app.get("/")
def index():
    with db() as conn:
        locations = [dict(r) for r in conn.execute("SELECT * FROM locations ORDER BY name")]
    return render_template("index.html", locations=locations)


def met_symbol_to_code(symbol):
    symbol = (symbol or "").lower()
    if "thunder" in symbol: return 95
    if "heavyrain" in symbol: return 65
    if "rainshowers" in symbol: return 80
    if "rain" in symbol or "sleet" in symbol: return 61
    if "snow" in symbol: return 71
    if "fog" in symbol: return 45
    if "cloudy" in symbol: return 3
    if "partlycloudy" in symbol: return 2
    return 0


def fetch_met_forecast(location):
    query = urllib.parse.urlencode({"lat": location["latitude"], "lon": location["longitude"]})
    req = urllib.request.Request(
        "https://api.met.no/weatherapi/locationforecast/2.0/compact?" + query,
        headers={"User-Agent": MET_USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=12) as response:
        payload = json.load(response)
    series = payload.get("properties", {}).get("timeseries", [])
    if not series:
        raise ValueError("MET Norway returned no forecast")

    now_details = series[0].get("data", {}).get("instant", {}).get("details", {})
    days = {}
    today = datetime.now(MANILA_TZ).date()
    for item in series:
        stamp = datetime.fromisoformat(item["time"].replace("Z", "+00:00")).astimezone(MANILA_TZ)
        if stamp.date() < today or stamp.date() >= today + timedelta(days=5):
            continue
        data = item.get("data", {})
        details = data.get("instant", {}).get("details", {})
        next_hour = data.get("next_1_hours", {})
        summary = next_hour.get("summary", {})
        day = days.setdefault(stamp.date().isoformat(), {"temps": [], "rain": 0.0, "gust": 0.0, "codes": []})
        if details.get("air_temperature") is not None:
            day["temps"].append(float(details["air_temperature"]))
        day["gust"] = max(day["gust"], float(details.get("wind_speed_of_gust", details.get("wind_speed", 0))) * 3.6)
        day["rain"] += float(next_hour.get("details", {}).get("precipitation_amount", 0) or 0)
        if summary.get("symbol_code"):
            day["codes"].append(met_symbol_to_code(summary["symbol_code"]))

    forecast = []
    for date in sorted(days)[:5]:
        day = days[date]
        temps = day["temps"] or [0]
        code = max(day["codes"] or [0])
        forecast.append({
            "date": date, "weather_code": code,
            "temperature_max": max(temps), "temperature_min": min(temps),
            "rain": round(day["rain"], 2), "gust": round(day["gust"], 1),
        })
    return {
        "current": {
            "temperature_2m": now_details.get("air_temperature"),
            "apparent_temperature": now_details.get("air_temperature"),
            "relative_humidity_2m": now_details.get("relative_humidity"),
            "wind_speed_10m": float(now_details.get("wind_speed", 0)) * 3.6,
            "wind_gusts_10m": float(now_details.get("wind_speed_of_gust", now_details.get("wind_speed", 0))) * 3.6,
        },
        "forecast": forecast,
    }


def mean_available(*values):
    valid = [float(value) for value in values if value is not None]
    return sum(valid) / len(valid) if valid else None


@app.get("/api/weather")
def weather():
    now = time.monotonic()
    with WEATHER_CACHE_LOCK:
        if WEATHER_CACHE["payload"] is not None and WEATHER_CACHE["expires"] > now:
            return jsonify(WEATHER_CACHE["payload"])

    with db() as conn:
        locations = [dict(r) for r in conn.execute("SELECT * FROM locations ORDER BY name")]
    if not locations:
        return jsonify({"locations": [], "updated_at": datetime.now(timezone.utc).isoformat()})

    params = urllib.parse.urlencode({
        "latitude": ",".join(str(x["latitude"]) for x in locations),
        "longitude": ",".join(str(x["longitude"]) for x in locations),
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,wind_gusts_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,wind_gusts_10m_max",
        "forecast_days": 5, "timezone": "Asia/Manila", "wind_speed_unit": "kmh"
    })
    try:
        open_req = urllib.request.Request(
            "https://api.open-meteo.com/v1/forecast?" + params,
            headers={"User-Agent": f"WeatherWatch/{APP_VERSION}"},
        )
        with urllib.request.urlopen(open_req, timeout=12) as response:
            open_payload = json.load(response)
        open_forecasts = open_payload if isinstance(open_payload, list) else [open_payload]

        met_forecasts = {}
        # MET Norway requires one coordinate request per site. Run them concurrently,
        # cache the consensus for five minutes, and tolerate individual failures.
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(fetch_met_forecast, loc): loc["id"] for loc in locations}
            for future in as_completed(futures):
                try:
                    met_forecasts[futures[future]] = future.result()
                except Exception as exc:
                    app.logger.warning("MET Norway error for location %s: %s", futures[future], exc)

        result = []
        for loc, open_forecast in zip(locations, open_forecasts):
            met = met_forecasts.get(loc["id"])
            current = dict(open_forecast.get("current", {}))
            if met:
                met_current = met["current"]
                current["temperature_2m"] = mean_available(current.get("temperature_2m"), met_current.get("temperature_2m"))
                current["apparent_temperature"] = mean_available(current.get("apparent_temperature"), met_current.get("apparent_temperature"))
                current["relative_humidity_2m"] = mean_available(current.get("relative_humidity_2m"), met_current.get("relative_humidity_2m"))
                current["wind_speed_10m"] = max(float(current.get("wind_speed_10m", 0) or 0), float(met_current.get("wind_speed_10m", 0) or 0))
                current["wind_gusts_10m"] = max(float(current.get("wind_gusts_10m", 0) or 0), float(met_current.get("wind_gusts_10m", 0) or 0))

            daily = open_forecast.get("daily", {})
            open_days = []
            for i, date in enumerate(daily.get("time", [])[:5]):
                open_days.append({
                    "date": date,
                    "weather_code": (daily.get("weather_code") or [0] * 5)[i],
                    "temperature_max": (daily.get("temperature_2m_max") or [None] * 5)[i],
                    "temperature_min": (daily.get("temperature_2m_min") or [None] * 5)[i],
                    "rain": float((daily.get("precipitation_sum") or [0] * 5)[i] or 0),
                    "gust": float((daily.get("wind_gusts_10m_max") or [0] * 5)[i] or 0),
                })
            met_by_date = {day["date"]: day for day in (met or {}).get("forecast", [])}
            days = []
            for open_day in open_days:
                met_day = met_by_date.get(open_day["date"])
                if met_day:
                    # Safety-first consensus: use the higher hazardous value and
                    # mean temperatures. This avoids understating rain or wind risk.
                    open_day["rain"] = max(open_day["rain"], met_day["rain"])
                    open_day["gust"] = max(open_day["gust"], met_day["gust"])
                    open_day["temperature_max"] = mean_available(open_day["temperature_max"], met_day["temperature_max"])
                    open_day["temperature_min"] = mean_available(open_day["temperature_min"], met_day["temperature_min"])
                open_day["severity"] = classify(open_day["rain"], open_day["gust"])
                days.append(open_day)

            first = days[0] if days else {"rain": 0, "gust": 0, "severity": "normal"}
            result.append({
                **loc, "current": current, "rain": first["rain"], "gust": first["gust"],
                "severity": first["severity"], "forecast": days,
                "source": "Open-Meteo + MET Norway" if met else "Open-Meteo",
                "selection": "Safety-first consensus" if met else "Provider fallback",
            })
        payload = {"locations": result, "updated_at": datetime.now(timezone.utc).isoformat(), "method": "Safety-first multi-provider consensus"}
        with WEATHER_CACHE_LOCK:
            WEATHER_CACHE.update(payload=payload, expires=time.monotonic() + 300)
        return jsonify(payload)
    except Exception as exc:
        app.logger.warning("Weather provider error: %s", exc)
        with WEATHER_CACHE_LOCK:
            stale = WEATHER_CACHE["payload"]
        if stale is not None:
            return jsonify({**stale, "stale": True})
        return jsonify({"error": "Weather data is temporarily unavailable."}), 503


def classify(rain, gust):
    if rain > 100 or gust > 130: return "extreme"
    if rain >= 50 or gust >= 100: return "heavy"
    if rain >= 30 or gust >= 75: return "moderate"
    if rain > 0 or gust >= 40: return "watch"
    return "normal"


def login_is_limited(ip, username):
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    with db() as conn:
        conn.execute("DELETE FROM login_attempts WHERE attempted_at < ?", (cutoff,))
        count = conn.execute(
            "SELECT COUNT(*) FROM login_attempts WHERE ip = ? AND username = ? AND attempted_at >= ?",
            (ip[:64], username[:40], cutoff),
        ).fetchone()[0]
    return count >= 5


def record_login_failure(ip, username):
    with db() as conn:
        conn.execute(
            "INSERT INTO login_attempts(ip, username, attempted_at) VALUES(?,?,?)",
            (ip[:64], username[:40], datetime.now(timezone.utc).isoformat()),
        )


def clear_login_failures(ip, username):
    with db() as conn:
        conn.execute("DELETE FROM login_attempts WHERE ip = ? AND username = ?", (ip[:64], username[:40]))


@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_id"):
        return redirect(url_for("admin_dashboard"))
    if not admin_exists():
        return redirect(url_for("admin_register"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()[:40]
        password = request.form.get("password", "")[:256]
        ip = request.remote_addr or "unknown"
        if login_is_limited(ip, username):
            flash("Too many failed attempts. Try again in 15 minutes.", "error")
            return render_template("admin/login.html"), 429
        with db() as conn:
            user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        password_ok = check_password_hash(user["password_hash"] if user else DUMMY_PASSWORD_HASH, password)
        if user and password_ok:
            clear_login_failures(ip, username)
            session.clear(); session["admin_id"] = user["id"]; session.permanent = True
            return redirect(url_for("admin_dashboard"))
        record_login_failure(ip, username)
        flash("Invalid username or password.", "error")
    return render_template("admin/login.html")


@app.route("/admin/register", methods=["GET", "POST"])
def admin_register():
    if admin_exists():
        return redirect(url_for("admin_login"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirmation = request.form.get("confirmation", "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", username):
            flash("Username must be 3–40 letters, numbers, dots, dashes, or underscores.", "error")
        elif len(password) < 12 or len(password) > 256:
            flash("Password must contain 12–256 characters.", "error")
        elif password != confirmation:
            flash("Passwords do not match.", "error")
        else:
            try:
                with db() as conn:
                    conn.execute("INSERT INTO users(id,username,password_hash,created_at) VALUES(1,?,?,?)", (username, generate_password_hash(password, method="scrypt"), datetime.now(timezone.utc).isoformat()))
                flash("Administrator created. Please sign in.", "success")
                return redirect(url_for("admin_login"))
            except sqlite3.IntegrityError:
                return redirect(url_for("admin_login"))
    return render_template("admin/register.html")


@app.get("/admin/dashboard")
@admin_required
def admin_dashboard():
    with db() as conn:
        locations = conn.execute("SELECT * FROM locations ORDER BY name").fetchall()
    return render_template("admin/dashboard.html", locations=locations)


@app.post("/admin/locations")
@admin_required
def location_add():
    try:
        name = request.form["name"].strip(); address = request.form["address"].strip()
        lat = float(request.form["latitude"]); lon = float(request.form["longitude"])
        plus = request.form.get("plus_code", "").strip()
        if not name or not address or not (-90 <= lat <= 90) or not (-180 <= lon <= 180): raise ValueError
        with db() as conn:
            conn.execute("INSERT INTO locations(name,address,latitude,longitude,plus_code,created_at) VALUES(?,?,?,?,?,?)", (name,address,lat,lon,plus,datetime.now(timezone.utc).isoformat()))
        flash("Location added.", "success")
    except (ValueError, KeyError):
        flash("Please provide valid location details and coordinates.", "error")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/locations/<int:location_id>/delete")
@admin_required
def location_delete(location_id):
    with db() as conn:
        conn.execute("DELETE FROM locations WHERE id = ?", (location_id,))
    flash("Location deleted.", "success")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/update")
@admin_required
def system_update():
    if os.getenv("ENABLE_WEB_UPDATES", "0") != "1":
        flash("Web updates are disabled. Set ENABLE_WEB_UPDATES=1 to enable them.", "error")
        return redirect(url_for("admin_dashboard"))
    try:
        def run(command, timeout=60):
            return subprocess.run(
                command, cwd=BASE_DIR, check=True, capture_output=True,
                text=True, timeout=timeout, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )

        # Refuse to overwrite local administrator changes or accept a history rewrite.
        run(["git", "diff", "--quiet"])
        run(["git", "diff", "--cached", "--quiet"])
        before = run(["git", "rev-parse", "--short", "HEAD"], 10).stdout.strip()
        run(["git", "fetch", "--prune", "origin"])
        run(["git", "merge", "--ff-only", "origin/main"])
        after = run(["git", "rev-parse", "--short", "HEAD"], 10).stdout.strip()

        if before == after:
            flash(f"Already up to date (version {APP_VERSION}).", "success")
        else:
            # Install pinned dependencies before gracefully reloading Gunicorn. ExecReload
            # lets this request finish while replacement workers start with the new code.
            run([str(BASE_DIR / ".venv" / "bin" / "pip"), "install", "--requirement", str(BASE_DIR / "requirements.txt")], 180)
            run(["sudo", "-n", "/bin/systemctl", "reload", "weatherwatch.service"], 15)
            flash(f"Updated {before} → {after}. WeatherWatch is restarting automatically; refresh in a few seconds.", "success")
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "unknown command error").strip().splitlines()[-1][:240]
        app.logger.error("Update command failed (%s): %s", exc.cmd, detail)
        flash(f"Update failed: {detail}", "error")
    except (subprocess.SubprocessError, OSError) as exc:
        app.logger.error("Update failed: %s", exc)
        flash("Update failed. Check the WeatherWatch service log for details.", "error")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/logout")
@admin_required
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=False)
