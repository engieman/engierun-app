import importlib
import json


def test_app_loads_authorized_compiled_dataset_including_unmarked_roster_members(
    monkeypatch, tmp_path
):
    dataset = {
        "schema_version": 1,
        "athletes": [
            {
                "id": "tfrrs:100",
                "name": "Runner One",
                "school": "Harvard",
                "gender": "Female",
                "year": "SO-2",
                "profile_url": "https://www.tfrrs.org/athletes/100/Harvard/Runner_One.html",
                "bests": {"1500m": {"mark": "4:20.00", "seconds": 260.0}},
                "results": [
                    {
                        "date": "2026-01-01",
                        "event": "1500m",
                        "mark": "4:22.00",
                        "seconds": 262.0,
                        "meet": "Licensed Meet",
                        "status": None,
                    }
                ],
            },
            {
                "id": "tfrrs:200",
                "name": "Field Athlete",
                "school": "Yale",
                "gender": "Male",
                "year": "FR-1",
                "profile_url": "https://www.tfrrs.org/athletes/200/Yale/Field_Athlete.html",
                "bests": {},
                "results": [],
            },
        ],
    }
    path = tmp_path / "ivy.json"
    path.write_text(json.dumps(dataset))
    monkeypatch.setenv("ENGIERUN_DATASET", str(path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)

    import app

    importlib.reload(app)
    loaded = app.load_athletes()

    assert set(loaded) == {"Runner One", "Field Athlete"}
    assert loaded["Runner One"]["marks"] == {"1500m": "4:20.00"}
    assert loaded["Runner One"]["results"][0]["seconds"] == 262.0
    assert loaded["Field Athlete"]["marks"] == {}
