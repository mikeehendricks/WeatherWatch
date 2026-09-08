from test_app import load, token


def register(client):
    csrf = token(client)
    client.post('/admin/register', data={
        'csrf_token': csrf, 'username': 'operator',
        'password': 'a-very-strong-password',
        'confirmation': 'a-very-strong-password'
    })


def test_admin_security_headers(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch)
    response = module.app.test_client().get('/admin')
    assert response.headers['Cache-Control'] == 'no-store, max-age=0'
    assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
    assert response.headers['X-Frame-Options'] == 'DENY'


def test_login_rate_limit(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch); client = module.app.test_client()
    register(client)
    for _ in range(5):
        csrf = token(client, '/admin')
        response = client.post('/admin', data={'csrf_token': csrf, 'username': 'operator', 'password': 'wrong-password'})
        assert response.status_code == 200
    csrf = token(client, '/admin')
    response = client.post('/admin', data={'csrf_token': csrf, 'username': 'operator', 'password': 'wrong-password'})
    assert response.status_code == 429


def test_inline_event_handlers_absent(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch); client = module.app.test_client()
    register(client)
    csrf = token(client, '/admin')
    client.post('/admin', data={'csrf_token': csrf, 'username': 'operator', 'password': 'a-very-strong-password'})
    response = client.get('/admin/dashboard')
    assert b'onsubmit=' not in response.data


def test_version_in_footer(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch)
    response = module.app.test_client().get('/')
    assert f'Version {module.APP_VERSION}'.encode() in response.data
