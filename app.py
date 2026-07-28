import json, os, re, time, traceback
from urllib.parse import quote, urlparse, parse_qs, unquote
from bs4 import BeautifulSoup
from flask import Flask, render_template_string, request, redirect, url_for

# curl_cffi impersonates a real browser's TLS fingerprint so protected sites
# don't block us at the handshake. Falls back to plain requests if unavailable.
try:
    from curl_cffi import requests as httpx
    IMPERSONATE = "chrome120"
    HAVE_CFFI = True
except Exception:
    import requests as httpx
    IMPERSONATE = None
    HAVE_CFFI = False

app = Flask(__name__)
DATA_FILE = "athletes.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}


def _get(url, method="get"):
    kwargs = {"headers": HEADERS, "timeout": 20}
    if HAVE_CFFI:
        kwargs["impersonate"] = IMPERSONATE
    return getattr(httpx, method)(url, **kwargs)


SAMPLE = {}

AXES = {
    "Short Speed (800/1500)": ["800m", "1000m", "1500m", "Mile"],
    "3k Speed-Endurance": ["1500m", "Mile", "3000m", "5000m"],
    "5k/10k Aerobic Engine": ["5000m", "10000m"],
}
EVENTS = ["800m", "1000m", "1500m", "Mile", "3000m", "5000m", "10000m"]
EVENT_METERS = {"800m": 800, "1000m": 1000, "1500m": 1500, "Mile": 1609,
                "3000m": 3000, "5000m": 5000, "10000m": 10000}
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
        if re.search(pat, text, re.I):
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

if DATABASE_URL:
    import psycopg2
    _DB = DATABASE_URL.replace("postgres://", "postgresql://", 1)

    def _db_conn():
        return psycopg2.connect(_DB)

    def _db_init():
        with _db_conn() as conn, conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS athletes (
                               name TEXT PRIMARY KEY,
                               school TEXT,
                               marks TEXT)""")
            # Add the category column if this is an older table missing it.
            cur.execute("""SELECT column_name FROM information_schema.columns
                           WHERE table_name='athletes' AND column_name='category'""")
            if not cur.fetchone():
                cur.execute("ALTER TABLE athletes ADD COLUMN category TEXT")
            conn.commit()

    def load_athletes():
        try:
            _db_init()
            with _db_conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT name, school, marks, category FROM athletes")
                rows = cur.fetchall()
            out = {}
            for name, school, marks, category in rows:
                try:
                    m = json.loads(marks) if marks else {}
                except Exception:
                    m = {}
                out[clean_name(name)] = {"school": school or "",
                                         "category": category or "",
                                         "marks": {k: str(v) for k, v in m.items()}}
            return out
        except Exception as e:
            print("db load error:", e)
            return {}

    def save_athletes(data):
        try:
            with _db_conn() as conn, conn.cursor() as cur:
                cur.execute("DELETE FROM athletes")
                for name, d in data.items():
                    cur.execute(
                        "INSERT INTO athletes (name, school, marks, category) VALUES (%s,%s,%s,%s)",
                        (name, d.get("school", ""), json.dumps(d.get("marks", {})),
                         d.get("category", "")))
                conn.commit()
        except Exception as e:
            print("db save error:", e)

else:
    def load_athletes():
        if not os.path.exists(DATA_FILE):
            with open(DATA_FILE, "w") as f:
                json.dump(SAMPLE, f, indent=2)
        try:
            with open(DATA_FILE) as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("athletes file is not a JSON object")
            clean = {}
            for name, d in data.items():
                if isinstance(d, dict) and isinstance(d.get("marks"), dict):
                    clean[clean_name(name)] = {"school": d.get("school", ""),
                                   "category": d.get("category", ""),
                                   "marks": {k: str(v) for k, v in d["marks"].items()}}
            return clean
        except Exception as e:
            print("athletes.json unreadable, backing up and reseeding:", e)
            try:
                os.replace(DATA_FILE, DATA_FILE + ".corrupt")
            except Exception:
                pass
            with open(DATA_FILE, "w") as f:
                json.dump(SAMPLE, f, indent=2)
            return dict(SAMPLE)

    def save_athletes(data):
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)


def time_to_seconds(mark):
    if not mark:
        return None
    m = re.search(r"(?:(\d+):)?(\d+(?:\.\d+)?)", str(mark).strip())
    if not m:
        return None
    mins = int(m.group(1)) if m.group(1) else 0
    return mins * 60 + float(m.group(2))


def seconds_to_time(sec):
    """Format seconds back into m:ss.xx (or ss.xx under a minute)."""
    if sec is None:
        return ""
    mins = int(sec // 60)
    s = sec - mins * 60
    return f"{mins}:{s:05.2f}" if mins else f"{s:.2f}"


def riegel_predict(t1_sec, d1_m, d2_m):
    """Riegel endurance formula: T2 = T1 * (D2/D1)^1.06."""
    if not t1_sec or not d1_m or not d2_m:
        return None
    return t1_sec * (d2_m / d1_m) ** 1.06


def predict_event(marks, target_event):
    """Predict a runner's time for target_event from their nearest existing PR
    (nearest by distance, which Riegel handles most accurately). Returns a
    formatted string or None if they have no marks to predict from."""
    if target_event in marks and time_to_seconds(marks[target_event]):
        return None  # they already have a real mark; no prediction needed
    td = EVENT_METERS.get(target_event)
    if not td:
        return None
    # find the runner's marks we can use, pick the closest distance
    candidates = []
    for ev, mk in marks.items():
        sec = time_to_seconds(mk)
        d = EVENT_METERS.get(ev)
        if sec and d:
            candidates.append((abs(d - td), d, sec))
    if not candidates:
        return None
    candidates.sort()
    _, d1, t1 = candidates[0]
    return seconds_to_time(riegel_predict(t1, d1, td))


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


def multi_compare(selected, floor=40):
    """selected: list of (name, marks). Returns (labels, {name: [scores]}).
    Each axis is anchored to the fastest athlete on it. Prefers per-event axes
    (shared events) since that reaches 3+ axes most often; falls back to
    runner-type groups only if per-event gives fewer axes."""
    def build(keys, getter):
        labs = []
        data = {n: [] for n, _ in selected}
        for key in keys:
            vals = {n: getter(m, key) for n, m in selected}
            if all(v is not None for v in vals.values()) and vals:
                best = min(vals.values())
                labs.append(key)
                for n in data:
                    data[n].append(round(floor + (best / vals[n]) ** 8 * (100 - floor), 1))
        return labs, data

    # Per-event: an axis per event that ALL selected athletes actually share.
    # This is the honest comparison — same event for everyone.
    ev_labels, ev_data = build(EVENTS, lambda m, k: time_to_seconds(m.get(k)))

    # Runner-type group axes average across events and can compare different
    # underlying events between runners, so only use them as a RICHER view when
    # the athletes already share enough real events (3+) to make a radar anyway.
    # When they share few events, always use the real per-event comparison.
    if len(ev_labels) >= 3:
        grp_labels, grp_data = build(list(AXES.keys()), lambda m, k: axis_seconds(m, AXES[k]))
        if len(grp_labels) > len(ev_labels):
            return grp_labels, grp_data
    return ev_labels, ev_data


def head_to_head(a_marks, b_marks, a_name, b_name):
    """Per-event winner table for exactly two athletes."""
    rows = []
    for ev in EVENTS:
        a, b = time_to_seconds(a_marks.get(ev)), time_to_seconds(b_marks.get(ev))
        if a and b:
            if a < b:
                winner, diff = a_name, b - a
            elif b < a:
                winner, diff = b_name, a - b
            else:
                winner, diff = "Tie", 0
            rows.append({"event": ev, "a_mark": a_marks.get(ev), "b_mark": b_marks.get(ev),
                         "winner": winner, "diff": round(diff, 2)})
    return rows


def fastest_per_event(selected):
    """For 3+ athletes: who is fastest in each event."""
    rows = []
    for ev in EVENTS:
        vals = [(n, time_to_seconds(m.get(ev)), m.get(ev)) for n, m in selected
                if time_to_seconds(m.get(ev))]
        if len(vals) >= 2:
            vals.sort(key=lambda x: x[1])
            rows.append({"event": ev, "winner": vals[0][0], "mark": vals[0][2]})
    return rows


def build_grid(selected, predict=False):
    """Full events x athletes grid: a row for every event ANY selected runner
    has, a cell per athlete. Each cell is {'mark': str, 'pred': bool}. When
    predict=True, blanks are filled with a Riegel estimate flagged pred=True."""
    used = [ev for ev in EVENTS if any(ev in m for _, m in selected)]
    rows = []
    for ev in used:
        cells = []
        for _, m in selected:
            real = m.get(ev, "")
            if real:
                cells.append({"mark": real, "pred": False})
            elif predict:
                p = predict_event(m, ev)
                cells.append({"mark": ("~" + p) if p else "", "pred": bool(p)})
            else:
                cells.append({"mark": "", "pred": False})
        rows.append({"event": ev, "cells": cells})
    return rows


def tfrrs_fetch_athlete(url):
    try:
        time.sleep(1)
        resp = _get(url)
        soup = BeautifulSoup(resp.text, "html.parser")
        name = "Unknown"
        if soup.title and soup.title.string:
            name = re.split(r"[|\-–]", soup.title.string)[0].strip()
        heading = soup.find(["h1", "h2", "h3"])
        if heading and heading.get_text(strip=True):
            name = heading.get_text(strip=True)
        name = clean_name(name)

        school = ""
        team_link = soup.find("a", href=re.compile(r"/teams/"))
        if team_link and team_link.get_text(strip=True):
            school = team_link.get_text(strip=True)
        elif soup.title and soup.title.string and "|" in soup.title.string:
            school = soup.title.string.split("|", 1)[1].strip()
        school = re.sub(r"\s+", " ", school).strip()

        category = detect_category(soup.get_text(" ", strip=True)[:4000])

        marks = {}
        for row in soup.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
            if not cells:
                continue
            event = match_event(cells[0]) or match_event(" ".join(cells))
            mark = next((c for c in cells[1:]
                         if re.search(r"\d+:\d|\d+\.\d", c) and time_to_seconds(c)), None)
            if event and mark and event not in marks:
                m = re.search(r"\d+:\d+(?:\.\d+)?|\d+\.\d+", mark)
                clean_mark = m.group(0) if m else mark
                secs = time_to_seconds(clean_mark)
                lo, hi = EVENT_BOUNDS.get(event, (0, 1e9))
                if secs and lo <= secs <= hi:
                    marks[event] = clean_mark
        return {"name": name, "school": school, "category": category, "marks": marks}
    except Exception as e:
        print("fetch error:", e)
        traceback.print_exc()
        return None


PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Engieneer</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root { --ink:#16211c; --paper:#eef0e9; --lane:#c8532a; --lane-b:#2f6f6b; --line:#cfd3c7; }
    * { box-sizing:border-box; margin:0; padding:0; }
    body { font-family:"Segoe UI",system-ui,sans-serif; background:var(--paper); color:var(--ink); line-height:1.5; padding:2rem 1.25rem 4rem; }
    .wrap { max-width:900px; margin:0 auto; }
    header { border-bottom:3px solid var(--ink); padding-bottom:.75rem; margin-bottom:2rem; }
    .eyebrow { font-size:.8rem; text-transform:uppercase; letter-spacing:.18em; color:#5b665e; }
    h1 { font-size:clamp(1.8rem,5vw,3rem); font-weight:800; letter-spacing:-0.03em; text-transform:uppercase; }
    nav { display:flex; gap:1.25rem; margin-top:.6rem; flex-wrap:wrap; }
    nav a { text-decoration:none; color:var(--ink); font-weight:700; font-size:.8rem; text-transform:uppercase; letter-spacing:.1em; border-bottom:2px solid transparent; padding-bottom:2px; }
    nav a:hover, nav a.active { border-bottom-color:var(--lane); }
    .btn { display:inline-block; padding:.55rem 1.4rem; background:var(--ink); color:var(--paper); border:none; text-decoration:none; font-weight:700; text-transform:uppercase; letter-spacing:.1em; cursor:pointer; font-size:.85rem; }
    .btn:hover { background:var(--lane); }
    .btn-ghost { background:transparent; color:var(--ink); border:2px solid var(--ink); }
    .btn-ghost:hover { background:var(--ink); color:var(--paper); }
    input, select { padding:.55rem; border:1px solid var(--ink); background:#fff; font-size:1rem; width:100%; }
    label { font-size:.7rem; text-transform:uppercase; letter-spacing:.12em; font-weight:700; display:block; margin-bottom:.3rem; }
    .field { margin-bottom:1rem; }
    .card { border:2px solid var(--ink); padding:1.1rem; background:#fff; }
    .tag { display:inline-block; font-size:.7rem; font-weight:700; text-transform:uppercase; letter-spacing:.08em; padding:.2rem .5rem; border-radius:3px; margin:.15rem .15rem 0 0; }
    .strong { background:#d8ecd3; color:#1f5c2e; }
    .weak { background:#f6dcd2; color:#8a3316; }
    .cat { background:#e4e9f5; color:#2f3f6b; }
    .msg { background:#fff5e6; border:1px solid #e0a94f; padding:.6rem .8rem; font-size:.8rem; margin-bottom:1rem; }
    .filterbar { display:flex; gap:.5rem; margin-bottom:1.5rem; flex-wrap:wrap; }
    .filterbar a { text-decoration:none; font-size:.75rem; font-weight:700; text-transform:uppercase; letter-spacing:.08em; padding:.35rem .8rem; border:2px solid var(--ink); color:var(--ink); }
    .filterbar a.active { background:var(--ink); color:var(--paper); }
    table { width:100%; border-collapse:collapse; font-size:.9rem; }
    td { padding:.3rem 0; border-bottom:1px solid var(--line); }
    .school { font-size:.75rem; text-transform:uppercase; letter-spacing:.1em; color:#5b665e; }
    .dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:.4rem; }
    .searchable { position:relative; }
    .searchable .options { position:absolute; z-index:10; left:0; right:0; background:#fff; border:1px solid var(--ink); border-top:none; max-height:220px; overflow-y:auto; display:none; }
    .searchable.open .options { display:block; }
    .searchable .opt { padding:.45rem .55rem; cursor:pointer; font-size:.9rem; border-bottom:1px solid var(--line); }
    .searchable .opt:hover { background:var(--paper); }
    .searchable .opt.hidden { display:none; }

    /* Inputs at 16px+ prevent iOS auto-zoom on focus */
    input, select { font-size:16px; }
    /* Comfortable tap targets */
    .btn { min-height:38px; }
    .filterbar a { min-height:34px; display:inline-flex; align-items:center; }

    @media (max-width: 640px) {
      body { padding:1.25rem .85rem 3rem; }
      header { margin-bottom:1.25rem; }
      nav { gap:.85rem; }
      nav a { font-size:.72rem; }
      h1 { font-size:2rem; }
      .card { padding:.9rem; }
      /* Cards stack to one column on phones */
      .wrap [style*="grid-template-columns:repeat(auto-fill"] { grid-template-columns:1fr !important; }
      .wrap [style*="grid-template-columns:1fr 1fr"] { grid-template-columns:1fr !important; }
      /* Compare pickers and forms stack instead of sitting in a tight row */
      #cmpform .picker-row { flex-wrap:wrap; }
      table { font-size:.85rem; }
      /* Let wide tables scroll rather than squish */
      .card { overflow-x:auto; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div class="eyebrow">Collegiate Track &amp; Field</div>
      <h1><span style="color:var(--lane);">Engie</span>neer</h1>
      <p style="font-size:.9rem; color:#5b665e; margin:.15rem 0 .1rem;">Build, compare, and break down runner profiles.</p>
      <nav>
        <a href="{{ url_for('home') }}" class="{{ 'active' if page=='home' }}">Home</a>
        <a href="{{ url_for('athletes_page') }}" class="{{ 'active' if page=='athletes' }}">Athletes</a>
        <a href="{{ url_for('compare') }}" class="{{ 'active' if page=='compare' }}">Compare</a>
        <a href="{{ url_for('predictor') }}" class="{{ 'active' if page=='predictor' }}">Predictor</a>
        <a href="{{ url_for('add') }}" class="{{ 'active' if page=='add' }}">Add manually</a>
      </nav>
    </header>

    {% if page == 'home' %}
      <div class="card" style="margin-bottom:1.5rem;">
        <label for="tfrrs_url">Paste a TFRRS profile link to import an athlete</label>
        <form method="get" action="{{ url_for('import_athlete') }}" style="display:flex; gap:.75rem;">
          <input type="text" id="tfrrs_url" name="url" placeholder="https://www.tfrrs.org/athletes/...">
          <button class="btn" type="submit">Import</button>
        </form>
        <p style="font-size:.75rem; color:#5b665e; margin-top:.5rem;">Or use "Add manually" to type in marks yourself.</p>
      </div>

      {% if import_failed %}
        <div class="msg">Couldn't read marks from that link. Make sure it's a full athlete URL (contains /athletes/), or use "Add manually".</div>
      {% endif %}

      <div class="card" style="text-align:center; padding:2rem 1.1rem;">
        <div style="font-size:2.5rem; font-weight:800;">{{ total }}</div>
        <div class="school" style="margin-bottom:1rem;">athletes in the database</div>
        <a class="btn" href="{{ url_for('athletes_page') }}">View all athletes &rarr;</a>
        <a class="btn btn-ghost" href="{{ url_for('compare') }}">Compare two &rarr;</a>
      </div>

    {% elif page == 'athletes' %}
      <form method="get" style="display:flex; gap:.75rem; margin-bottom:1rem; flex-wrap:wrap;">
        <input type="text" name="q" value="{{ q }}" placeholder="Search by name or school..." style="flex:2; min-width:200px;">
        <input type="hidden" name="cat" value="{{ cat_filter }}">
        <select name="sort" style="flex:1; min-width:160px;">
          <option value="name" {% if sort_by=='name' %}selected{% endif %}>Sort: Name</option>
          <option value="school" {% if sort_by=='school' %}selected{% endif %}>Sort: School</option>
          {% for ev in events %}<option value="event:{{ ev }}" {% if sort_by=='event:'+ev %}selected{% endif %}>Sort: {{ ev }} (fastest)</option>{% endfor %}
        </select>
        <button class="btn" type="submit">Go</button>
      </form>

      <div class="filterbar">
        <a href="{{ url_for('athletes_page', q=q, sort=sort_by) }}" class="{{ 'active' if not cat_filter }}">All</a>
        <a href="{{ url_for('athletes_page', cat='Male', q=q, sort=sort_by) }}" class="{{ 'active' if cat_filter=='Male' }}">Male</a>
        <a href="{{ url_for('athletes_page', cat='Female', q=q, sort=sort_by) }}" class="{{ 'active' if cat_filter=='Female' }}">Female</a>
        <a href="{{ url_for('athletes_page', cat='Unassigned', q=q, sort=sort_by) }}" class="{{ 'active' if cat_filter=='Unassigned' }}">Unassigned</a>
      </div>

      <p style="margin-bottom:1rem; font-size:.85rem; color:#5b665e;">{{ athletes|length }} athletes shown.</p>
      {% if athletes %}
        <div style="display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:1rem;">
          {% for name, d in athletes.items() %}
            <div class="card">
              <h2 style="font-size:1.15rem;">{{ name }}</h2>
              <div class="school" style="margin-bottom:.4rem;">{{ d.school }}</div>
              {% if d.category %}<span class="tag cat">{{ d.category }}</span>{% endif %}
              <table style="margin-top:.6rem;">{% for ev, mk in d.marks.items() %}<tr><td>{{ ev }}</td><td style="text-align:right; font-weight:600;">{{ mk }}</td></tr>{% endfor %}</table>
              <div style="margin-top:.8rem; display:flex; gap:.5rem; flex-wrap:wrap;">
                <a class="btn btn-ghost" style="padding:.3rem .8rem; font-size:.7rem;" href="{{ url_for('compare', a=name) }}">Compare</a>
                <a class="btn btn-ghost" style="padding:.3rem .8rem; font-size:.7rem;" href="{{ url_for('edit', name=name) }}">Edit</a>
                {% if not d.category %}
                <a class="btn btn-ghost" style="padding:.3rem .8rem; font-size:.7rem;" href="{{ url_for('set_category', name=name, cat='Male') }}">Set M</a>
                <a class="btn btn-ghost" style="padding:.3rem .8rem; font-size:.7rem;" href="{{ url_for('set_category', name=name, cat='Female') }}">Set F</a>
                {% endif %}
                <a class="btn btn-ghost" style="padding:.3rem .8rem; font-size:.7rem;" href="{{ url_for('delete', name=name) }}" onclick="return confirm('Remove {{ name }}?')">Delete</a>
              </div>
            </div>
          {% endfor %}
        </div>
      {% else %}
        <p>No athletes match. <a href="{{ url_for('athletes_page') }}" style="color:var(--lane);">Clear search</a> or add one.</p>
      {% endif %}

    {% elif page == 'add' %}
      <div class="card" style="max-width:520px;">
        <h2 style="margin-bottom:1rem;">Add an athlete</h2>
        <form method="post">
          <div class="field"><label for="name">Name</label><input type="text" id="name" name="name" required></div>
          <div class="field"><label for="school">School</label><input type="text" id="school" name="school"></div>
          <div class="field"><label for="category">Category</label>
            <select id="category" name="category">
              <option value="">— select —</option>
              {% for cval in categories %}<option value="{{ cval }}">{{ cval }}</option>{% endfor %}
            </select>
          </div>
          <p style="font-size:.75rem; color:#5b665e; margin-bottom:.8rem;">Enter marks as on TFRRS (e.g. 14:20.50). Leave blank to skip.</p>
          {% for ev in events %}
            <div class="field"><label for="{{ ev }}">{{ ev }}</label><input type="text" id="{{ ev }}" name="{{ ev }}" placeholder="mm:ss.xx"></div>
          {% endfor %}
          <button class="btn" type="submit">Save athlete</button>
          <a class="btn btn-ghost" href="{{ url_for('home') }}">Cancel</a>
        </form>
      </div>

    {% elif page == 'edit' %}
      <div class="card" style="max-width:520px;">
        <h2 style="margin-bottom:1rem;">Edit {{ orig_name }}</h2>
        <form method="post">
          <div class="field"><label for="name">Name</label><input type="text" id="name" name="name" value="{{ ath.name }}" required></div>
          <div class="field"><label for="school">School</label><input type="text" id="school" name="school" value="{{ ath.school }}"></div>
          <div class="field"><label for="category">Category</label>
            <select id="category" name="category">
              <option value="">— select —</option>
              {% for cval in categories %}<option value="{{ cval }}" {% if ath.category==cval %}selected{% endif %}>{{ cval }}</option>{% endfor %}
            </select>
          </div>
          <p style="font-size:.75rem; color:#5b665e; margin-bottom:.8rem;">Edit marks as needed. Clear a field to remove that mark.</p>
          {% for ev in events %}
            <div class="field"><label for="{{ ev }}">{{ ev }}</label><input type="text" id="{{ ev }}" name="{{ ev }}" value="{{ ath.marks.get(ev, '') }}" placeholder="mm:ss.xx"></div>
          {% endfor %}
          <button class="btn" type="submit">Save changes</button>
          <a class="btn btn-ghost" href="{{ url_for('athletes_page') }}">Cancel</a>
        </form>
      </div>

    {% elif page == 'predictor' %}
      <div class="card" style="max-width:520px; margin-bottom:1.5rem;">
        <h2 style="margin-bottom:.4rem;">Race time predictor</h2>
        <p style="font-size:.8rem; color:#5b665e; margin-bottom:1rem;">Enter one time and its event to estimate equivalent times at other distances. Uses the Riegel formula — these are estimates, most accurate for middle-distance to 10k, and a runner's real times depend on their strengths.</p>
        <form method="get" style="display:flex; gap:.75rem; flex-wrap:wrap; align-items:flex-end;">
          <div class="field" style="margin-bottom:0; flex:1; min-width:140px;">
            <label for="time">Time (mm:ss.xx)</label>
            <input type="text" id="time" name="time" value="{{ in_time or '' }}" placeholder="3:52.86" required>
          </div>
          <div class="field" style="margin-bottom:0; flex:1; min-width:140px;">
            <label for="event">Event</label>
            <select id="event" name="event">
              {% for ev in events %}<option value="{{ ev }}" {% if ev==in_event %}selected{% endif %}>{{ ev }}</option>{% endfor %}
            </select>
          </div>
          <button class="btn" type="submit">Predict</button>
        </form>
      </div>
      {% if predictions %}
        <div class="card">
          <h2 style="font-size:1rem; margin-bottom:.6rem;">Predicted equivalents from {{ in_time }} {{ in_event }}</h2>
          <table>
            <tr style="font-size:.7rem; text-transform:uppercase; letter-spacing:.06em; color:#5b665e;"><td>Event</td><td style="text-align:right;">Predicted</td></tr>
            {% for ev, pt in predictions %}
              <tr><td style="font-weight:700;">{{ ev }}</td><td style="text-align:right; {% if ev==in_event %}color:var(--lane); font-weight:700;{% endif %}">{{ pt }}{% if ev==in_event %} (entered){% endif %}</td></tr>
            {% endfor %}
          </table>
        </div>
      {% elif predict_error %}
        <div class="msg">{{ predict_error }}</div>
      {% endif %}

    {% elif page == 'compare' %}
      <div class="filterbar">
        <a href="{{ url_for('compare') }}" class="{{ 'active' if not cat_filter }}">All</a>
        <a href="{{ url_for('compare', cat='Male') }}" class="{{ 'active' if cat_filter=='Male' }}">Male</a>
        <a href="{{ url_for('compare', cat='Female') }}" class="{{ 'active' if cat_filter=='Female' }}">Female</a>
      </div>
      <form method="get" id="cmpform" style="margin-bottom:2rem;">
        <input type="hidden" name="cat" value="{{ cat_filter }}">
        <div id="picker-rows"></div>
        <div style="display:flex; gap:.75rem; margin-top:1rem; flex-wrap:wrap;">
          <button type="button" class="btn btn-ghost" id="add-athlete">+ Add athlete</button>
          <button class="btn" type="submit">Compare</button>
        </div>
      </form>
      <script>
        var ALL_NAMES = {{ names | tojson }};
        var PRESELECTED = {{ (selected_names or []) | tojson }};

        function makeRow(preval){
          var wrap = document.createElement('div');
          wrap.className = 'picker-row';
          wrap.style.cssText = 'display:flex; gap:.5rem; align-items:center; margin-bottom:.6rem;';

          var box = document.createElement('div');
          box.className = 'searchable';
          box.style.cssText = 'flex:1; min-width:200px;';
          var inp = document.createElement('input');
          inp.type='text'; inp.className='search-in'; inp.autocomplete='off';
          inp.placeholder='Type to search...'; inp.value = preval || '';
          var hid = document.createElement('input');
          hid.type='hidden'; hid.name='athlete'; hid.className='hidden-val'; hid.value = preval || '';
          var opts = document.createElement('div'); opts.className='options';
          ALL_NAMES.forEach(function(n){
            var o=document.createElement('div'); o.className='opt'; o.setAttribute('data-val',n); o.textContent=n;
            opts.appendChild(o);
          });
          box.appendChild(inp); box.appendChild(hid); box.appendChild(opts);

          var rm = document.createElement('button');
          rm.type='button'; rm.className='btn btn-ghost'; rm.textContent='×';
          rm.style.cssText='padding:.4rem .7rem; font-size:1rem;';
          rm.addEventListener('click', function(){
            if(document.querySelectorAll('.picker-row').length > 2){
              wrap.remove();
            } else {
              // At the two-row minimum: clear this picker instead of removing it.
              var inp = box.querySelector('.search-in');
              var hid = box.querySelector('.hidden-val');
              inp.value = ''; hid.value = '';
              box.querySelectorAll('.opt').forEach(function(o){ o.classList.remove('hidden'); });
              inp.focus();
            }
          });

          wrap.appendChild(box); wrap.appendChild(rm);
          wireSearchable(box);
          return wrap;
        }

        function wireSearchable(box){
          var input = box.querySelector('.search-in');
          var hidden = box.querySelector('.hidden-val');
          var opts = box.querySelectorAll('.opt');
          input.addEventListener('focus', function(){ box.classList.add('open'); });
          input.addEventListener('input', function(){
            var qq = input.value.toLowerCase();
            box.classList.add('open'); hidden.value = input.value;
            opts.forEach(function(o){ o.classList.toggle('hidden', o.textContent.toLowerCase().indexOf(qq)===-1); });
          });
          opts.forEach(function(o){
            o.addEventListener('click', function(){
              input.value=o.textContent; hidden.value=o.getAttribute('data-val'); box.classList.remove('open');
            });
          });
          document.addEventListener('click', function(e){ if(!box.contains(e.target)) box.classList.remove('open'); });
        }

        var rows = document.getElementById('picker-rows');
        var start = PRESELECTED.length >= 2 ? PRESELECTED : [PRESELECTED[0]||'', PRESELECTED[1]||''];
        start.forEach(function(v){ rows.appendChild(makeRow(v)); });
        document.getElementById('add-athlete').addEventListener('click', function(){
          rows.appendChild(makeRow(''));
        });
      </script>

      {% if c %}
        {% if c.labels and c.labels|length >= 3 %}
          <div class="card" style="margin-bottom:1.5rem;"><canvas id="radar" height="380"></canvas></div>
        {% elif c.labels %}
          <div class="card" style="margin-bottom:1.5rem;">
            <p style="font-size:.8rem; color:#5b665e; margin-bottom:1rem;">These athletes share only {{ c.labels|length }} event(s) — not enough for a radar, so here's an event-by-event view.</p>
            <div id="gauges" style="display:flex; gap:2rem; flex-wrap:wrap; justify-content:center;"></div>
          </div>
        {% else %}
          <div class="msg">These athletes don't share any events, so there's nothing to chart. Their marks are listed below.</div>
        {% endif %}

        {% if c.summary %}
          <div class="card" style="margin-bottom:1.5rem;">
            <h2 style="font-size:1rem; margin-bottom:.6rem;">
              {% if c.summary_kind == 'h2h' %}Who wins each event{% else %}Fastest in each event{% endif %}
            </h2>
            <table>
              {% if c.summary_kind == 'h2h' %}
                <tr style="font-size:.7rem; text-transform:uppercase; letter-spacing:.06em; color:#5b665e;">
                  <td>Event</td><td>{{ c.series[0].name }}</td><td>{{ c.series[1].name }}</td><td style="text-align:right;">Winner (gap)</td>
                </tr>
                {% for r in c.summary %}
                  <tr>
                    <td style="font-weight:700;">{{ r.event }}</td>
                    <td>{{ r.a_mark }}</td>
                    <td>{{ r.b_mark }}</td>
                    <td style="text-align:right;">{% if r.winner=='Tie' %}Tie{% else %}<b>{{ r.winner }}</b> by {{ r.diff }}s{% endif %}</td>
                  </tr>
                {% endfor %}
              {% else %}
                <tr style="font-size:.7rem; text-transform:uppercase; letter-spacing:.06em; color:#5b665e;">
                  <td>Event</td><td>Fastest</td><td style="text-align:right;">Mark</td>
                </tr>
                {% for r in c.summary %}
                  <tr><td style="font-weight:700;">{{ r.event }}</td><td><b>{{ r.winner }}</b></td><td style="text-align:right;">{{ r.mark }}</td></tr>
                {% endfor %}
              {% endif %}
            </table>
          </div>
        {% endif %}

        {% if c.grid %}
          <div class="card" style="margin-bottom:1.5rem; overflow-x:auto;">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:.5rem; margin-bottom:.6rem;">
              <h2 style="font-size:1rem;">All events side by side</h2>
              {% if predict_on %}
                <a class="btn btn-ghost" style="padding:.3rem .7rem; font-size:.7rem;" href="{{ url_for('compare', athlete=selected_names) }}">Hide predicted</a>
              {% else %}
                <a class="btn btn-ghost" style="padding:.3rem .7rem; font-size:.7rem;" href="{{ url_for('compare', athlete=selected_names, predict='1') }}">Fill blanks with predictions</a>
              {% endif %}
            </div>
            {% if predict_on %}<p style="font-size:.72rem; color:#5b665e; margin-bottom:.6rem;">Predicted times (shown with ~, in italic) are Riegel estimates from each runner's other PRs — not real marks.</p>{% endif %}
            <table>
              <tr style="font-size:.7rem; text-transform:uppercase; letter-spacing:.06em; color:#5b665e;">
                <td>Event</td>
                {% for s in c.series %}<td style="color:{{ s.color }}; font-weight:700;">{{ s.name }}</td>{% endfor %}
              </tr>
              {% for row in c.grid %}
                <tr>
                  <td style="font-weight:700;">{{ row.event }}</td>
                  {% for cell in row.cells %}
                    <td {% if cell.pred %}style="font-style:italic; color:#8a8f86;"{% endif %}>{{ cell.mark if cell.mark else '—' }}</td>
                  {% endfor %}
                </tr>
              {% endfor %}
            </table>
          </div>
        {% endif %}

        <div style="display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:1rem;">
          {% for s in c.series %}
            <div class="card">
              <h2 style="font-size:1.2rem;"><span class="dot" style="background:{{ s.color }}"></span>{{ s.name }}</h2>
              <div class="school" style="margin-bottom:.4rem;">{{ s.school }}</div>
              {% if s.category %}<span class="tag cat">{{ s.category }}</span>{% endif %}
              <table style="margin-top:.6rem;">{% for ev, mk in s.marks.items() %}<tr><td>{{ ev }}</td><td style="text-align:right; font-weight:600;">{{ mk }}</td></tr>{% endfor %}</table>
            </div>
          {% endfor %}
        </div>

        {% if c.labels %}
        <script>
          (function(){
            var labels = {{ c.labels | tojson }};
            var series = {{ c.series | tojson }};
            function hexToRgba(h, a){
              var n = parseInt(h.slice(1),16);
              return 'rgba('+((n>>16)&255)+','+((n>>8)&255)+','+(n&255)+','+a+')';
            }

            if (labels.length >= 3) {
              // RADAR
              var ds = series.map(function(s){
                return { label:s.name, data:s.scores, borderColor:s.color,
                  backgroundColor: hexToRgba(s.color,0.20),
                  pointBackgroundColor:s.color, borderWidth:2 };
              });
              new Chart(document.getElementById('radar'), {
                type: 'radar',
                data: { labels: labels, datasets: ds },
                options: { scales:{ r:{ min:40, max:100, ticks:{ stepSize:10 },
                  pointLabels:{ font:{ size:14, weight:'700' } },
                  grid:{ color:'#cfd3c7' }, angleLines:{ color:'#cfd3c7' } } },
                  plugins:{ legend:{ position:'top', labels:{ font:{ size:13 } } },
                    tooltip:{ callbacks:{ label:function(ctx){ return ctx.dataset.label+': '+ctx.raw; } } } } }
              });
            } else {
              // GAUGES: one dial per shared event; each athlete an arc on it.
              var host = document.getElementById('gauges');
              function polar(cx, cy, r, deg){
                var a = (deg-180) * Math.PI/180;
                return [cx + r*Math.cos(a), cy + r*Math.sin(a)];
              }
              function arcPath(cx, cy, r, startDeg, endDeg){
                var s = polar(cx,cy,r,startDeg), e = polar(cx,cy,r,endDeg);
                var large = (endDeg-startDeg) > 180 ? 1 : 0;
                return 'M '+s[0]+' '+s[1]+' A '+r+' '+r+' 0 '+large+' 1 '+e[0]+' '+e[1];
              }
              labels.forEach(function(evt, idx){
                var wrap = document.createElement('div');
                wrap.style.cssText = 'text-align:center;';
                var W=180, H=130, cx=90, cy=110, r=70;
                var svg = '<svg viewBox="0 0 '+W+' '+H+'" width="200">';
                // background track (semicircle 0..180)
                svg += '<path d="'+arcPath(cx,cy,r,0,180)+'" fill="none" stroke="#cfd3c7" stroke-width="12" stroke-linecap="round"/>';
                // each athlete's arc: score 40..100 maps to 0..180 degrees
                series.forEach(function(s, si){
                  var val = s.scores[idx];
                  var frac = Math.max(0, Math.min(1, (val-40)/60));
                  var deg = frac*180;
                  var rr = r - si*10;  // nest arcs so multiple athletes don't overlap
                  if (deg > 0.5){
                    svg += '<path d="'+arcPath(cx,cy,rr,0,deg)+'" fill="none" stroke="'+s.color+'" stroke-width="7" stroke-linecap="round"/>';
                  }
                });
                svg += '</svg>';
                wrap.innerHTML = svg +
                  '<div style="font-weight:700; font-size:.9rem; margin-top:.2rem;">'+evt+'</div>';
                // legend of values
                var vals = series.map(function(s){
                  return '<span style="color:'+s.color+'; font-weight:700;">'+s.name+': '+s.scores[idx]+'</span>';
                }).join(' &middot; ');
                wrap.innerHTML += '<div style="font-size:.75rem; margin-top:.2rem;">'+vals+'</div>';
                host.appendChild(wrap);
              });
            }
          })();
        </script>
        {% endif %}
      {% else %}
        <p>Pick two or more athletes above, then click Compare. Use "+ Add athlete" to compare a whole group.</p>
      {% endif %}
    {% endif %}
  </div>
</body>
</html>
"""


def filter_by_category(athletes, cat):
    if not cat:
        return athletes
    if cat == "Unassigned":
        return {n: d for n, d in athletes.items() if not d.get("category", "")}
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


@app.route("/")
def home():
    athletes = load_athletes()
    return render_template_string(
        PAGE, page="home", total=len(athletes),
        import_failed=request.args.get("failed") == "1")


@app.route("/athletes")
def athletes_page():
    athletes = load_athletes()
    cat_filter = request.args.get("cat", "")
    q = request.args.get("q", "").strip()
    sort_by = request.args.get("sort", "name")
    shown = apply_view(athletes, q, cat_filter, sort_by)
    return render_template_string(
        PAGE, page="athletes", athletes=shown, cat_filter=cat_filter,
        q=q, sort_by=sort_by, events=EVENTS)


@app.route("/import")
def import_athlete():
    url = request.args.get("url", "").strip()
    if url and "tfrrs.org" in url:
        data = tfrrs_fetch_athlete(url)
        if data and data["marks"]:
            athletes = load_athletes()
            athletes[data["name"]] = {"school": data["school"],
                                      "category": data.get("category", ""),
                                      "marks": data["marks"]}
            save_athletes(athletes)
            return redirect(url_for("home"))
    return redirect(url_for("home", failed="1"))


@app.route("/add", methods=["GET", "POST"])
def add():
    if request.method == "POST":
        name = clean_name(request.form.get("name", "").strip())
        school = request.form.get("school", "").strip()
        category = request.form.get("category", "").strip()
        marks = {ev: request.form.get(ev, "").strip()
                 for ev in EVENTS if request.form.get(ev, "").strip()}
        if name and marks:
            athletes = load_athletes()
            athletes[name] = {"school": school, "category": category, "marks": marks}
            save_athletes(athletes)
            return redirect(url_for("athletes_page"))
    return render_template_string(PAGE, page="add", events=EVENTS, categories=CATEGORIES)


@app.route("/edit/<name>", methods=["GET", "POST"])
def edit(name):
    athletes = load_athletes()
    if name not in athletes:
        return redirect(url_for("athletes_page"))
    if request.method == "POST":
        new_name = clean_name(request.form.get("name", "").strip())
        school = request.form.get("school", "").strip()
        category = request.form.get("category", "").strip()
        marks = {ev: request.form.get(ev, "").strip()
                 for ev in EVENTS if request.form.get(ev, "").strip()}
        if new_name and marks:
            # If the name changed, remove the old entry (this is a rename).
            if new_name != name and name in athletes:
                del athletes[name]
            athletes[new_name] = {"school": school, "category": category, "marks": marks}
            save_athletes(athletes)
            return redirect(url_for("athletes_page"))
    a = athletes[name]
    ath = {"name": name, "school": a.get("school", ""),
           "category": a.get("category", ""), "marks": a.get("marks", {})}
    return render_template_string(PAGE, page="edit", ath=ath, orig_name=name,
                                  events=EVENTS, categories=CATEGORIES)


@app.route("/set_category/<name>/<cat>")
def set_category(name, cat):
    athletes = load_athletes()
    if name in athletes and cat in CATEGORIES:
        athletes[name]["category"] = cat
        save_athletes(athletes)
    return redirect(url_for("athletes_page"))


@app.route("/delete/<name>")
def delete(name):
    athletes = load_athletes()
    if name in athletes:
        del athletes[name]
        save_athletes(athletes)
    return redirect(url_for("athletes_page"))


@app.route("/predictor")
def predictor():
    in_time = request.args.get("time", "").strip()
    in_event = request.args.get("event", "1500m")
    predictions = None
    predict_error = None
    if in_time:
        t1 = time_to_seconds(in_time)
        d1 = EVENT_METERS.get(in_event)
        if not t1 or not d1:
            predict_error = "Couldn't read that time. Use a format like 3:52.86 or 14:20.50."
        else:
            predictions = []
            for ev in EVENTS:
                d2 = EVENT_METERS[ev]
                if ev == in_event:
                    predictions.append((ev, in_time))
                else:
                    predictions.append((ev, seconds_to_time(riegel_predict(t1, d1, d2))))
    return render_template_string(PAGE, page="predictor", events=EVENTS,
                                  in_time=in_time, in_event=in_event,
                                  predictions=predictions, predict_error=predict_error)


@app.route("/compare")
def compare():
    athletes = load_athletes()
    cat_filter = request.args.get("cat", "")
    shown = filter_by_category(athletes, cat_filter)
    names = sorted(shown.keys(),
                   key=lambda n: (n.strip().split()[-1].lower() if n.strip() else n.lower(), n.lower()))

    # Collect any number of selected athletes from repeated ?athlete= params.
    selected_names = [n for n in request.args.getlist("athlete") if n in athletes]
    # Back-compat: also accept old ?a= / ?b= links.
    for k in ("a", "b"):
        v = request.args.get(k)
        if v and v in athletes and v not in selected_names:
            selected_names.append(v)

    comparison = None
    predict_on = request.args.get("predict") == "1"
    if len(selected_names) >= 2:
        try:
            selected = [(n, athletes[n]["marks"]) for n in selected_names]
            labels, data = multi_compare(selected)
            # colors cycle for each athlete
            palette = ["#c8532a", "#2f6f6b", "#c99a2e", "#4b6cb7", "#8a3b8f", "#3f8c4f"]
            series = []
            for i, n in enumerate(selected_names):
                col = palette[i % len(palette)]
                series.append({"name": n, "color": col, "scores": data.get(n, []),
                               "school": athletes[n].get("school", ""),
                               "category": athletes[n].get("category", ""),
                               "marks": athletes[n]["marks"]})
            # summaries
            if len(selected_names) == 2:
                summary = head_to_head(athletes[selected_names[0]]["marks"],
                                       athletes[selected_names[1]]["marks"],
                                       selected_names[0], selected_names[1])
                summary_kind = "h2h"
            else:
                summary = fastest_per_event(selected)
                summary_kind = "fastest"
            comparison = {"labels": labels, "series": series,
                          "summary": summary, "summary_kind": summary_kind,
                          "grid": build_grid(selected, predict=predict_on)}
        except Exception as e:
            print("compare error:", e)
            comparison = None

    return render_template_string(PAGE, page="compare", names=names,
                                  selected_names=selected_names, c=comparison,
                                  cat_filter=cat_filter, predict_on=predict_on)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)