"""Pure parsers for TFRRS HTML pages."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

_PROFILE_ID_RE = re.compile(r"/athletes/(\d+)(?:/|$)")
_STATUS_MARKS = {"DNF", "DNS", "DQ", "FS", "NT", "NH", "NM", "FOUL"}
_EVENT_ALIASES = {
    "MILE": "Mile",
    "8K (XC)": "8K XC",
}
_TIMED_EVENT_RE = re.compile(
    r"^(?:\d+(?:\.\d+)?m|\d+[kK](?: XC)?|Mile|\d+x\d+|DMR|SMR)$"
)


def _text(node: Any) -> str:
    return " ".join(node.get_text(" ", strip=True).split())


def _normalize_event(raw_event: str, *, cross_country: bool = False) -> str:
    event = " ".join(raw_event.split())
    upper = event.upper()
    if upper in _EVENT_ALIASES:
        return _EVENT_ALIASES[upper]
    meters = re.fullmatch(
        r"(\d+(?:\.\d+)?)\s*(?:M|METERS?)?", event, re.IGNORECASE
    )
    if meters:
        return f"{meters.group(1)}m"
    if re.fullmatch(r"\d+[kK]", event):
        distance = event.upper()
        return f"{distance} XC" if cross_country else distance
    if upper == "MILE":
        return "Mile"
    return event


def is_timed_event(event: str) -> bool:
    """Return whether normalized TFRRS event marks must parse as elapsed time."""
    return _TIMED_EVENT_RE.fullmatch(event) is not None


def parse_timed_mark_seconds(mark: str, event: str) -> float | None:
    """Parse a timed performance mark into seconds; field/status marks return None."""
    value = mark.strip()
    if not value or value.upper() in _STATUS_MARKS or not is_timed_event(event):
        return None

    # Ignore wind or other annotations after the leading performance.
    value = value.split()[0]
    try:
        parts = value.split(":")
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        return None
    return None


def _date_from_display(raw_date: str) -> str:
    """Return the final day represented by a TFRRS date or date range."""
    display = " ".join(raw_date.replace("\xa0", " ").split())
    year_match = re.search(r",\s*(\d{4})\s*$", display)
    if not year_match:
        raise ValueError(f"Unrecognized TFRRS date: {raw_date!r}")
    year = year_match.group(1)
    without_year = display[: year_match.start()]

    # Same-month range: Jan 24-25. Cross-month range: Apr 30-May 1.
    cross_month = re.fullmatch(
        r"([A-Za-z]{3,9})\s+\d+\s*-\s*([A-Za-z]{3,9})\s+(\d+)",
        without_year,
    )
    if cross_month:
        month, day = cross_month.group(2), cross_month.group(3)
    else:
        same_month = re.fullmatch(
            r"([A-Za-z]{3,9})\s+(?:\d+\s*-\s*)?(\d+)", without_year
        )
        if not same_month:
            raise ValueError(f"Unrecognized TFRRS date: {raw_date!r}")
        month, day = same_month.groups()

    for month_format in ("%b", "%B"):
        try:
            parsed = datetime.strptime(
                f"{month} {day}, {year}", f"{month_format} %d, %Y"
            ).replace(tzinfo=timezone.utc)
            return parsed.date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"Unrecognized TFRRS date: {raw_date!r}")


def validate_profile_url(url: str) -> str:
    """Validate an HTTPS TFRRS athlete URL before any caller performs I/O."""
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"Invalid TFRRS athlete profile URL: {url!r}") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"tfrrs.org", "www.tfrrs.org"}
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(
            r"/athletes/\d+/[A-Za-z0-9._~'-]+/[A-Za-z0-9._~'-]+\.html",
            parsed.path,
        )
    ):
        raise ValueError(f"Invalid TFRRS athlete profile URL: {url!r}")
    return url


def parse_team_roster(
    html: str, *, team_url: str, school: str, gender: str
) -> list[dict[str, str]]:
    """Parse only the current ROSTER table from a TFRRS team-page export."""
    soup = BeautifulSoup(html, "html.parser")
    roster_heading = next(
        (
            heading
            for heading in soup.find_all(["h2", "h3", "h4"])
            if _text(heading).upper() == "ROSTER"
        ),
        None,
    )
    if roster_heading is None:
        raise ValueError("TFRRS team page is missing a ROSTER heading")
    table = roster_heading.find_next("table")
    if table is None:
        raise ValueError("TFRRS team page is missing a roster table")

    roster: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for row in table.select("tr"):
        cells = row.select("td")
        if len(cells) < 2:
            continue
        link = cells[0].find("a", href=True)
        if link is None:
            continue
        href = link.get("href")
        if not isinstance(href, str):
            continue
        profile_url = validate_profile_url(urljoin(team_url, href))
        id_match = _PROFILE_ID_RE.search(urlparse(profile_url).path)
        if id_match is None or id_match.group(1) in seen_ids:
            continue
        seen_ids.add(id_match.group(1))
        raw_name = _text(link)
        if "," in raw_name:
            last, first = (part.strip() for part in raw_name.split(",", 1))
            name = f"{first} {last}".title()
        else:
            name = raw_name.title()
        roster.append(
            {
                "tfrrs_id": id_match.group(1),
                "name": name,
                "year": _text(cells[1]),
                "school": school,
                "gender": gender,
                "profile_url": profile_url,
            }
        )
    return roster


def parse_athlete_profile(
    html: str, *, profile_url: str, gender: str
) -> dict[str, Any]:
    """Parse one TFRRS athlete profile without performing network access."""
    validate_profile_url(profile_url)
    soup = BeautifulSoup(html, "html.parser")

    id_match = _PROFILE_ID_RE.search(urlparse(profile_url).path)
    if not id_match:
        raise ValueError(f"Invalid TFRRS athlete profile URL: {profile_url!r}")

    identity = soup.select_one("h3.panel-title.large-title")
    if identity is None:
        raise ValueError("TFRRS athlete profile is missing an identity heading")
    identity_text = _text(identity)
    identity_match = re.fullmatch(r"(.+?)\s*\(([^()]+)\)\s*", identity_text)
    if not identity_match:
        raise ValueError(f"Malformed TFRRS athlete identity: {identity_text!r}")
    raw_name, year = identity_match.groups()
    name = raw_name.title()

    school_node = soup.select_one('a[href*="/teams/tf/"] h3.panel-title')
    school = _text(school_node).title() if school_node else None

    bests: dict[str, dict[str, Any]] = {}
    bests_table = soup.select_one("table#all_bests")
    if bests_table:
        for row in bests_table.select("tr"):
            cells = row.select("td")
            for index in range(0, len(cells) - 1, 2):
                event_raw = _text(cells[index])
                mark = _text(cells[index + 1])
                if not event_raw or not mark:
                    continue
                event = _normalize_event(
                    event_raw, cross_country="(XC)" in event_raw.upper()
                )
                bests[event] = {"mark": mark, "seconds": parse_timed_mark_seconds(mark, event)}

    results: list[dict[str, Any]] = []
    result_root = soup.select_one("#meet-results") or soup
    for table in result_root.select("table.table-hover"):
        header = table.select_one("thead th")
        meet_node = header.select_one("a") if header else None
        date_node = header.select_one("span") if header else None
        if not meet_node or not date_node:
            continue
        try:
            date = _date_from_display(_text(date_node))
        except ValueError:
            continue
        cross_country = "xc" in (table.get("class") or [])
        for row in table.select("tr"):
            if row.find_parent("thead") is not None:
                continue
            cells = row.select("td")
            if len(cells) < 2:
                continue
            event = _normalize_event(_text(cells[0]), cross_country=cross_country)
            mark = _text(cells[1])
            if not event or not mark:
                continue
            status = mark.upper() if mark.upper() in _STATUS_MARKS else None
            results.append(
                {
                    "date": date,
                    "meet": _text(meet_node),
                    "event": event,
                    "mark": mark,
                    "seconds": parse_timed_mark_seconds(mark, event),
                    "status": status,
                }
            )

    results.sort(key=lambda result: result["date"])
    return {
        "tfrrs_id": id_match.group(1),
        "name": name,
        "year": year,
        "school": school,
        "gender": gender,
        "profile_url": profile_url,
        "bests": bests,
        "results": results,
    }
