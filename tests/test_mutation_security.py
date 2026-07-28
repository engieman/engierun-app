import importlib

import pytest


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)

    import app

    importlib.reload(app)
    app.app.config.update(TESTING=True)
    return app.app.test_client()


@pytest.mark.parametrize(
    "path",
    [
        "/add",
        "/delete/DEMO%20RUNNER",
        "/set_category/DEMO%20RUNNER/Male",
        "/import",
    ],
)
def test_public_app_ships_no_shared_state_or_network_import_routes(client, path):
    assert client.get(path).status_code == 404
    assert client.post(path, data={}).status_code == 404
