from pathlib import Path

from engierun.tfrrs import parse_team_roster

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_team_roster_only_returns_current_roster_table_profiles():
    html = (FIXTURES / "tfrrs_team_roster.html").read_text()

    roster = parse_team_roster(
        html,
        team_url="https://www.tfrrs.org/teams/tf/MA_college_m_Harvard.html",
        school="Harvard",
        gender="Male",
    )

    assert roster == [
        {
            "tfrrs_id": "8984078",
            "name": "Liam Acevedo",
            "year": "SO-2",
            "school": "Harvard",
            "gender": "Male",
            "profile_url": "https://www.tfrrs.org/athletes/8984078/Harvard/Liam_Acevedo.html",
        },
        {
            "tfrrs_id": "9251574",
            "name": "Tam Gavenas",
            "year": "FR-1",
            "school": "Harvard",
            "gender": "Male",
            "profile_url": "https://www.tfrrs.org/athletes/9251574/Harvard/Tam_Gavenas.html",
        },
    ]
