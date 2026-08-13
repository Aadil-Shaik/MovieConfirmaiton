from __future__ import annotations

import json
import re
from datetime import date, datetime

import requests

from src.models import AvailabilityResult, Showtime, WatchRule, movie_matches

BASE_URL = "https://www.district.in/movies"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}


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
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
    if not match:
        raise RuntimeError("District page did not contain embedded showtime data")
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


def _parse_known_dates(cinema_payload: dict) -> list[date]:
    raw_dates = cinema_payload.get("data", {}).get("sessionDates", [])
    return [date.fromisoformat(value) for value in raw_dates]


def _showtimes_for_movie_on_date(cinema_payload: dict, movie_name: str, target_date: date) -> list[Showtime]:
    showtimes: list[Showtime] = []
    target_prefix = target_date.isoformat()

    for block in cinema_payload.get("arrangedSessions", []):
        label = block.get("data", {}).get("label") or block.get("entityName") or ""
        if not movie_matches(label, movie_name):
            continue

        for session in block.get("sessions", []):
            show_time = session.get("showTime") or session.get("show_time")
            if not show_time or not str(show_time).startswith(target_prefix):
                continue

            parsed = datetime.fromisoformat(str(show_time))
            showtimes.append(
                Showtime(
                    time=parsed.strftime("%I:%M %p").lstrip("0"),
                    screen=session.get("audi"),
                    format=session.get("scrnFmt") or session.get("premiumLabel"),
                )
            )

    showtimes.sort(key=lambda item: item.time)
    return showtimes


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
        response = requests.get(_district_url(rule), headers=HEADERS, timeout=25)
        response.raise_for_status()
        payload = _parse_next_data(response.text)
        cinema_payload = _extract_cinema_sessions(payload, cinema_id)
        known_dates = _parse_known_dates(cinema_payload)
        showtimes = _showtimes_for_movie_on_date(cinema_payload, rule.movie, target_date)

        return AvailabilityResult(
            platform="district",
            available=bool(showtimes),
            target_date=target_date,
            showtimes=showtimes,
            known_dates=known_dates,
            raw={"known_dates": [d.isoformat() for d in known_dates]},
        )
    except Exception as exc:  # noqa: BLE001 - surface checker errors to engine
        return AvailabilityResult(
            platform="district",
            available=False,
            target_date=target_date,
            error=str(exc),
        )
