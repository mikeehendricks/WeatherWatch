import hmac
import json
import os
import secrets
import sqlite3
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("WEATHERWATCH_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "weatherwatch.db"
DATA_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "1") == "1",
    PERMANENT_SESSION_LIFETIME=1800,
    MAX_CONTENT_LENGTH=64 * 1024,
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

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


@app.get("/api/weather")
def weather():
    with db() as conn:
        locations = [dict(r) for r in conn.execute("SELECT * FROM locations ORDER BY name")]
    if not locations:
        return jsonify({"locations": [], "updated_at": datetime.now(timezone.utc).isoformat()})
    params = urllib.parse.urlencode({
        "latitude": ",".join(str(x["latitude"]) for x in locations),
        "longitude": ",".join(str(x["longitude"]) for x in locations),
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,wind_gusts_10m",
        "daily": "precipitation_sum,wind_gusts_10m_max,weather_code",
        "forecast_days": 1, "timezone": "Asia/Manila", "wind_speed_unit": "kmh"
    })
    try:
        req = urllib.request.Request("https://api.open-meteo.com/v1/forecast?" + params, headers={"User-Agent": "WeatherWatch/1.0"})
        with urllib.request.urlopen(req, timeout=12) as response:
            payload = json.load(response)
        forecasts = payload if isinstance(payload, list) else [payload]
        result = []
        for loc, forecast in zip(locations, forecasts):
            current = forecast.get("current", {})
            daily = forecast.get("daily", {})
            rain = float((daily.get("precipitation_sum") or [0])[0] or 0)
            gust = float((daily.get("wind_gusts_10m_max") or [0])[0] or 0)
            severity = classify(rain, gust)
            result.append({**loc, "current": current, "rain": rain, "gust": gust, "severity": severity})
        return jsonify({"locations": result, "updated_at": datetime.now(timezone.utc).isoformat()})
    except Exception as exc:
        app.logger.warning("Weather provider error: %s", exc)
        return jsonify({"error": "Weather data is temporarily unavailable."}), 503


def classify(rain, gust):
    if rain > 100 or gust > 130: return "extreme"
    if rain >= 50 or gust >= 100: return "heavy"
    if rain >= 30 or gust >= 75: return "moderate"
    if rain > 0 or gust >= 40: return "watch"
    return "normal"


@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_id"):
        return redirect(url_for("admin_dashboard"))
    if not admin_exists():
        return redirect(url_for("admin_register"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with db() as conn:
            user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear(); session["admin_id"] = user["id"]; session.permanent = True
            return redirect(url_for("admin_dashboard"))
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
        if len(username) < 3 or len(username) > 40:
            flash("Username must be 3–40 characters.", "error")
        elif len(password) < 12:
            flash("Password must contain at least 12 characters.", "error")
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
        before = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=BASE_DIR, check=True, capture_output=True, text=True, timeout=10).stdout.strip()
        subprocess.run(["git", "fetch", "--prune", "origin"], cwd=BASE_DIR, check=True, capture_output=True, text=True, timeout=60)
        subprocess.run(["git", "merge", "--ff-only", "@{u}"], cwd=BASE_DIR, check=True, capture_output=True, text=True, timeout=60)
        after = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=BASE_DIR, check=True, capture_output=True, text=True, timeout=10).stdout.strip()
        flash("Already up to date." if before == after else f"Updated {before} → {after}. Restart the service to apply changes.", "success")
    except (subprocess.SubprocessError, OSError) as exc:
        app.logger.error("Update failed: %s", exc)
        flash("Update failed. Check server logs and repository permissions.", "error")
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
