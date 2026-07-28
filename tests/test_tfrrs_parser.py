from pathlib import Path

import pytest

from engierun.tfrrs import parse_athlete_profile

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_athlete_profile_extracts_identity_bests_and_chronological_results():
    html = (FIXTURES / "tfrrs_athlete_profile.html").read_text()

    athlete = parse_athlete_profile(
        html,
        profile_url="https://www.tfrrs.org/athletes/8617086/Dartmouth/Ayush_Saran.html",
        gender="Male",
    )

    assert athlete["tfrrs_id"] == "8617086"
    assert athlete["name"] == "Ayush Saran"
    assert athlete["year"] == "FR-1"
    assert athlete["school"] == "Dartmouth"
    assert athlete["gender"] == "Male"
    assert athlete["bests"]["3000m"]["mark"] == "9:10.97"
    assert athlete["bests"]["3000m"]["seconds"] == pytest.approx(550.97)
    assert athlete["bests"]["8K XC"]["seconds"] == pytest.approx(1695.3)

    assert [result["date"] for result in athlete["results"]] == [
        "2023-09-29",
        "2025-01-25",
        "2025-04-11",
    ]
    assert athlete["results"][1]["event"] == "3000m"
    assert athlete["results"][1]["meet"] == "Riverhawk Invitational"
    assert athlete["results"][1]["seconds"] == pytest.approx(555.73)
    assert athlete["results"][0]["status"] == "DNF"
    assert athlete["results"][0]["seconds"] is None


def test_parse_athlete_profile_uses_range_end_dates():
    html = """
    <h3 class="panel-title large-title">RANGE RUNNER (SR-4)</h3>
    <a href="/teams/tf/MA_college_m_Test.html"><h3 class="panel-title">TEST</h3></a>
    <div id="meet-results">
      <table class="table table-hover">
        <thead><tr><th><a href="/results/1">Same Month</a><span>February  7- 8, 2025</span></th></tr></thead>
        <tr><td>3000</td><td>9:00.00</td></tr>
      </table>
      <table class="table table-hover">
        <thead><tr><th><a href="/results/2">Cross Month</a><span>Apr 30-May 1, 2021</span></th></tr></thead>
        <tr><td>3000</td><td>9:01.00</td></tr>
      </table>
    </div>
    """

    athlete = parse_athlete_profile(
        html,
        profile_url="https://www.tfrrs.org/athletes/1234567/Test/Range_Runner.html",
        gender="Female",
    )

    assert [(result["meet"], result["date"]) for result in athlete["results"]] == [
        ("Cross Month", "2021-05-01"),
        ("Same Month", "2025-02-08"),
    ]


def test_parse_athlete_profile_normalizes_events_without_timing_field_marks():
    html = """
    <h3 class="panel-title large-title">FIELD RUNNER (JR-3)</h3>
    <table id="all_bests">
      <tr>
        <td>3000 Meters</td><td><a>9:05.25</a></td>
        <td>PV</td><td><a>5.21m 17' 1&quot;</a></td>
      </tr>
    </table>
    """

    athlete = parse_athlete_profile(
        html,
        profile_url="https://www.tfrrs.org/athletes/1234568/Test/Field_Runner.html",
        gender="Male",
    )

    assert athlete["bests"]["3000m"]["seconds"] == pytest.approx(545.25)
    assert athlete["bests"]["PV"] == {"mark": "5.21m 17' 1\"", "seconds": None}


def test_parse_athlete_profile_rejects_malformed_identity():
    html = '<h3 class="panel-title large-title">ATHLETE WITHOUT YEAR ()</h3>'

    with pytest.raises(ValueError, match="Malformed TFRRS athlete identity"):
        parse_athlete_profile(
            html,
            profile_url="https://www.tfrrs.org/athletes/1234569/Test/Athlete.html",
            gender="Female",
        )
