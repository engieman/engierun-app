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
  <title>EngieRun Compare</title>
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
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div class="eyebrow">Collegiate Track &amp; Field</div>
      <h1>EngieRun Compare</h1>
      <nav>
        <a href="{{ url_for('home') }}" class="{{ 'active' if page=='home' }}">Athletes</a>
        <a href="{{ url_for('compare') }}" class="{{ 'active' if page=='compare' }}">Compare</a>
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
        <p style="font-size:.75rem; color:#5b665e; margin-top:.5rem;">Or use "Add manually" to type in marks yourself. Category is auto-detected on import — fix it below if it's wrong.</p>
      </div>

      {% if import_failed %}
        <div class="msg">Couldn't read marks from that link. Make sure it's a full athlete URL (contains /athletes/), or use "Add manually".</div>
      {% endif %}

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
        <a href="{{ url_for('home', q=q, sort=sort_by) }}" class="{{ 'active' if not cat_filter }}">All</a>
        <a href="{{ url_for('home', cat='Male', q=q, sort=sort_by) }}" class="{{ 'active' if cat_filter=='Male' }}">Male</a>
        <a href="{{ url_for('home', cat='Female', q=q, sort=sort_by) }}" class="{{ 'active' if cat_filter=='Female' }}">Female</a>
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
        <p>No athletes yet. Import one above or add manually.</p>
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

    {% elif page == 'compare' %}
      <div class="filterbar">
        <a href="{{ url_for('compare') }}" class="{{ 'active' if not cat_filter }}">All</a>
        <a href="{{ url_for('compare', cat='Male') }}" class="{{ 'active' if cat_filter=='Male' }}">Male</a>
        <a href="{{ url_for('compare', cat='Female') }}" class="{{ 'active' if cat_filter=='Female' }}">Female</a>
      </div>
      <form method="get" style="display:flex; gap:1rem; flex-wrap:wrap; align-items:flex-end; margin-bottom:2rem;">
        <input type="hidden" name="cat" value="{{ cat_filter }}">
        <div class="field" style="margin-bottom:0; flex:1; min-width:180px;">
          <label>Athlete A</label>
          <div class="searchable" data-target="a">
            <input type="text" class="search-in" autocomplete="off" placeholder="Type to search..." value="{{ a_name or '' }}">
            <input type="hidden" name="a" class="hidden-val" value="{{ a_name or '' }}">
            <div class="options">
              {% for n in names %}<div class="opt" data-val="{{ n }}">{{ n }}</div>{% endfor %}
            </div>
          </div>
        </div>
        <div class="field" style="margin-bottom:0; flex:1; min-width:180px;">
          <label>Athlete B</label>
          <div class="searchable" data-target="b">
            <input type="text" class="search-in" autocomplete="off" placeholder="Type to search..." value="{{ b_name or '' }}">
            <input type="hidden" name="b" class="hidden-val" value="{{ b_name or '' }}">
            <div class="options">
              {% for n in names %}<div class="opt" data-val="{{ n }}">{{ n }}</div>{% endfor %}
            </div>
          </div>
        </div>
        <button class="btn" type="submit">Compare</button>
      </form>
      <script>
        document.querySelectorAll('.searchable').forEach(function(box){
          var input = box.querySelector('.search-in');
          var hidden = box.querySelector('.hidden-val');
          var opts = box.querySelectorAll('.opt');
          input.addEventListener('focus', function(){ box.classList.add('open'); });
          input.addEventListener('input', function(){
            var qq = input.value.toLowerCase();
            box.classList.add('open');
            hidden.value = input.value;
            opts.forEach(function(o){
              o.classList.toggle('hidden', o.textContent.toLowerCase().indexOf(qq) === -1);
            });
          });
          opts.forEach(function(o){
            o.addEventListener('click', function(){
              input.value = o.textContent;
              hidden.value = o.getAttribute('data-val');
              box.classList.remove('open');
            });
          });
          document.addEventListener('click', function(e){
            if(!box.contains(e.target)) box.classList.remove('open');
          });
        });
      </script>

      {% if c %}
        {% if c.labels %}
          <div class="card" style="margin-bottom:2rem;"><canvas id="radar" height="380"></canvas></div>
        {% else %}
          <div class="msg">These two athletes share no overlapping events, so there's nothing to chart.</div>
        {% endif %}
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:1rem;">
          <div class="card">
            <h2 style="font-size:1.25rem;"><span class="dot" style="background:var(--lane)"></span>{{ c.a_name }}</h2>
            <div class="school" style="margin-bottom:.4rem;">{{ c.a_school }}</div>
            {% if c.a_cat %}<span class="tag cat">{{ c.a_cat }}</span>{% endif %}
            {% if c.a_strength %}<span class="tag strong">Strength: {{ c.a_strength }}</span><span class="tag weak">Weakness: {{ c.a_weakness }}</span>{% endif %}
            <table style="margin-top:.6rem;">{% for ev, mk in c.a_marks.items() %}<tr><td>{{ ev }}</td><td style="text-align:right; font-weight:600;">{{ mk }}</td></tr>{% endfor %}</table>
          </div>
          <div class="card">
            <h2 style="font-size:1.25rem;"><span class="dot" style="background:var(--lane-b)"></span>{{ c.b_name }}</h2>
            <div class="school" style="margin-bottom:.4rem;">{{ c.b_school }}</div>
            {% if c.b_cat %}<span class="tag cat">{{ c.b_cat }}</span>{% endif %}
            {% if c.b_strength %}<span class="tag strong">Strength: {{ c.b_strength }}</span><span class="tag weak">Weakness: {{ c.b_weakness }}</span>{% endif %}
            <table style="margin-top:.6rem;">{% for ev, mk in c.b_marks.items() %}<tr><td>{{ ev }}</td><td style="text-align:right; font-weight:600;">{{ mk }}</td></tr>{% endfor %}</table>
          </div>
        </div>
        {% if c.labels %}
        <script>
          (function(){
            var labels = {{ c.labels | tojson }};
            var aData = {{ c.a_scores | tojson }};
            var bData = {{ c.b_scores | tojson }};
            var aName = {{ c.a_name | tojson }};
            var bName = {{ c.b_name | tojson }};
            var useRadar = labels.length >= 3;  // radar needs 3+ axes to form a shape
            var ds = [
              { label:aName, data:aData, borderColor:'#c8532a',
                backgroundColor: useRadar ? 'rgba(200,83,42,0.30)' : '#c8532a',
                pointBackgroundColor:'#c8532a', borderWidth:2 },
              { label:bName, data:bData, borderColor:'#2f6f6b',
                backgroundColor: useRadar ? 'rgba(47,111,107,0.30)' : '#2f6f6b',
                pointBackgroundColor:'#2f6f6b', borderWidth:2 }
            ];
            var opts;
            if (useRadar) {
              opts = { scales: { r: { min:40, max:100, ticks:{ stepSize:10 },
                pointLabels:{ font:{ size:14, weight:'700' } },
                grid:{ color:'#cfd3c7' }, angleLines:{ color:'#cfd3c7' } } },
                plugins: { legend:{ position:'top', labels:{ font:{ size:13 } } },
                  tooltip:{ callbacks:{ label: function(ctx){ return ctx.dataset.label+': '+ctx.raw; } } } } };
            } else {
              opts = { scales: { y: { min:40, max:100, ticks:{ stepSize:10 },
                grid:{ color:'#cfd3c7' } }, x: { grid:{ display:false },
                ticks:{ font:{ size:13, weight:'700' } } } },
                plugins: { legend:{ position:'top', labels:{ font:{ size:13 } } },
                  tooltip:{ callbacks:{ label: function(ctx){ return ctx.dataset.label+': '+ctx.raw; } } } } };
            }
            new Chart(document.getElementById('radar'), {
              type: useRadar ? 'radar' : 'bar',
              data: { labels: labels, datasets: ds },
              options: opts
            });
          })();
        </script>
        {% endif %}
      {% else %}
        <p>Select two athletes above to see their runner-type profiles compared.</p>
      {% endif %}
    {% endif %}
  </div>
</body>
</html>
"""


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


@app.route("/")
def home():
    athletes = load_athletes()
    cat_filter = request.args.get("cat", "")
    q = request.args.get("q", "").strip()
    sort_by = request.args.get("sort", "name")
    shown = apply_view(athletes, q, cat_filter, sort_by)
    return render_template_string(
        PAGE, page="home", athletes=shown, cat_filter=cat_filter,
        q=q, sort_by=sort_by, events=EVENTS,
        import_failed=request.args.get("failed") == "1")


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
            return redirect(url_for("home"))
    return render_template_string(PAGE, page="add", events=EVENTS, categories=CATEGORIES)


@app.route("/set_category/<name>/<cat>")
def set_category(name, cat):
    athletes = load_athletes()
    if name in athletes and cat in CATEGORIES:
        athletes[name]["category"] = cat
        save_athletes(athletes)
    return redirect(url_for("home"))


@app.route("/delete/<name>")
def delete(name):
    athletes = load_athletes()
    if name in athletes:
        del athletes[name]
        save_athletes(athletes)
    return redirect(url_for("home"))


@app.route("/compare")
def compare():
    athletes = load_athletes()
    cat_filter = request.args.get("cat", "")
    shown = filter_by_category(athletes, cat_filter)
    names = sorted(shown.keys(),
                   key=lambda n: (n.strip().split()[-1].lower() if n.strip() else n.lower(), n.lower()))
    a_name = request.args.get("a")
    b_name = request.args.get("b")
    comparison = None
    if a_name in athletes and b_name in athletes:
        try:
            a, b = athletes[a_name], athletes[b_name]
            labels, a_scores, b_scores = compare_axes(a["marks"], b["marks"])
            a_str, a_weak = label_strength_weakness(labels, a_scores)
            b_str, b_weak = label_strength_weakness(labels, b_scores)
            comparison = {
                "a_name": a_name, "b_name": b_name,
                "a_school": a["school"], "b_school": b["school"],
                "a_cat": a.get("category", ""), "b_cat": b.get("category", ""),
                "labels": labels, "a_scores": a_scores, "b_scores": b_scores,
                "a_strength": a_str, "a_weakness": a_weak,
                "b_strength": b_str, "b_weakness": b_weak,
                "a_marks": a["marks"], "b_marks": b["marks"],
            }
        except Exception as e:
            print("compare error:", e)
            comparison = {"a_name": a_name, "b_name": b_name,
                          "a_school": "", "b_school": "", "a_cat": "", "b_cat": "",
                          "labels": [], "a_scores": [], "b_scores": [],
                          "a_strength": None, "a_weakness": None,
                          "b_strength": None, "b_weakness": None,
                          "a_marks": athletes[a_name].get("marks", {}),
                          "b_marks": athletes[b_name].get("marks", {})}
    return render_template_string(PAGE, page="compare", names=names,
                                  a_name=a_name, b_name=b_name, c=comparison,
                                  cat_filter=cat_filter)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)