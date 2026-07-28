import pytest

from engierun.comparison import compare_personal_bests


def test_head_to_head_scores_shared_events_and_reports_actual_time_gap():
    ashton = {
        "800m": "1:55.27",
        "1500m": "3:47.34",
        "Mile": "4:06.42",
        "3000m": "8:23.23",
        "5000m": "14:42.03",
        "10000m": "31:02.1",
    }
    callahan = {
        "800m": "1:56.85",
        "1500m": "3:51.14",
        "Mile": "4:06.01",
        "3000m": "8:21.14",
        "5000m": "14:25.88",
        "10000m": "30:45.3",
    }

    comparison = compare_personal_bests(ashton, callahan)

    assert comparison["shared_event_count"] == 6
    assert comparison["a_points"] == 2
    assert comparison["b_points"] == 4
    assert comparison["a_win_share_percent"] == pytest.approx(33.3, abs=0.05)
    assert comparison["b_win_share_percent"] == pytest.approx(66.7, abs=0.05)
    # Overall pace edge is a geometric aggregation of all shared event-time ratios;
    # it is distinct from the 66.7% event win share shown to users.
    assert comparison["overall_time_edge_winner"] == "b"
    assert comparison["overall_time_edge_percent"] == pytest.approx(0.05297, abs=0.00001)

    by_event = {row["event"]: row for row in comparison["events"]}
    assert by_event["800m"]["winner"] == "a"
    assert by_event["800m"]["difference_seconds"] == pytest.approx(1.58)
    assert by_event["800m"]["percent_faster"] == pytest.approx(1.3522, abs=0.0001)
    assert by_event["Mile"]["winner"] == "b"


def test_ties_split_points_and_invalid_shared_marks_are_excluded():
    a_marks = {"5000m": "14:00", "800m": "1:55.00", "Mile": "DNF"}
    b_marks = {"Mile": "4:10", "800m": "1:55", "5000m": "not a time"}

    comparison = compare_personal_bests(a_marks, b_marks)

    assert comparison["shared_event_count"] == 1
    assert comparison["a_points"] == 0.5
    assert comparison["b_points"] == 0.5
    assert comparison["a_win_share_percent"] == 50
    assert comparison["b_win_share_percent"] == 50
    assert [row["event"] for row in comparison["events"]] == ["800m"]
    tie = comparison["events"][0]
    assert tie["winner"] == "tie"
    assert tie["difference_seconds"] == 0
    assert tie["percent_faster"] == 0
    assert tie["faster_seconds"] == pytest.approx(115)
    assert tie["slower_seconds"] == pytest.approx(115)
