import importlib


def load(tmp_path, monkeypatch):
    monkeypatch.setenv("WEATHERWATCH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COOKIE_SECURE", "0")
    import app
    importlib.reload(app)
    app.app.config.update(TESTING=True)
    return app


def token(client, path="/admin/register"):
    client.get(path)
    with client.session_transaction() as s:
        return s["csrf"]


def test_home_and_seed_data(tmp_path, monkeypatch):
    module=load(tmp_path,monkeypatch); client=module.app.test_client()
    response=client.get("/")
    assert response.status_code==200
    assert b"Therma South Inc" in response.data
    assert b"Made with" in response.data
    assert b"weather-ambient" in response.data
    assert b"Select a site to reflect its weather" in response.data
    assert b"/admin" not in response.data


def test_one_time_registration_and_location_crud(tmp_path, monkeypatch):
    module=load(tmp_path,monkeypatch); client=module.app.test_client()
    csrf=token(client)
    response=client.post("/admin/register",data={"csrf_token":csrf,"username":"operator","password":"a-very-strong-password","confirmation":"a-very-strong-password"})
    assert response.status_code==302
    assert client.get("/admin/register").status_code==302
    csrf=token(client,"/admin")
    client.post("/admin",data={"csrf_token":csrf,"username":"operator","password":"a-very-strong-password"})
    csrf=token(client,"/admin/dashboard")
    response=client.post("/admin/locations",data={"csrf_token":csrf,"name":"Test Site","address":"Test address","latitude":"14.5","longitude":"121","plus_code":"ABC"},follow_redirects=True)
    assert b"Test Site" in response.data


def test_csrf_rejected(tmp_path, monkeypatch):
    module=load(tmp_path,monkeypatch); client=module.app.test_client()
    assert client.post("/admin/register",data={}).status_code==400


def test_severity_boundaries(tmp_path, monkeypatch):
    module=load(tmp_path,monkeypatch)
    assert module.classify(0,0)=="normal"
    assert module.classify(1,0)=="watch"
    assert module.classify(30,0)=="moderate"
    assert module.classify(50,0)=="heavy"
    assert module.classify(101,0)=="extreme"
