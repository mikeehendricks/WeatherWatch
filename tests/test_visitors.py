from datetime import datetime, timedelta, timezone

from test_locations import authenticated_client
from test_app import load, token


def test_public_visit_is_recorded(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch)
    client = module.app.test_client()
    response = client.get('/', environ_base={'REMOTE_ADDR': '203.0.113.10'}, headers={'User-Agent': 'Test Browser'})
    assert response.status_code == 200
    with module.db() as conn:
        visitor = conn.execute("SELECT * FROM visitors WHERE ip='203.0.113.10'").fetchone()
        event = conn.execute("SELECT * FROM visitor_events WHERE ip='203.0.113.10'").fetchone()
    assert visitor is not None
    assert visitor['request_count'] == 1
    assert event['user_agent'] == 'Test Browser'


def test_admin_sees_active_visitor(tmp_path, monkeypatch):
    module, client = authenticated_client(tmp_path, monkeypatch)
    client.get('/', environ_base={'REMOTE_ADDR': '198.51.100.8'})
    response = client.get('/admin/dashboard')
    assert b'198.51.100.8' in response.data
    assert b'Active visitors' in response.data


def test_visitor_export_by_time(tmp_path, monkeypatch):
    module, client = authenticated_client(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    with module.db() as conn:
        conn.execute("INSERT INTO visitors(ip,isp,first_seen,last_seen,request_count,user_agent) VALUES(?,?,?,?,?,?)",
                     ('192.0.2.4', '=unsafe ISP', now.isoformat(), now.isoformat(), 1, '@unsafe agent'))
        conn.execute("INSERT INTO visitor_events(ip,visited_at,user_agent) VALUES(?,?,?)",
                     ('192.0.2.4', now.isoformat(), '@unsafe agent'))
    start = (now - timedelta(hours=1)).isoformat()
    end = (now + timedelta(hours=1)).isoformat()
    response = client.get('/admin/visitors/export', query_string={'start': start, 'end': end})
    assert response.status_code == 200
    assert response.mimetype == 'text/csv'
    assert 'attachment;' in response.headers['Content-Disposition']
    assert b"'=unsafe ISP" in response.data
    assert b"'@unsafe agent" in response.data


def test_visitor_export_requires_login(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch)
    response = module.app.test_client().get('/admin/visitors/export')
    assert response.status_code == 302
    assert '/admin' in response.headers['Location']
