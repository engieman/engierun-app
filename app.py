import json
import math
import os
import re
from datetime import datetime, timedelta, timezone

import psycopg2
from flask import Flask, render_template, request

from engierun.comparison import compare_personal_bests
from engierun.predictor import InsufficientHistoryError, predict_next_performance
from engierun.recent_form import compare_recent_form

app = Flask(__name__)
DATA_FILE = "athletes.json"


@app.context_processor
def dataset_mode():
    configured = os.environ.get("ENGIERUN_DATASET", "data/demo_athletes.json")
    is_demo = not os.environ.get("DATABASE_URL") and os.path.basename(configured) == "demo_athletes.json"
    return {"demo_data": is_demo}

SAMPLE = {}

AXES = {
    "Short Speed (800/1500)": ["800m", "1000m", "1500m", "Mile"],
    "3k Speed-Endurance": ["1500m", "Mile", "3000m", "5000m"],
    "5k/10k Aerobic Engine": ["5000m", "10000m"],
}
EVENTS = ["800m", "1000m", "1500m", "Mile", "3000m", "5000m", "10000m"]
CATEGORIES = ["Male", "Female"]

EVENT_PATTERNS = [
    ("10000m", r"10[,\s]?000|10\s?k\b"),
    ("5000m",  r"5000|5\s?k\b"),
    ("3000mSC", r"3000\s*S\.?C|steeple"),
    ("3000m",  r"3000|3\s?k\b"),
    ("1500m",  r"1500"),
    ("Mile",   r"\bmile\b|1609"),
    ("1000m",  r"\b1000\b|1\s?k\b"),
    ("800m",   r"\b800\b"),
    ("400m",   r"\b400\b"),
    ("200m",   r"\b200\b"),
    ("100m",   r"\b100\b"),
    ("60m",    r"\b60\b"),
]

EVENT_BOUNDS = {
    "60m": (6, 12), "100m": (9, 18), "200m": (18, 40), "400m": (42, 75),
    "800m": (95, 150), "1000m": (125, 200), "1500m": (185, 320), "Mile": (210, 360),
    "3000m": (400, 700), "5000m": (750, 1200), "10000m": (1550, 2400),
}


def match_event(text):
    for canon, pat in EVENT_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return canon
    return None


def clean_name(name):
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"\s*\(.*?\)\s*", "", name)
    return name.strip() or "Unknown"


def detect_category(page_text):
    """Best-effort guess of Male/Female from a TFRRS page's text."""
    t = (page_text or "").lower()
    if re.search(r"women'?s\b|\bwomen\b|\bfemale\b", t):
        return "Female"
    if re.search(r"men'?s\b|\bmen\b|\bmale\b", t):
        return "Male"
    return ""


# --- Storage: Postgres if DATABASE_URL is set (Render), else JSON (local) ---
DATABASE_URL = os.environ.get("DATABASE_URL")
_DB = DATABASE_URL.replace("postgres://", "postgresql://", 1) if DATABASE_URL else ""


def _db_conn():
    if not _DB:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg2.connect(_DB)


_ATHLETE_SELECT = """
SELECT record->>'name', record->>'school', record->>'marks',
       record->>'category', record->>'results'
FROM (SELECT to_jsonb(athletes) AS record FROM athletes) AS rows
"""


if DATABASE_URL:
    def load_athletes():
        try:
            with _db_conn() as conn, conn.cursor() as cur:
                cur.execute(_ATHLETE_SELECT)
                rows = cur.fetchall()
            out = {}
            for name, school, marks, category, results in rows:
                if not isinstance(name, str) or not name.strip():
                    raise ValueError("database athlete row is missing a name")
                try:
                    m = json.loads(marks) if marks else {}
                    if not isinstance(m, dict):
                        m = {}
                except (json.JSONDecodeError, TypeError):
                    m = {}
                try:
                    race_results = json.loads(results) if results else []
                    if not isinstance(race_results, list):
                        race_results = []
                except (json.JSONDecodeError, TypeError):
                    race_results = []
                out[clean_name(name)] = {
                    "school": school or "",
                    "category": category or "",
                    "marks": {k: str(v) for k, v in m.items()},
                    "results": race_results,
                }
            return out
        except (psycopg2.Error, OSError, ValueError, TypeError) as exc:
            app.logger.error("database load failed: %s", exc)
            return {}

else:
    def _bundled_athletes():
        """Load a compiled dataset, falling back to the checked-in synthetic demo."""
        default_snapshot = os.path.join(
            os.path.dirname(__file__), "data", "demo_athletes.json"
        )
        snapshot = os.environ.get("ENGIERUN_DATASET", default_snapshot)
        try:
            with open(snapshot) as handle:
                rows = json.load(handle).get("athletes", [])
            loaded = {}
            for row in rows:
                if not isinstance(row, dict) or not row.get("name"):
                    continue
                raw_marks = row.get("marks")
                if not isinstance(raw_marks, dict):
                    raw_marks = {
                        event: value.get("mark")
                        for event, value in row.get("bests", {}).items()
                        if isinstance(value, dict) and value.get("mark")
                    }
                loaded[clean_name(row["name"])] = {
                    "id": row.get("id"),
                    "school": row.get("school", ""),
                    "category": row.get("category", row.get("gender", "")),
                    "year": row.get("year"),
                    "profile_url": row.get("profile_url"),
                    "marks": {key: str(value) for key, value in raw_marks.items()},
                    "results": row.get("results", []),
                }
            return loaded
        except (OSError, ValueError, TypeError):
            return {}

    def load_athletes():
        if not os.path.exists(DATA_FILE):
            return _bundled_athletes()
        try:
            with open(DATA_FILE) as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise TypeError("athletes file is not a JSON object")
            clean = {}
            for name, d in data.items():
                if isinstance(d, dict) and isinstance(d.get("marks"), dict):
                    clean[clean_name(name)] = {
                        "school": d.get("school", ""),
                        "category": d.get("category", ""),
                        "marks": {k: str(v) for k, v in d["marks"].items()},
                        "results": d.get("results", []),
                    }
            return clean
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            app.logger.warning(
                "athletes.json unreadable; using bundled data: %s", exc
            )
            try:
                os.replace(DATA_FILE, DATA_FILE + ".corrupt")
            except OSError as backup_error:
                app.logger.warning("could not preserve corrupt athletes file: %s", backup_error)
            return _bundled_athletes()


def time_to_seconds(mark):
    if isinstance(mark, bool) or mark is None:
        return None
    match = re.fullmatch(r"(?:(\d+):)?(\d+(?:\.\d+)?)", str(mark).strip())
    if not match:
        return None
    minutes = int(match.group(1)) if match.group(1) else 0
    seconds = float(match.group(2))
    if match.group(1) and seconds >= 60:
        return None
    total = minutes * 60 + seconds
    return total if math.isfinite(total) and total > 0 else None


def axis_seconds(marks, events):
    vals = [time_to_seconds(marks[e]) for e in events
            if e in marks and time_to_seconds(marks[e])]
    return sum(vals) / len(vals) if vals else None


def _score_pair(a, b, floor):
    best = min(a, b)
    return (round(floor + (best / a) ** 8 * (100 - floor), 1),
            round(floor + (best / b) ** 8 * (100 - floor), 1))


def compare_axes(a_marks, b_marks, floor=40):
    labels, a_scores, b_scores = [], [], []
    for axis, evs in AXES.items():
        a, b = axis_seconds(a_marks, evs), axis_seconds(b_marks, evs)
        if a and b:
            pa, pb = _score_pair(a, b, floor)
            labels.append(axis); a_scores.append(pa); b_scores.append(pb)

    if len(labels) < 3:
        ev_labels, ev_a, ev_b = [], [], []
        for ev in EVENTS:
            a, b = time_to_seconds(a_marks.get(ev)), time_to_seconds(b_marks.get(ev))
            if a and b:
                pa, pb = _score_pair(a, b, floor)
                ev_labels.append(ev); ev_a.append(pa); ev_b.append(pb)
        if len(ev_labels) >= len(labels):
            labels, a_scores, b_scores = ev_labels, ev_a, ev_b

    return labels, a_scores, b_scores


def label_strength_weakness(labels, scores):
    if not labels:
        return None, None
    pairs = list(zip(labels, scores))
    return max(pairs, key=lambda p: p[1])[0], min(pairs, key=lambda p: p[1])[0]


def filter_by_category(athletes, cat):
    if not cat:
        return athletes
    return {n: d for n, d in athletes.items() if d.get("category", "") == cat}


def search_filter(athletes, q):
    if not q:
        return athletes
    q = q.lower()
    return {n: d for n, d in athletes.items()
            if q in n.lower() or q in (d.get("school", "") or "").lower()}


def sort_athletes(athletes, sort_by):
    items = list(athletes.items())
    if sort_by == "school":
        items.sort(key=lambda kv: (kv[1].get("school", "") or "zzz").lower())
    elif sort_by and sort_by.startswith("event:"):
        ev = sort_by.split(":", 1)[1]
        def key(kv):
            s = time_to_seconds(kv[1]["marks"].get(ev))
            return (s is None, s if s is not None else 0)
        items.sort(key=key)
    else:  # default: last name, then full name as tiebreak
        def name_key(kv):
            parts = kv[0].strip().split()
            return (parts[-1].lower() if parts else kv[0].lower(), kv[0].lower())
        items.sort(key=name_key)
    return dict(items)


def apply_view(athletes, q, cat, sort_by):
    """Search, then category filter, then sort — the full list pipeline."""
    out = search_filter(athletes, q)
    out = filter_by_category(out, cat)
    out = sort_athletes(out, sort_by)
    return out


@app.template_filter("race_time")
def format_race_time(seconds):
    """Format numeric race seconds as a compact track mark."""
    if seconds is None:
        return "—"
    minutes, remainder = divmod(float(seconds), 60)
    if minutes:
        return f"{int(minutes)}:{remainder:05.2f}"
    return f"{remainder:.2f}"


def _score_label(value):
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _load_predictor_benchmark():
    path = os.path.join(os.path.dirname(__file__), "data", "predictor_benchmark.json")
    try:
        with open(path) as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        return {
            "final_metrics": {"count": 0, "hits": 0, "hit_rate_percent": 0},
            "caveat": "Benchmark artifact is unavailable.",
        }


def _prediction_records(athletes):
    rows = []
    for athlete_name, athlete in athletes.items():
        for result in athlete.get("results", []):
            if not isinstance(result, dict):
                continue
            row = dict(result)
            row["athlete_id"] = athlete_name
            rows.append(row)
    return rows


@app.route("/")
def home():
    athletes = load_athletes()
    return render_template(
        "index.html", page="home", total=len(athletes),
        athletes_preview=list(sort_athletes(athletes, "name").items())[:3])


@app.get("/health")
def health():
    if DATABASE_URL:
        athletes = load_athletes()
        if not athletes:
            return {
                "status": "unhealthy",
                "storage": "postgres",
                "reason": "database_dataset_unavailable",
            }, 503
        return {
            "status": "ready",
            "storage": "postgres",
            "athletes": len(athletes),
        }

    default_dataset = os.path.join(os.path.dirname(__file__), "data", "demo_athletes.json")
    source = DATA_FILE if os.path.exists(DATA_FILE) else os.environ.get(
        "ENGIERUN_DATASET", default_dataset
    )
    try:
        with open(source, encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise TypeError("dataset root must be an object")
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {
            "status": "unhealthy",
            "storage": "json",
            "reason": "dataset_unavailable",
        }, 503
    athletes = load_athletes()
    if not athletes:
        return {
            "status": "unhealthy",
            "storage": "json",
            "reason": "dataset_empty_or_invalid",
        }, 503
    return {
        "status": "ready",
        "storage": "json",
        "athletes": len(athletes),
    }


@app.route("/predictor", methods=["GET", "POST"])
def predictor_page():
    athletes = load_athletes()
    names = sorted(athletes)
    event = request.values.get("event", "1500m")
    if event not in EVENTS:
        event = "1500m"
    selected = request.values.get("athlete", "")
    target_text = request.values.get(
        "target_date",
        (datetime.now(timezone.utc).date() + timedelta(days=14)).isoformat(),
    )
    manual_marks = [request.values.get(f"r{i}", "").strip() for i in range(1, 5)]
    forecast = None
    prediction_error = None

    if request.method == "POST":
        try:
            target = datetime.fromisoformat(target_text).date()
            records = _prediction_records(athletes)
            supplied_seconds = [time_to_seconds(mark) for mark in manual_marks]
            valid_seconds = [seconds for seconds in supplied_seconds if seconds is not None]
            if any(manual_marks) and len(valid_seconds) != 4:
                raise ValueError("Enter four valid race times or leave all four blank.")
            if len(valid_seconds) == 4:
                lower, upper = EVENT_BOUNDS[event]
                if any(not lower <= seconds <= upper for seconds in valid_seconds):
                    raise ValueError(f"Enter realistic {event} times within the supported range.")
                athlete_id = "manual-forecast"
                records.extend(
                    {
                        "athlete_id": athlete_id,
                        "event": event,
                        "date": (target - timedelta(days=35 - index * 7)).isoformat(),
                        "seconds": seconds,
                        "meet": f"Recent result {index}",
                    }
                    for index, seconds in enumerate(valid_seconds, start=1)
                )
            elif selected in athletes:
                athlete_id = selected
            else:
                raise ValueError("Select an athlete with history or enter four recent times.")
            forecast = predict_next_performance(
                records, athlete_id=athlete_id, event=event, cutoff=target
            )
        except (ValueError, InsufficientHistoryError) as exc:
            prediction_error = str(exc)

    return render_template(
        "index.html",
        page="predictor",
        total=len(athletes),
        names=names,
        selected=selected,
        event=event,
        target_date=target_text,
        manual_marks=manual_marks,
        forecast=forecast,
        prediction_error=prediction_error,
        benchmark=_load_predictor_benchmark(),
        events=EVENTS,
    )


@app.route("/athletes")
def athletes_page():
    athletes = load_athletes()
    cat_filter = request.args.get("cat", "")
    q = request.args.get("q", "").strip()
    sort_by = request.args.get("sort", "name")
    shown = apply_view(athletes, q, cat_filter, sort_by)
    return render_template(
        "index.html", page="athletes", athletes=shown, cat_filter=cat_filter,
        q=q, sort_by=sort_by, events=EVENTS)


@app.route("/compare")
def compare():
    athletes = load_athletes()
    cat_filter = request.args.get("cat", "")
    shown = filter_by_category(athletes, cat_filter)
    names = sorted(
        shown,
        key=lambda n: (n.strip().split()[-1].lower() if n.strip() else n.lower(), n.lower()),
    )
    a_name = request.args.get("a")
    b_name = request.args.get("b")
    event = request.args.get("event", "")
    comparison = None

    if a_name in athletes and b_name in athletes:
        a, b = athletes[a_name], athletes[b_name]
        head_to_head = compare_personal_bests(a.get("marks", {}), b.get("marks", {}))
        available_events = [row["event"] for row in head_to_head["events"]]

        form_comparisons = {
            ev: compare_recent_form(
                a.get("results", []), b.get("results", []), event=ev, limit=4
            )
            for ev in EVENTS
        }
        form_events = [
            ev
            for ev, form in form_comparisons.items()
            if form["a_sample_size"] and form["b_sample_size"]
        ]
        if not event:
            event = form_events[0] if form_events else (available_events[0] if available_events else "")
        if event not in EVENTS and event not in available_events:
            event = ""

        recent = form_comparisons.get(event) if event else None

        comparison = {
            "a_name": a_name,
            "b_name": b_name,
            "a": a,
            "b": b,
            "h2h": head_to_head,
            "scoreline": f"{_score_label(head_to_head['a_points'])}–{_score_label(head_to_head['b_points'])}",
            "available_events": available_events,
            "form_events": form_events,
            "event": event,
            "recent": recent,
        }

    return render_template(
        "index.html",
        page="compare",
        names=names,
        a_name=a_name,
        b_name=b_name,
        c=comparison,
        cat_filter=cat_filter,
        events=EVENTS,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=port)
