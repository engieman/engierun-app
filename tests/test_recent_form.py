import pytest

from engierun.recent_form import compare_recent_form


def _result(date, seconds, status="OK", event="3000m"):
    return {
        "date": date,
        "event": event,
        "seconds": seconds,
        "status": status,
        "mark": "" if seconds is None else str(seconds),
        "meet": f"Meet {date}",
    }


def test_recent_form_uses_latest_four_valid_results_in_the_shared_event():
    athlete_a = [
        _result("2025-01-01", 560.0),
        _result("2025-01-10", 550.0),
        _result("2025-01-20", None, status="DNF"),
        _result("2025-02-01", 545.0),
        _result("2025-02-10", 540.0),
        _result("2025-02-20", 538.0),
    ]
    athlete_b = [
        _result("2025-01-05", 552.0),
        _result("2025-01-15", 548.0),
        _result("2025-02-05", 546.0),
        _result("2025-02-15", 544.0),
    ]

    comparison = compare_recent_form(athlete_a, athlete_b, event="3000m", limit=4)

    assert [row["seconds"] for row in comparison["a_results"]] == [538.0, 540.0, 545.0, 550.0]
    assert comparison["a_average_seconds"] == pytest.approx(543.25)
    assert comparison["b_average_seconds"] == pytest.approx(547.5)
    assert comparison["winner"] == "a"
    assert comparison["difference_seconds"] == pytest.approx(4.25)
    assert comparison["percent_faster"] == pytest.approx(0.7763, abs=0.0001)
    assert comparison["a_sample_size"] == 4
    assert comparison["b_sample_size"] == 4


def test_recent_form_skips_missing_or_invalid_dates_and_sorts_real_dates():
    athlete_a = [
        _result("2025-2-20", 530.0),
        _result("not-a-date", 531.0),
        {"event": "3000m", "seconds": 532.0, "status": "OK"},
        _result("2025-02-09T12:00:00+00:00", 533.0),
        _result("2025-10-01", 529.0),
    ]

    comparison = compare_recent_form(athlete_a, [], event="3000m", limit=4)

    assert [row["seconds"] for row in comparison["a_results"]] == [529.0, 533.0]
    assert comparison["a_sample_size"] == 2
