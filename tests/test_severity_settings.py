from test_app import token
from test_locations import authenticated_client


def valid_settings(csrf, **overrides):
    data = {
        'csrf_token': csrf,
        'watch_rain': '1', 'watch_gust': '35',
        'moderate_rain': '25', 'moderate_gust': '65',
        'heavy_rain': '45', 'heavy_gust': '90',
        'extreme_rain': '90', 'extreme_gust': '120',
    }
    data.update(overrides)
    return data


def test_admin_can_recalibrate_matrix(tmp_path, monkeypatch):
    module, client = authenticated_client(tmp_path, monkeypatch)
    csrf = token(client, '/admin/dashboard')
    response = client.post('/admin/severity', data=valid_settings(csrf), follow_redirects=True)
    assert response.status_code == 200
    assert b'severity matrix recalibrated' in response.data
    settings = module.get_severity_settings()
    assert settings['moderate_rain'] == 25
    assert module.classify(25, 0, settings) == 'moderate'
    assert module.classify(91, 0, settings) == 'extreme'
    assert module.WEATHER_CACHE['payload'] is None


def test_matrix_requires_strictly_increasing_values(tmp_path, monkeypatch):
    _, client = authenticated_client(tmp_path, monkeypatch)
    csrf = token(client, '/admin/dashboard')
    response = client.post('/admin/severity', data=valid_settings(csrf, heavy_rain='20'), follow_redirects=True)
    assert b'strictly increasing' in response.data


def test_matrix_update_requires_authentication(tmp_path, monkeypatch):
    module, client = authenticated_client(tmp_path, monkeypatch)
    client.post('/admin/logout', data={'csrf_token': token(client, '/admin/dashboard')})
    csrf = token(client, '/admin')
    response = client.post('/admin/severity', data=valid_settings(csrf))
    assert response.status_code == 302
    assert '/admin' in response.headers['Location']


def test_main_page_displays_saved_thresholds(tmp_path, monkeypatch):
    module, client = authenticated_client(tmp_path, monkeypatch)
    csrf = token(client, '/admin/dashboard')
    client.post('/admin/severity', data=valid_settings(csrf, moderate_rain='27.5'))
    response = client.get('/')
    assert b'27.5 mm' in response.data
