import csv
import hmac
import io
import ipaddress
import json
import os
import secrets
import signal
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

from flask import Flask, Response, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("WEATHERWATCH_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "weatherwatch.db"
VERSION_FILE = BASE_DIR / "VERSION"
UPDATE_STATE_FILE = DATA_DIR / "update-state.json"
APP_VERSION = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.exists() else "dev"
DUMMY_PASSWORD_HASH = "scrypt:32768:8:1$0ZQlMO29KrbGTodV$15ff43ebbcff60f820f090a9f02af5a33682d757db92ad1c584581819183a210c3271ad9d8ea45df68deeed3b5fb1976a1a85b4bef17bd37b9f727588193330e"
DATA_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
secure_cookies = os.getenv("COOKIE_SECURE", "1") == "1"
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_NAME="__Host-weatherwatch" if secure_cookies else "weatherwatch",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=secure_cookies,
    SESSION_REFRESH_EACH_REQUEST=True,
    PERMANENT_SESSION_LIFETIME=1800,
    MAX_CONTENT_LENGTH=64 * 1024,
    TRUSTED_HOSTS=([x.strip() for x in os.getenv("TRUSTED_HOSTS", "").split(",") if x.strip()] or None),
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

WEATHER_CACHE = {"expires": 0.0, "payload": None, "location_key": None}
WEATHER_CACHE_LOCK = threading.Lock()
VISITOR_LOOKUPS = set()
VISITOR_LOOKUPS_LOCK = threading.Lock()
MANILA_TZ = ZoneInfo("Asia/Manila")
MET_USER_AGENT = os.getenv(
    "MET_NORWAY_USER_AGENT",
    f"WeatherWatch/{APP_VERSION} (+https://github.com/mikeehendricks/WeatherWatch)",
)
try:
    VISITOR_RETENTION_DAYS = max(1, min(int(os.getenv("VISITOR_RETENTION_DAYS", "30")), 365))
except ValueError:
    VISITOR_RETENTION_DAYS = 30

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
            CREATE TABLE IF NOT EXISTS visitors (
                ip TEXT PRIMARY KEY, isp TEXT NOT NULL DEFAULT 'Resolving…',
                first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                request_count INTEGER NOT NULL DEFAULT 1,
                user_agent TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS visitors_last_seen ON visitors(last_seen);
            CREATE TABLE IF NOT EXISTS visitor_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT NOT NULL,
                visited_at TEXT NOT NULL, user_agent TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS visitor_events_time ON visitor_events(visited_at);
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


def visitor_ip():
    candidate = request.headers.get("CF-Connecting-IP", "").strip() or (request.remote_addr or "unknown")
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return "unknown"


def resolve_isp(ip):
    try:
        address = ipaddress.ip_address(ip)
        if not address.is_global:
            isp = "Private/local network"
        else:
            url = f"https://ipwho.is/{urllib.parse.quote(ip)}?fields=success,connection"
            req = urllib.request.Request(url, headers={"User-Agent": f"WeatherWatch/{APP_VERSION}"})
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.load(response)
            connection = data.get("connection") or {}
            isp = (connection.get("isp") or connection.get("org") or "Unknown ISP")[:160]
        with db() as conn:
            conn.execute("UPDATE visitors SET isp=? WHERE ip=?", (isp, ip))
    except Exception as exc:
        app.logger.info("ISP lookup failed for %s: %s", ip, exc)
        with db() as conn:
            conn.execute("UPDATE visitors SET isp='Lookup unavailable' WHERE ip=?", (ip,))
    finally:
        with VISITOR_LOOKUPS_LOCK:
            VISITOR_LOOKUPS.discard(ip)


def record_visitor():
    # Count only human visits to the public dashboard, not assets, API polling,
    # health checks, or administration activity.
    if request.method != "GET" or request.path != "/":
        return
    ip = visitor_ip()
    now = datetime.now(timezone.utc).isoformat()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=VISITOR_RETENTION_DAYS)).isoformat()
    agent = request.headers.get("User-Agent", "")[:300]
    with db() as conn:
        conn.execute("DELETE FROM visitors WHERE last_seen < ?", (cutoff,))
        conn.execute("DELETE FROM visitor_events WHERE visited_at < ?", (cutoff,))
        conn.execute("INSERT INTO visitor_events(ip, visited_at, user_agent) VALUES(?,?,?)", (ip, now, agent))
        conn.execute("""
            INSERT INTO visitors(ip, first_seen, last_seen, request_count, user_agent)
            VALUES(?,?,?,?,?)
            ON CONFLICT(ip) DO UPDATE SET
                last_seen=excluded.last_seen,
                request_count=visitors.request_count+1,
                user_agent=excluded.user_agent
        """, (ip, now, now, 1, agent))
        visitor = conn.execute("SELECT isp FROM visitors WHERE ip=?", (ip,)).fetchone()
    if visitor and visitor["isp"] == "Resolving…":
        with VISITOR_LOOKUPS_LOCK:
            if ip not in VISITOR_LOOKUPS:
                VISITOR_LOOKUPS.add(ip)
                threading.Thread(target=resolve_isp, args=(ip,), daemon=True).start()


@app.before_request
def track_public_visitor():
    record_visitor()


@app.before_request
def verify_csrf():
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("Origin")
        if origin and urllib.parse.urlsplit(origin).netloc != request.host:
            return "Cross-origin request rejected.", 403
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
    response.headers["Content-Security-Policy"] = "default-src 'self'; base-uri 'self'; object-src 'none'; form-action 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
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


def update_command(command, timeout=60):
    return subprocess.run(
        command, cwd=BASE_DIR, check=True, capture_output=True,
        text=True, timeout=timeout, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def load_update_state():
    try:
        state = json.loads(UPDATE_STATE_FILE.read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def save_update_state(state):
    temporary = UPDATE_STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, UPDATE_STATE_FILE)


def version_at_commit(commit):
    try:
        return update_command(["git", "show", f"{commit}:VERSION"], 10).stdout.strip()[:40] or "unknown"
    except subprocess.SubprocessError:
        return "unknown"


def request_graceful_reload():
    parent_pid = os.getppid()
    cmdline = Path(f"/proc/{parent_pid}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
    if "gunicorn" not in cmdline:
        raise RuntimeError("automatic reload is available only under Gunicorn")
    os.kill(parent_pid, signal.SIGHUP)


@app.get("/")
def index():
    with db() as conn:
        locations = [dict(r) for r in conn.execute("SELECT * FROM locations ORDER BY name")]
    return render_template("index.html", locations=locations, retention_days=VISITOR_RETENTION_DAYS)


@app.post("/api/visitor-heartbeat")
def visitor_heartbeat():
    with db() as conn:
        conn.execute(
            "UPDATE visitors SET last_seen=? WHERE ip=?",
            (datetime.now(timezone.utc).isoformat(), visitor_ip()),
        )
    return "", 204


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


def locations_cache_key(locations):
    """Create a stable cache identity shared conceptually across all workers."""
    return tuple(
        (item["id"], item["name"], item["address"], item["latitude"], item["longitude"], item["plus_code"])
        for item in locations
    )


@app.get("/api/weather")
def weather():
    # Read the lightweight location list before consulting the forecast cache.
    # Gunicorn workers have independent memory, so an identity key prevents a
    # worker from serving an old location list after another worker edits it.
    with db() as conn:
        locations = [dict(r) for r in conn.execute("SELECT * FROM locations ORDER BY name")]
    location_key = locations_cache_key(locations)
    now = time.monotonic()
    with WEATHER_CACHE_LOCK:
        if (
            WEATHER_CACHE["payload"] is not None
            and WEATHER_CACHE["expires"] > now
            and WEATHER_CACHE["location_key"] == location_key
        ):
            return jsonify(WEATHER_CACHE["payload"])

    if not locations:
        payload = {"locations": [], "updated_at": datetime.now(timezone.utc).isoformat()}
        with WEATHER_CACHE_LOCK:
            WEATHER_CACHE.update(payload=payload, expires=now + 300, location_key=location_key)
        return jsonify(payload)

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
            WEATHER_CACHE.update(payload=payload, expires=time.monotonic() + 300, location_key=location_key)
        return jsonify(payload)
    except Exception as exc:
        app.logger.warning("Weather provider error: %s", exc)
        with WEATHER_CACHE_LOCK:
            stale = WEATHER_CACHE["payload"] if WEATHER_CACHE["location_key"] == location_key else None
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
        pair_count = conn.execute(
            "SELECT COUNT(*) FROM login_attempts WHERE ip = ? AND username = ? AND attempted_at >= ?",
            (ip[:64], username[:40], cutoff),
        ).fetchone()[0]
        ip_count = conn.execute(
            "SELECT COUNT(*) FROM login_attempts WHERE ip = ? AND attempted_at >= ?",
            (ip[:64], cutoff),
        ).fetchone()[0]
    # Stop both targeted guessing and username-rotation bypasses.
    return pair_count >= 5 or ip_count >= 20


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
    active_since = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    with db() as conn:
        locations = conn.execute("SELECT * FROM locations ORDER BY name").fetchall()
        visitors = conn.execute(
            "SELECT * FROM visitors WHERE last_seen >= ? ORDER BY last_seen DESC", (active_since,)
        ).fetchall()
        visitor_total = conn.execute("SELECT COUNT(*) FROM visitors").fetchone()[0]
    update_state = load_update_state()
    rollback_available = bool(
        update_state.get("previous_commit")
        and update_state.get("status") in {"updated", "failed", "rollback_failed"}
    )
    return render_template(
        "admin/dashboard.html", locations=locations, visitors=visitors,
        visitor_total=visitor_total, retention_days=VISITOR_RETENTION_DAYS,
        update_state=update_state, rollback_available=rollback_available,
    )


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
        with WEATHER_CACHE_LOCK:
            WEATHER_CACHE.update(payload=None, expires=0.0)
        flash("Location added.", "success")
    except (ValueError, KeyError):
        flash("Please provide valid location details and coordinates.", "error")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/locations/<int:location_id>/edit", methods=["GET", "POST"])
@admin_required
def location_edit(location_id):
    with db() as conn:
        location = conn.execute("SELECT * FROM locations WHERE id = ?", (location_id,)).fetchone()
    if location is None:
        return "Location not found.", 404
    if request.method == "POST":
        try:
            name = request.form["name"].strip()
            address = request.form["address"].strip()
            latitude = float(request.form["latitude"])
            longitude = float(request.form["longitude"])
            plus_code = request.form.get("plus_code", "").strip()
            if not name or len(name) > 120 or not address or len(address) > 300:
                raise ValueError
            if len(plus_code) > 150 or not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
                raise ValueError
            with db() as conn:
                conn.execute(
                    "UPDATE locations SET name=?, address=?, latitude=?, longitude=?, plus_code=? WHERE id=?",
                    (name, address, latitude, longitude, plus_code, location_id),
                )
            with WEATHER_CACHE_LOCK:
                WEATHER_CACHE.update(payload=None, expires=0.0)
            flash("Location updated.", "success")
            return redirect(url_for("admin_dashboard"))
        except (ValueError, KeyError):
            flash("Please provide valid site details and coordinates.", "error")
    return render_template("admin/edit_location.html", location=location)


@app.post("/admin/locations/<int:location_id>/delete")
@admin_required
def location_delete(location_id):
    with db() as conn:
        conn.execute("DELETE FROM locations WHERE id = ?", (location_id,))
    with WEATHER_CACHE_LOCK:
        WEATHER_CACHE.update(payload=None, expires=0.0)
    flash("Location deleted.", "success")
    return redirect(url_for("admin_dashboard"))


def parse_admin_datetime(value, default):
    if not value:
        return default
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MANILA_TZ)
    return parsed.astimezone(timezone.utc)


def csv_safe(value):
    text = str(value or "")
    # Prevent spreadsheet formula execution when opening exports in Excel/Sheets.
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


@app.get("/admin/visitors/export")
@admin_required
def visitor_export():
    now = datetime.now(timezone.utc)
    try:
        start = parse_admin_datetime(request.args.get("start", ""), now - timedelta(days=1))
        end = parse_admin_datetime(request.args.get("end", ""), now)
        if start >= end or end - start > timedelta(days=VISITOR_RETENTION_DAYS):
            raise ValueError
    except (ValueError, TypeError):
        flash(f"Select a valid range up to {VISITOR_RETENTION_DAYS} days.", "error")
        return redirect(url_for("admin_dashboard"))
    with db() as conn:
        rows = conn.execute("""
            SELECT e.ip, COALESCE(v.isp, 'Unknown ISP') AS isp, e.visited_at, e.user_agent
            FROM visitor_events e LEFT JOIN visitors v ON v.ip=e.ip
            WHERE e.visited_at BETWEEN ? AND ? ORDER BY e.visited_at DESC
        """, (start.isoformat(), end.isoformat())).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["IP address", "ISP", "Visited at (UTC)", "User agent"])
    for row in rows:
        writer.writerow([csv_safe(row[key]) for key in row.keys()])
    filename = f"weatherwatch-visitors-{now.strftime('%Y%m%d-%H%M%S')}.csv"
    return Response(
        "\ufeff" + output.getvalue(), mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


@app.post("/admin/update")
@admin_required
def system_update():
    if os.getenv("ENABLE_WEB_UPDATES", "0") != "1":
        flash("Web updates are disabled. Set ENABLE_WEB_UPDATES=1 to enable them.", "error")
        return redirect(url_for("admin_dashboard"))
    state = {}
    try:
        # Never overwrite local administrator changes or accept rewritten history.
        update_command(["git", "diff", "--quiet"])
        update_command(["git", "diff", "--cached", "--quiet"])
        before = update_command(["git", "rev-parse", "HEAD"], 10).stdout.strip()
        update_command(["git", "fetch", "--prune", "origin"])
        update_command(["git", "merge", "--ff-only", "origin/main"])
        after = update_command(["git", "rev-parse", "HEAD"], 10).stdout.strip()

        if before == after:
            flash(f"Already up to date (version {APP_VERSION}).", "success")
        else:
            state = {
                "status": "updated", "previous_commit": before,
                "previous_version": version_at_commit(before),
                "updated_commit": after, "updated_version": version_at_commit(after),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            # Save the known-good commit before dependency installation, ensuring
            # rollback remains available even when installation or reload fails.
            save_update_state(state)
            update_command([
                str(BASE_DIR / ".venv" / "bin" / "pip"), "install",
                "--requirement", str(BASE_DIR / "requirements.txt")
            ], 180)
            request_graceful_reload()
            flash(
                f"Updated {before[:7]} → {after[:7]}. WeatherWatch is reloading automatically; "
                "the previous version remains available for rollback.", "success"
            )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "unknown command error").strip().splitlines()[-1][:240]
        app.logger.error("Update command failed (%s): %s", exc.cmd, detail)
        if state:
            state.update(status="failed", error=detail, failed_at=datetime.now(timezone.utc).isoformat())
            save_update_state(state)
        flash(f"Update failed: {detail}. Use Roll back if an update was downloaded.", "error")
    except (subprocess.SubprocessError, OSError, RuntimeError) as exc:
        app.logger.error("Update failed: %s", exc)
        if state:
            state.update(status="failed", error=str(exc)[:240], failed_at=datetime.now(timezone.utc).isoformat())
            save_update_state(state)
        flash("Update failed. Use Roll back if an update was downloaded, or check the service log.", "error")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/rollback")
@admin_required
def system_rollback():
    if os.getenv("ENABLE_WEB_UPDATES", "0") != "1":
        flash("Web updates are disabled; rollback is unavailable.", "error")
        return redirect(url_for("admin_dashboard"))
    state = load_update_state()
    previous = str(state.get("previous_commit", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", previous):
        flash("No verified previous version is available for rollback.", "error")
        return redirect(url_for("admin_dashboard"))
    current = ""
    try:
        update_command(["git", "diff", "--quiet"])
        update_command(["git", "diff", "--cached", "--quiet"])
        current = update_command(["git", "rev-parse", "HEAD"], 10).stdout.strip()
        update_command(["git", "cat-file", "-e", f"{previous}^{{commit}}"], 10)
        # Only roll back to the exact ancestor recorded immediately before update.
        update_command(["git", "merge-base", "--is-ancestor", previous, current], 10)
        if current == previous:
            state.update(status="rolled_back", rolled_back_at=datetime.now(timezone.utc).isoformat())
            save_update_state(state)
            flash("The previous version is already active.", "success")
            return redirect(url_for("admin_dashboard"))

        update_command(["git", "reset", "--hard", previous], 30)
        try:
            update_command([
                str(BASE_DIR / ".venv" / "bin" / "pip"), "install",
                "--requirement", str(BASE_DIR / "requirements.txt")
            ], 180)
        except Exception:
            # Restore the newer source if old dependencies cannot be installed.
            update_command(["git", "reset", "--hard", current], 30)
            raise
        state.update(
            status="rolled_back", rolled_back_from=current,
            rolled_back_at=datetime.now(timezone.utc).isoformat(),
        )
        save_update_state(state)
        request_graceful_reload()
        flash(
            f"Rolled back to version {state.get('previous_version', 'unknown')} "
            f"({previous[:7]}). WeatherWatch is reloading.", "success"
        )
    except (subprocess.SubprocessError, OSError, RuntimeError) as exc:
        app.logger.error("Rollback failed: %s", exc)
        state.update(status="rollback_failed", error=str(exc)[:240], failed_at=datetime.now(timezone.utc).isoformat())
        save_update_state(state)
        flash("Rollback failed safely. The service log contains details; use SSH recovery if needed.", "error")
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
