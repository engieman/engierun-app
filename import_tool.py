"""
import_tool.py — standalone TFRRS athlete scraper.

Grabs the same data the web app's "Paste a TFRRS link" box does
(name, school, category, marks) and writes it to a JSON file.
It does NOT touch your app's database — it just produces a data file
you can inspect or load later.

USAGE:
  Single athlete:
    python import_tool.py "https://www.tfrrs.org/athletes/1234/School/Name"

  Many athletes from a file (one URL per line, e.g. ivy_profiles.txt):
    python import_tool.py --file ivy_profiles.txt

  Choose the output file (default: scraped_athletes.json):
    python import_tool.py --file ivy_profiles.txt --out ivy_data.json

NOTES:
  - Be polite: there's a delay between requests. Don't point this at
    thousands of URLs — TFRRS will block you, and it's against their terms
    to bulk-copy their data.
  - Progress is saved as it goes, so if it stops partway you keep what you got
    and can re-run to resume (already-scraped athletes are skipped).
"""

import argparse
import json
import os
import re
import sys
import time
import traceback

from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as httpx
    IMPERSONATE = "chrome120"
    HAVE_CFFI = True
except Exception:
    import requests as httpx
    IMPERSONATE = None
    HAVE_CFFI = False

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}

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


def _get(url):
    kwargs = {"headers": HEADERS, "timeout": 20}
    if HAVE_CFFI:
        kwargs["impersonate"] = IMPERSONATE
    return httpx.get(url, **kwargs)


def match_event(text):
    for canon, pat in EVENT_PATTERNS:
        if re.search(pat, text, re.I):
            return canon
    return None


def clean_name(name):
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"\s*\(.*?\)\s*", "", name)
    return name.strip() or "Unknown"


def time_to_seconds(mark):
    if not mark:
        return None
    m = re.search(r"(?:(\d+):)?(\d+(?:\.\d+)?)", str(mark).strip())
    if not m:
        return None
    mins = int(m.group(1)) if m.group(1) else 0
    return mins * 60 + float(m.group(2))


def detect_category(page_text):
    t = (page_text or "").lower()
    if re.search(r"women'?s\b|\bwomen\b|\bfemale\b", t):
        return "Female"
    if re.search(r"men'?s\b|\bmen\b|\bmale\b", t):
        return "Male"
    return ""


def scrape_athlete(url):
    """Return {name, school, category, marks} or None on failure."""
    try:
        time.sleep(1.5)  # polite delay
        resp = _get(url)
        soup = BeautifulSoup(resp.text, "html.parser")

        name = "Unknown"
        if soup.title and soup.title.string:
            name = re.split(r"[|\-\u2013]", soup.title.string)[0].strip()
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
        # Fall back to the school embedded in the URL (…/athletes/ID/School/Name)
        if not school:
            um = re.search(r"/athletes/\d+/([^/]+)/", url)
            if um:
                school = um.group(1).replace("_", " ")
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
                mm = re.search(r"\d+:\d+(?:\.\d+)?|\d+\.\d+", mark)
                clean_mark = mm.group(0) if mm else mark
                secs = time_to_seconds(clean_mark)
                lo, hi = EVENT_BOUNDS.get(event, (0, 1e9))
                if secs and lo <= secs <= hi:
                    marks[event] = clean_mark

        return {"name": name, "school": school, "category": category, "marks": marks}
    except Exception as e:
        print("  ! fetch error:", e)
        traceback.print_exc()
        return None


def load_existing(out_path):
    if os.path.exists(out_path):
        try:
            with open(out_path) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save(out_path, data):
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)


def main():
    ap = argparse.ArgumentParser(description="Scrape TFRRS athletes to a JSON file.")
    ap.add_argument("url", nargs="?", help="a single TFRRS athlete URL")
    ap.add_argument("--file", help="a text file with one TFRRS URL per line")
    ap.add_argument("--out", default="scraped_athletes.json", help="output JSON file")
    args = ap.parse_args()

    if not args.url and not args.file:
        ap.print_help()
        sys.exit(1)

    urls = []
    if args.url:
        urls.append(args.url.strip())
    if args.file:
        with open(args.file) as f:
            urls.extend(line.strip() for line in f if line.strip())

    data = load_existing(args.out)
    print(f"Loaded {len(data)} already-scraped athletes from {args.out}")
    print(f"Scraping {len(urls)} URL(s)...\n")

    done = 0
    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {url}")
        result = scrape_athlete(url)
        if result and result["marks"]:
            data[result["name"]] = {"school": result["school"],
                                    "category": result["category"],
                                    "marks": result["marks"]}
            save(args.out, data)  # save after each success so progress isn't lost
            done += 1
            print(f"    ok: {result['name']} ({result['school']}) — "
                  f"{len(result['marks'])} marks, category={result['category'] or '?'}")
        else:
            print("    skipped (no marks found or fetch failed)")

    print(f"\nDone. {done} athletes scraped this run. Total in {args.out}: {len(data)}")
    print("This file did not touch your app's database — it's just data on disk.")


if __name__ == "__main__":
    main()