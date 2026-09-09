from test_app import load, token


def authenticated_client(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch)
    client = module.app.test_client()
    csrf = token(client)
    client.post('/admin/register', data={
        'csrf_token': csrf, 'username': 'operator',
        'password': 'a-very-strong-password',
        'confirmation': 'a-very-strong-password'
    })
    csrf = token(client, '/admin')
    client.post('/admin', data={
        'csrf_token': csrf, 'username': 'operator',
        'password': 'a-very-strong-password'
    })
    return module, client


def test_edit_location(tmp_path, monkeypatch):
    module, client = authenticated_client(tmp_path, monkeypatch)
    with module.db() as conn:
        location_id = conn.execute("SELECT id FROM locations WHERE name='Malabon Admin'").fetchone()['id']
    response = client.get(f'/admin/locations/{location_id}/edit')
    assert response.status_code == 200
    assert b'Malabon Admin' in response.data
    csrf = token(client, f'/admin/locations/{location_id}/edit')
    response = client.post(f'/admin/locations/{location_id}/edit', data={
        'csrf_token': csrf, 'name': 'Malabon Operations',
        'address': 'Updated address', 'latitude': '14.7',
        'longitude': '121.0', 'plus_code': 'UPDATED'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Location updated.' in response.data
    assert b'Malabon Operations' in response.data
    with module.db() as conn:
        row = conn.execute('SELECT * FROM locations WHERE id=?', (location_id,)).fetchone()
    assert row['address'] == 'Updated address'
    assert row['latitude'] == 14.7


def test_location_cache_key_changes_for_adds_and_edits(tmp_path, monkeypatch):
    module, _ = authenticated_client(tmp_path, monkeypatch)
    with module.db() as conn:
        original = [dict(row) for row in conn.execute('SELECT * FROM locations ORDER BY name')]
        conn.execute("INSERT INTO locations(name,address,latitude,longitude,plus_code,created_at) VALUES(?,?,?,?,?,?)",
                     ('New Site', 'New address', 14.0, 121.0, '', '2026-01-01T00:00:00+00:00'))
        added = [dict(row) for row in conn.execute('SELECT * FROM locations ORDER BY name')]
    assert module.locations_cache_key(original) != module.locations_cache_key(added)
    changed = [dict(item) for item in added]
    changed[0]['latitude'] += 0.1
    assert module.locations_cache_key(added) != module.locations_cache_key(changed)


def test_edit_requires_authentication(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch)
    response = module.app.test_client().get('/admin/locations/1/edit')
    assert response.status_code == 302
    assert '/admin' in response.headers['Location']


def test_edit_rejects_invalid_coordinates(tmp_path, monkeypatch):
    module, client = authenticated_client(tmp_path, monkeypatch)
    csrf = token(client, '/admin/locations/1/edit')
    response = client.post('/admin/locations/1/edit', data={
        'csrf_token': csrf, 'name': 'Site', 'address': 'Address',
        'latitude': '999', 'longitude': '121', 'plus_code': ''
    })
    assert response.status_code == 200
    assert b'valid site details' in response.data
