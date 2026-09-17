import json

from test_app import load


class FakeResponse:
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, *_):
        return json.dumps({
            'host': 'https://tilecache.rainviewer.com',
            'radar': {'past': [
                {'time': 1700000000 + i * 600, 'path': f'/v2/radar/frame{i}'} for i in range(12)
            ]}
        }).encode()


def test_radar_timeline_is_limited_to_configured_location(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch); client = module.app.test_client()
    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *args, **kwargs: FakeResponse())
    module.RADAR_CACHE.update(expires=0, host='', frames=[])
    response = client.get('/api/radar?location_id=1')
    assert response.status_code == 200
    data = response.get_json()
    assert len(data['frames']) == 12
    assert data['history_minutes'] == 120
    assert data['attribution'] == 'Radar data by RainViewer'
    assert all(frame['url'].startswith('https://tilecache.rainviewer.com/v2/radar/') for frame in data['frames'])
    assert client.get('/api/radar?location_id=999999').status_code == 404
    assert client.get('/api/radar?location_id=not-a-number').status_code == 400


def test_unexpected_radar_host_is_rejected(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch); client = module.app.test_client()
    class BadResponse(FakeResponse):
        def read(self, *_):
            return json.dumps({'host':'https://attacker.example','radar':{'past':[{'time':1,'path':'/v2/radar/x'}]}}).encode()
    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *args, **kwargs: BadResponse())
    module.RADAR_CACHE.update(expires=0, host='', frames=[])
    assert client.get('/api/radar?location_id=1').status_code == 503
