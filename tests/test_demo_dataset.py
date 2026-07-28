import importlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_checked_in_athlete_data_is_unambiguously_synthetic_and_complete_for_ui_demo():
    payload = json.loads((ROOT / "data" / "demo_athletes.json").read_text())

    assert payload["source_type"] == "synthetic-demo"
    assert payload["synthetic"] is True
    assert "not real athlete data" in payload["notice"].lower()
    assert len(payload["athletes"]) == 16
    assert {athlete["school"] for athlete in payload["athletes"]} == {
        "Brown",
        "Columbia",
        "Cornell",
        "Dartmouth",
        "Harvard",
        "Penn",
        "Princeton",
        "Yale",
    }
    assert {athlete["gender"] for athlete in payload["athletes"]} == {
        "Female",
        "Male",
    }
    assert all(athlete["name"].startswith("DEMO RUNNER") for athlete in payload["athletes"])
    assert all(not athlete["profile_url"] for athlete in payload["athletes"])


def test_demo_warning_is_rendered_on_public_pages(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ENGIERUN_DATASET", raising=False)
    monkeypatch.chdir(tmp_path)

    import app

    importlib.reload(app)
    client = app.app.test_client()

    for path in ("/", "/athletes", "/compare", "/predictor"):
        response = client.get(path)
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "Synthetic demo data" in html
        assert "not real athlete results" in html
