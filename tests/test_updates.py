from test_app import token
from test_locations import authenticated_client


def test_update_state_round_trip(tmp_path, monkeypatch):
    module, _ = authenticated_client(tmp_path, monkeypatch)
    state = {
        'status': 'updated', 'previous_commit': 'a' * 40,
        'previous_version': '1.5.0', 'updated_commit': 'b' * 40,
        'updated_version': '1.6.0'
    }
    module.save_update_state(state)
    assert module.load_update_state() == state
    assert module.UPDATE_STATE_FILE.stat().st_mode & 0o777 == 0o600


def test_rollback_rejects_missing_verified_state(tmp_path, monkeypatch):
    monkeypatch.setenv('ENABLE_WEB_UPDATES', '1')
    module, client = authenticated_client(tmp_path, monkeypatch)
    csrf = token(client, '/admin/dashboard')
    response = client.post('/admin/rollback', data={'csrf_token': csrf}, follow_redirects=True)
    assert response.status_code == 200
    assert b'No verified previous version' in response.data


def test_rollback_requires_authentication(tmp_path, monkeypatch):
    monkeypatch.setenv('ENABLE_WEB_UPDATES', '1')
    module, client = authenticated_client(tmp_path, monkeypatch)
    client.post('/admin/logout', data={'csrf_token': token(client, '/admin/dashboard')})
    csrf = token(client, '/admin')
    response = client.post('/admin/rollback', data={'csrf_token': csrf})
    assert response.status_code == 302
    assert '/admin' in response.headers['Location']


def test_dashboard_shows_rollback_candidate(tmp_path, monkeypatch):
    module, client = authenticated_client(tmp_path, monkeypatch)
    module.save_update_state({
        'status': 'failed', 'previous_commit': 'a' * 40,
        'previous_version': '1.5.0'
    })
    response = client.get('/admin/dashboard')
    assert b'Roll back to 1.5.0' in response.data
    assert b'Last update failed' in response.data
