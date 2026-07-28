import importlib

import psycopg2


def test_health_reports_ready_and_loaded_athlete_count(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    import app

    importlib.reload(app)
    app.app.config.update(TESTING=True)
    response = app.app.test_client().get("/health")

    assert response.status_code == 200
    assert response.get_json() == {
        "athletes": 16,
        "status": "ready",
        "storage": "json",
    }


def test_health_fails_when_explicit_dataset_is_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ENGIERUN_DATASET", str(tmp_path / "missing.json"))
    monkeypatch.chdir(tmp_path)
    import app

    importlib.reload(app)
    app.app.config.update(TESTING=True)
    response = app.app.test_client().get("/health")

    assert response.status_code == 503
    assert response.get_json() == {
        "status": "unhealthy",
        "storage": "json",
        "reason": "dataset_unavailable",
    }


def test_health_fails_closed_when_postgres_is_unreachable(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://invalid:invalid@127.0.0.1:1/engierun?connect_timeout=1",
    )
    monkeypatch.chdir(tmp_path)
    import app

    importlib.reload(app)
    app.app.config.update(TESTING=True)
    response = app.app.test_client().get("/health")

    assert response.status_code == 503
    assert response.get_json() == {
        "status": "unhealthy",
        "storage": "postgres",
        "reason": "database_dataset_unavailable",
    }


def test_health_rejects_a_json_object_that_is_not_an_athlete_dataset(
    monkeypatch, tmp_path
):
    invalid = tmp_path / "wrong-shape.json"
    invalid.write_text('{"unexpected": true}', encoding="utf-8")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ENGIERUN_DATASET", str(invalid))
    monkeypatch.chdir(tmp_path)

    import app

    importlib.reload(app)
    response = app.app.test_client().get("/health")

    assert response.status_code == 503
    assert response.get_json()["reason"] == "dataset_empty_or_invalid"


def test_health_rejects_named_json_rows_without_usable_marks(monkeypatch, tmp_path):
    invalid = tmp_path / "unusable.json"
    invalid.write_text(
        '{"athletes":[{"name":"Named but unusable","school":"Brown",'
        '"gender":"Male","marks":{},"results":[]}]}',
        encoding="utf-8",
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ENGIERUN_DATASET", str(invalid))
    monkeypatch.chdir(tmp_path)

    import app

    importlib.reload(app)
    response = app.app.test_client().get("/health")

    assert response.status_code == 503
    assert response.get_json()["reason"] == "dataset_empty_or_invalid"


class _FakeCursor:
    def __init__(self, rows=None, failure=None):
        self.rows = rows or []
        self.failure = failure
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query):
        self.queries.append(str(query))

    def fetchall(self):
        if self.failure:
            raise self.failure
        return self.rows


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self._cursor


def _load_postgres_app(monkeypatch, tmp_path, cursor):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/engierun")
    monkeypatch.chdir(tmp_path)
    import app

    importlib.reload(app)
    monkeypatch.setattr(app, "_db_conn", lambda: _FakeConnection(cursor))
    return app


def test_postgres_health_fails_when_dataset_query_fails_after_connection(
    monkeypatch, tmp_path
):
    cursor = _FakeCursor(failure=psycopg2.OperationalError("dataset unavailable"))
    app = _load_postgres_app(monkeypatch, tmp_path, cursor)

    response = app.app.test_client().get("/health")

    assert response.status_code == 503
    assert response.get_json()["reason"] == "database_dataset_unavailable"


def test_postgres_health_rejects_named_rows_without_usable_marks(monkeypatch, tmp_path):
    cursor = _FakeCursor(
        rows=[("Named but unusable", "Brown", "{}", "Male", "[]")]
    )
    app = _load_postgres_app(monkeypatch, tmp_path, cursor)

    response = app.app.test_client().get("/health")

    assert response.status_code == 503
    assert response.get_json()["reason"] == "database_dataset_unavailable"


def test_postgres_health_reads_athletes_without_schema_or_write_statements(
    monkeypatch, tmp_path
):
    cursor = _FakeCursor(
        rows=[("Demo", "Brown", '{"1500m":"4:00.00"}', "Male", "[]")]
    )
    app = _load_postgres_app(monkeypatch, tmp_path, cursor)

    response = app.app.test_client().get("/health")

    assert response.status_code == 200
    assert response.get_json()["athletes"] == 1
    executed = "\n".join(cursor.queries).upper()
    assert "SELECT" in executed
    assert not any(word in executed for word in ("CREATE", "ALTER", "INSERT", "UPDATE", "DELETE"))
