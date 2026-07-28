import importlib

import pytest


def client(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    import app

    importlib.reload(app)
    app.app.config.update(TESTING=True)
    return app.app.test_client()


def test_predictor_page_exposes_honest_benchmark_and_caveat(monkeypatch, tmp_path):
    response = client(monkeypatch, tmp_path).get("/predictor")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Next performance predictor" in html
    assert "17 / 20" in html
    assert "next recorded top-list performance" in html
    assert "not necessarily the athlete’s genuine next race" in html


def test_predictor_accepts_four_manual_results_and_returns_visual_forecast(monkeypatch, tmp_path):
    response = client(monkeypatch, tmp_path).post(
        "/predictor",
        data={
            "event": "1500m",
            "target_date": "2026-08-15",
            "r1": "4:04.00",
            "r2": "4:03.00",
            "r3": "4:02.00",
            "r4": "4:01.00",
        },
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Predicted performance" in html
    assert "4:02" in html
    assert "Heuristic confidence" in html
    assert "not a calibrated probability" in html
    assert "Uncalibrated range" in html
    assert 'class="forecast-orbit"' in html


@pytest.mark.parametrize(
    ("invalid_mark", "error_text"),
    [
        ("garbage4:03.20junk", "Enter four valid race times"),
        ("99:99", "Enter four valid race times"),
        ("10:00", "Enter realistic 1500m times"),
    ],
)
def test_predictor_rejects_malformed_or_implausible_manual_times(
    monkeypatch, tmp_path, invalid_mark, error_text
):
    app_client = client(monkeypatch, tmp_path)
    response = app_client.post(
        "/predictor",
        data={
            "event": "1500m",
            "target_date": "2026-08-15",
            "r1": invalid_mark,
            "r2": "4:03.00",
            "r3": "4:02.00",
            "r4": "4:01.00",
        },
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert error_text in html
    assert 'class="forecast-orbit"' not in html


def test_race_time_parser_is_fully_anchored_and_checks_colon_components(
    monkeypatch, tmp_path
):
    client(monkeypatch, tmp_path)
    import app

    assert app.time_to_seconds("4:03.20") == pytest.approx(243.2)
    assert app.time_to_seconds("garbage4:03.20junk") is None
    assert app.time_to_seconds("99:99") is None
