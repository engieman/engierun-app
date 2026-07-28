import app as webapp

ATHLETES = {
    "ASHTON BANGE": {
        "school": "Dartmouth",
        "category": "Male",
        "marks": {"800m": "1:55.27", "1500m": "3:47.34", "3000m": "8:23.23"},
        "results": [
            {"date": "2025-02-20", "event": "3000m", "seconds": 498.0, "mark": "8:18.00", "meet": "Ivy Classic", "status": "OK"},
            {"date": "2025-02-10", "event": "3000m", "seconds": 500.0, "mark": "8:20.00", "meet": "Valentine", "status": "OK"},
            {"date": "2025-02-01", "event": "3000m", "seconds": 502.0, "mark": "8:22.00", "meet": "River Hawk", "status": "OK"},
            {"date": "2025-01-20", "event": "3000m", "seconds": 504.0, "mark": "8:24.00", "meet": "Season Opener", "status": "OK"},
            {"date": "2025-01-01", "event": "3000m", "seconds": 510.0, "mark": "8:30.00", "meet": "Old Meet", "status": "OK"},
        ],
    },
    "CALLAHAN FIELDER": {
        "school": "Dartmouth",
        "category": "Male",
        "marks": {"800m": "1:56.85", "1500m": "3:51.14", "3000m": "8:21.14"},
        "results": [
            {"date": "2025-02-18", "event": "3000m", "seconds": 501.0, "mark": "8:21.00", "meet": "Ivy Classic", "status": "OK"},
            {"date": "2025-02-08", "event": "3000m", "seconds": 503.0, "mark": "8:23.00", "meet": "Valentine", "status": "OK"},
            {"date": "2025-01-28", "event": "3000m", "seconds": 505.0, "mark": "8:25.00", "meet": "River Hawk", "status": "OK"},
            {"date": "2025-01-18", "event": "3000m", "seconds": 507.0, "mark": "8:27.00", "meet": "Season Opener", "status": "OK"},
        ],
    },
}


def client(monkeypatch):
    monkeypatch.setattr(webapp, "load_athletes", lambda: ATHLETES)
    webapp.app.config.update(TESTING=True)
    return webapp.app.test_client()


def test_athlete_browse_is_server_rendered_and_searchable(monkeypatch):
    response = client(monkeypatch).get("/athletes?q=ashton")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "ASHTON BANGE" in html
    assert "CALLAHAN FIELDER" not in html
    assert "Browse the field" in html
    assert 'href="/compare?a=ASHTON+BANGE"' in html


def test_head_to_head_is_visual_without_a_chart_library(monkeypatch):
    response = client(monkeypatch).get(
        "/compare?a=ASHTON+BANGE&b=CALLAHAN+FIELDER&event=3000m"
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Head-to-head" in html
    assert "2–1" in html
    assert "1.58s" in html
    assert "1.35% faster" in html
    assert "66.7% event win share" in html
    assert "33.3% event win share" in html
    assert "0.86% aggregate time edge" in html
    assert 'class="edge-bar"' in html
    assert html.count("Fastest") == 3
    assert "chart.js" not in html.lower()
    assert "comparison.py" not in html


def test_recent_form_renders_latest_four_races_and_average(monkeypatch):
    response = client(monkeypatch).get(
        "/compare?a=ASHTON+BANGE&b=CALLAHAN+FIELDER&event=3000m"
    )
    html = response.get_data(as_text=True)

    assert "Recent form" in html
    assert "Last 4 valid 3000m results" in html
    assert "8:21.00" in html
    assert "8:27.00" in html
    assert "8:30.00" not in html
    assert "8:21.00 avg" in html
    assert "8:24.00 avg" in html
    assert "3.00s faster" in html


def test_comparison_has_clear_empty_state_when_results_are_unavailable(monkeypatch):
    athletes = {name: {**data, "results": []} for name, data in ATHLETES.items()}
    monkeypatch.setattr(webapp, "load_athletes", lambda: athletes)
    webapp.app.config.update(TESTING=True)

    html = webapp.app.test_client().get(
        "/compare?a=ASHTON+BANGE&b=CALLAHAN+FIELDER&event=3000m"
    ).get_data(as_text=True)

    assert "Recent race history isn’t available yet" in html
    assert "Personal-best comparison is still shown above" in html
