import json
from urllib.parse import parse_qs, urlsplit

from test_app import load


class FakeResponse:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, *_): return json.dumps(self.payload).encode()


def forecast_payload():
    dates = ['2026-09-09','2026-09-10','2026-09-11','2026-09-12','2026-09-13']
    hours = [f'2026-09-{9 + i // 24:02d}T{i % 24:02d}:00' for i in range(30)]
    return {
        'current': {'time': '2026-09-09T03:00', 'temperature_2m': 29, 'apparent_temperature': 32, 'weather_code': 2},
        'hourly': {
            'time': hours, 'temperature_2m': [28 + i % 4 for i in range(30)],
            'apparent_temperature': [31 + i % 4 for i in range(30)], 'weather_code': [2] * 30,
            'precipitation_probability': [40] * 30, 'precipitation': [0.2] * 30,
            'wind_speed_10m': [15] * 30, 'wind_gusts_10m': [25] * 30,
        },
        'daily': {
            'time': dates, 'weather_code': [2]*5,
            'temperature_2m_max': [31]*5, 'temperature_2m_min': [25]*5,
            'precipitation_sum': [4]*5, 'wind_gusts_10m_max': [35]*5,
        }
    }


def test_weather_uses_explicit_ecmwf_ifs_hres(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch); client = module.app.test_client()
    captured = {}
    def fake_urlopen(request, timeout):
        captured['url'] = request.full_url
        with module.db() as conn:
            count = conn.execute('SELECT COUNT(*) FROM locations').fetchone()[0]
        return FakeResponse([forecast_payload() for _ in range(count)])
    monkeypatch.setattr(module.urllib.request, 'urlopen', fake_urlopen)
    module.WEATHER_CACHE.update(payload=None, expires=0, location_key=None)
    response = client.get('/api/weather')
    assert response.status_code == 200
    query = parse_qs(urlsplit(captured['url']).query)
    assert query['models'] == ['ecmwf_ifs']
    data = response.get_json()
    assert data['method'] == 'ECMWF IFS HRES 9 km'
    assert all(item['source'] == 'ECMWF IFS HRES 9 km' for item in data['locations'])
    assert all(item['severity_reason'] for item in data['locations'])
    assert data['matrix_updated_at']
    assert 'no-store' in response.headers['Cache-Control']
    assert all(len(item['forecast']) == 5 for item in data['locations'])
    assert all(len(item['hourly_forecast']) == 27 for item in data['locations'])
    first_hour = data['locations'][0]['hourly_forecast'][0]
    assert first_hour['time'] == '2026-09-09T03:00'
    assert first_hour['precipitation_probability'] == 40
    assert first_hour['wind_gust'] == 25
    assert 'temperature_2m' in query['hourly'][0]
    assert 'precipitation_probability' in query['hourly'][0]
