from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime

import requests

from src.models import AvailabilityResult, Showtime, WatchRule

BASE_URL = "https://www.district.in/movies"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}


@dataclass
class CinemaDay:
    """One fetch of a District cinema page: the bookable dates plus the sessions for one of them."""

    known_dates: list[date]
    blocks: list[dict] = field(default_factory=list)


# Per-process cache so several rules watching the same cinema share one request per date.
_CACHE: dict[tuple[str, str | None], CinemaDay] = {}


def clear_cache() -> None:
    _CACHE.clear()


def _district_url(rule: WatchRule) -> str:
    slug = rule.cinema.district_slug
    if slug:
        if slug.startswith("http"):
            return slug
        return f"{BASE_URL}/{slug}"
    cinema_id = rule.cinema.district_cinema_id
    if cinema_id:
        return f"{BASE_URL}/cinema-{cinema_id}"
    raise ValueError(f"Rule '{rule.id}' is missing district cinema slug or id")


def _parse_next_data(html: str) -> dict:
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
    if not match:
        raise RuntimeError("District page did not contain embedded showtime data (possibly blocked)")
    return json.loads(match.group(1))


def _extract_cinema_sessions(payload: dict, cinema_id: str) -> dict:
    page_props = payload.get("props", {}).get("pageProps", {})
    initial_state = page_props.get("initialState", {})
    cinema_sessions = initial_state.get("movies", {}).get("cinemaSessions", {})

    if cinema_id in cinema_sessions:
        return cinema_sessions[cinema_id]

    if len(cinema_sessions) == 1:
        return next(iter(cinema_sessions.values()))

    raise RuntimeError(f"District cinema sessions not found for id {cinema_id}")


def fetch_cinema_day(rule: WatchRule, day: date | None = None) -> CinemaDay:
    """Fetch the cinema page. With no day, District shows its first bookable date (usually today)."""
    url = _district_url(rule)
    cinema_id = rule.cinema.district_cinema_id or ""
    key = (url, day.isoformat() if day else None)
    if key in _CACHE:
        return _CACHE[key]

    params = {"fromdate": day.isoformat()} if day else None
    response = requests.get(url, params=params, headers=HEADERS, timeout=25)
    response.raise_for_status()
    cinema_payload = _extract_cinema_sessions(_parse_next_data(response.text), cinema_id)
    raw_dates = cinema_payload.get("data", {}).get("sessionDates", [])
    result = CinemaDay(
        known_dates=[date.fromisoformat(value) for value in raw_dates],
        blocks=cinema_payload.get("arrangedSessions", []) or [],
    )
    _CACHE[key] = result
    return result


def showtimes_for_movie(blocks: list[dict], rule: WatchRule, target_date: date) -> list[Showtime]:
    showtimes: list[Showtime] = []
    target_prefix = target_date.isoformat()

    for block in blocks:
        label = block.get("data", {}).get("label") or block.get("entityName") or ""
        if not rule.title_matches(label):
            continue

        for session in block.get("sessions", []):
            show_time = session.get("showTime") or session.get("show_time")
            if not show_time or not str(show_time).startswith(target_prefix):
                continue

            parsed = datetime.fromisoformat(str(show_time))
            seats = None
            if session.get("avail") is not None and session.get("total"):
                seats = f"{session['avail']}/{session['total']} seats left"
            showtimes.append(
                Showtime(
                    time=parsed.strftime("%I:%M %p").lstrip("0"),
                    screen=session.get("audi"),
                    format=session.get("scrnFmt") or session.get("premiumLabel"),
                    seats=seats,
                    sort_key=parsed.isoformat(),
                )
            )

    showtimes.sort(key=lambda item: item.sort_key or item.time)
    return showtimes


def find_listings(rule: WatchRule, skip_dates: set[date]) -> dict[date, list[Showtime]]:
    """Return {date: showtimes} for every bookable date on which the rule's movie is listed.

    Dates in skip_dates (already alerted), dates before rule.from_date and, for rules with a
    target_date, every other date are not fetched.
    Raises on network/parse errors so the caller can track consecutive failures.
    """
    first = fetch_cinema_day(rule)
    listings: dict[date, list[Showtime]] = {}

    for day in sorted(first.known_dates):
        if day in skip_dates:
            continue
        if rule.from_date and day < rule.from_date:
            continue
        if rule.target_date and day != rule.target_date:
            continue
        page = first if day == min(first.known_dates) else fetch_cinema_day(rule, day)
        showtimes = showtimes_for_movie(page.blocks, rule, day)
        if showtimes:
            listings[day] = showtimes

    return listings


def check_district(rule: WatchRule, target_date: date) -> AvailabilityResult:
    cinema_id = rule.cinema.district_cinema_id
    if not cinema_id:
        return AvailabilityResult(
            platform="district",
            available=False,
            target_date=target_date,
            error="Missing district.cinema_id in rule",
        )

    try:
        page = fetch_cinema_day(rule, target_date)
        showtimes = showtimes_for_movie(page.blocks, rule, target_date)

        return AvailabilityResult(
            platform="district",
            available=bool(showtimes),
            target_date=target_date,
            showtimes=showtimes,
            known_dates=page.known_dates,
            raw={"known_dates": [d.isoformat() for d in page.known_dates]},
        )
    except Exception as exc:  # noqa: BLE001 - surface checker errors to engine
        return AvailabilityResult(
            platform="district",
            available=False,
            target_date=target_date,
            error=str(exc),
        )
