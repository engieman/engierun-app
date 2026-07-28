from __future__ import annotations

from datetime import date, timedelta

import pytest

from engierun.predictor import InsufficientHistoryError, predict_next_performance


def _row(athlete, day, seconds, event="1500 Metres"):
    return {
        "athlete_id": athlete,
        "date": day,
        "event": event,
        "seconds": seconds,
        "meet": f"Meet {day}",
    }


def test_predictor_uses_only_records_strictly_before_cutoff():
    start = date(2020, 1, 1)
    records = [_row("a", start + timedelta(days=i * 10), 240.0 - i) for i in range(4)]
    records += [_row("a", date(2020, 3, 1), 100.0), _row("a", date(2020, 4, 1), 90.0)]

    result = predict_next_performance(
        records, athlete_id="a", event="1500 Metres", cutoff=date(2020, 2, 15)
    )

    assert result["predicted_seconds"] > 200
    assert [row["date"] for row in result["recent_history"]] == [
        "2020-01-01",
        "2020-01-11",
        "2020-01-21",
        "2020-01-31",
    ]
    assert result["latest_evidence_date"] == "2020-01-31"
    assert result["cutoff"] == "2020-02-15"


def test_predictor_returns_explanation_uncertainty_confidence_and_comparables():
    start = date(2019, 1, 1)
    records = []
    for athlete, offset in (("a", 0.0), ("b", 30.0), ("c", 60.0)):
        for i, seconds in enumerate((250, 247, 245, 244, 243, 242)):
            records.append(_row(athlete, start + timedelta(days=i * 14), seconds + offset))

    result = predict_next_performance(
        records, athlete_id="a", event="1500 Metres", cutoff=date(2019, 4, 1)
    )

    assert result["predicted_seconds"] > 0
    assert result["uncertainty_seconds"][0] <= result["predicted_seconds"]
    assert result["uncertainty_seconds"][1] >= result["predicted_seconds"]
    assert 0 <= result["confidence"] <= 1
    assert result["confidence_kind"] == "heuristic_neighbor_evidence_score"
    assert result["uncertainty_kind"] == "uncalibrated_neighbor_residual_range"
    assert result["recent_history"]
    assert result["comparable_episodes"]
    assert all(row["target_date"] < result["cutoff"] for row in result["comparable_episodes"])
    assert "baseline_seconds" in result["explanation"]
    assert "neighbor_adjustment_percent" in result["explanation"]


def test_predictor_rejects_insufficient_same_event_history():
    rows = [_row("a", date(2020, 1, day), 240.0) for day in (1, 2, 3)]
    with pytest.raises(InsufficientHistoryError):
        predict_next_performance(
            rows, athlete_id="a", event="1500 Metres", cutoff=date(2020, 2, 1)
        )


def test_same_day_and_other_event_records_do_not_enter_history():
    rows = [
        _row("a", date(2020, 1, day), 240.0 + day) for day in (1, 2, 3, 4)
    ]
    rows += [
        _row("a", date(2020, 2, 1), 100.0),
        _row("a", date(2020, 1, 5), 10.0, event="800 Metres"),
    ]
    result = predict_next_performance(
        rows, athlete_id="a", event="1500 Metres", cutoff=date(2020, 2, 1)
    )
    assert len(result["recent_history"]) == 4
    assert result["latest_evidence_date"] == "2020-01-04"
