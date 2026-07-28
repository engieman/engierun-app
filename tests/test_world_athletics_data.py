from pathlib import Path

from engierun.world_athletics_data import load_world_athletics_results


def test_loader_parses_licensed_semicolon_data_and_pseudonymises_athletes(tmp_path: Path):
    source = tmp_path / "wa.csv"
    source.write_text(
        "Rank;Mark;Competitor;DOB;Nat;Pos;Venue;Date;Results Score;Mark [meters or seconds];Event;Wind;Sex\n"
        "1;3:50.00;Runner One;1990-01-01;USA;1;Rome;2022-01-01;1200;230.0;1500 Metres;;male\n"
        "2;3:50.00;Runner One;1990-01-01;USA;1;Rome;2022-01-01;1200;230.0;1500 Metres;;male\n"
        "1;8.00;Thrower;1990-01-01;USA;1;Rome;2022-01-01;1000;8.0;Shot Put;;male\n",
        encoding="utf-8",
    )
    rows = load_world_athletics_results(source)
    assert len(rows) == 1
    assert rows[0]["seconds"] == 230.0
    assert rows[0]["event"] == "1500 Metres"
    assert rows[0]["athlete_id"].startswith("wa_")
    assert "Runner" not in repr(rows)
    assert "Rome" not in repr(rows)
