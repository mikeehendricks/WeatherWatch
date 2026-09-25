import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

from test_app import load


class FakeResponse:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, *_): return json.dumps(self.payload).encode()


def forecast_payload():
    start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    timeseries = []
    for i in range(120):
        timeseries.append({
            'time': (start + timedelta(hours=i)).isoformat().replace('+00:00', 'Z'),
            'data': {
                'instant': {'details': {
                    'air_temperature': 28 + i % 4, 'relative_humidity': 78,
                    'wind_speed': 4.2, 'wind_speed_of_gust': 7.0,
                }},
                'next_1_hours': {
                    'summary': {'symbol_code': 'partlycloudy_day'},
                    'details': {'precipitation_amount': 0.2, 'probability_of_precipitation': 40},
                },
            },
        })
    return {'properties': {'timeseries': timeseries}}


def test_weather_uses_met_norway_locationforecast(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch); client = module.app.test_client()
    captured = []
    def fake_urlopen(request, timeout):
        captured.append(request)
        return FakeResponse(forecast_payload())
    monkeypatch.setattr(module.urllib.request, 'urlopen', fake_urlopen)
    module.WEATHER_CACHE.update(payload=None, expires=0, location_key=None)
    module.METNO_CACHE.clear()
    response = client.get('/api/weather')
    assert response.status_code == 200
    assert captured
    assert all(urlsplit(item.full_url).netloc == 'api.met.no' for item in captured)
    query = parse_qs(urlsplit(captured[0].full_url).query)
    assert 'lat' in query and 'lon' in query
    assert captured[0].headers['User-agent'].startswith('WeatherWatch/')
    data = response.get_json()
    assert data['method'] == 'MET Norway Locationforecast 2.0'
    assert all(item['source'] == 'MET Norway Locationforecast' for item in data['locations'])
    assert all(item['severity_reason'] for item in data['locations'])
    assert data['matrix_updated_at']
    assert 'no-store' in response.headers['Cache-Control']
    assert all(len(item['forecast']) == 5 for item in data['locations'])
    assert all(len(item['hourly_forecast']) == 24 for item in data['locations'])
    first_hour = data['locations'][0]['hourly_forecast'][0]
    assert first_hour['precipitation_probability'] == 40
    assert first_hour['wind_gust'] == 25.2
