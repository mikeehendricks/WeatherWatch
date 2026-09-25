import json
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import parse_qs, urlsplit

from test_app import load
from test_weather_model import FakeResponse, forecast_payload


def test_hourly_day_is_loaded_on_demand_and_cached(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch)
    client = module.app.test_client()
    requested = datetime.now(ZoneInfo('Asia/Manila')).date().isoformat()
    calls = []
    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        return FakeResponse(forecast_payload())
    monkeypatch.setattr(module.urllib.request, 'urlopen', fake_urlopen)
    response = client.get(f'/api/hourly/1?date={requested}')
    assert response.status_code == 200
    assert 1 <= len(response.get_json()['hours']) <= 24
    query = parse_qs(urlsplit(calls[0]).query)
    assert urlsplit(calls[0]).netloc == 'api.met.no'
    assert 'lat' in query and 'lon' in query
    client.get(f'/api/hourly/1?date={requested}')
    assert len(calls) == 1


def test_hourly_day_rejects_invalid_date_and_location(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch)
    client = module.app.test_client()
    assert client.get('/api/hourly/1?date=bad').status_code == 400
    requested = datetime.now(ZoneInfo('Asia/Manila')).date().isoformat()
    assert client.get(f'/api/hourly/99999?date={requested}').status_code == 404


def test_installer_configures_static_cache_and_compression():
    installer = open('install.sh', encoding='utf-8').read()
    assert 'location /static/' in installer
    assert 'expires 7d' in installer
    assert 'gzip on' in installer


def test_weather_scenes_use_webp_without_eager_preload():
    css = open('static/style.css', encoding='utf-8').read()
    javascript = open('static/app.js', encoding='utf-8').read()
    assert '.webp")' in css
    assert '.jpg")' not in css
    assert 'new Image()' not in javascript
