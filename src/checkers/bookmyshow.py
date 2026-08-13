from __future__ import annotations

import json
import re
from datetime import date, datetime

import requests

from src.models import AvailabilityResult, Showtime, WatchRule, movie_matches

BMS_BASE = "https://in.bookmyshow.com"
HEADERS = {
    "User-Agent": "BookMyShow/7.5.0 (Android 13; SM-G991B)",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "x-platform": "ANDROID",
    "x-platform-version": "7.5.0",
}


def _bms_headers(region: str) -> dict[str, str]:
    return {
        **HEADERS,
        "x-region-code": region,
    }


def _cinema_page_url(rule: WatchRule, target_date: date) -> str | None:
    region = (rule.cinema.bms_region or "").lower()
    slug = rule.cinema.bms_slug
    venue_code = rule.cinema.bms_venue_code
    if not (region and slug and venue_code):
        return None
    return f"{BMS_BASE}/cinemas/{region}/{slug}/buytickets/{venue_code}/{target_date.strftime('%Y%m%d')}"


def _parse_showtimes_from_html(html: str, movie_name: str) -> list[Showtime]:
    showtimes: list[Showtime] = []
    normalized_movie = movie_name.lower()

    for match in re.finditer(r'"EventTitle"\s*:\s*"([^"]+)"', html):
        title = match.group(1)
        if not movie_matches(title, normalized_movie):
            continue

        chunk = html[match.start() : match.start() + 4000]
        for time_match in re.finditer(r'"ShowTime"\s*:\s*"([^"]+)"', chunk):
            raw_time = time_match.group(1)
            parsed = _parse_bms_time(raw_time)
            if parsed:
                showtimes.append(Showtime(time=parsed))

        for time_match in re.finditer(r'"ShowTimes"\s*:\s*"([^"]+)"', chunk):
            raw_time = time_match.group(1)
            parsed = _parse_bms_time(raw_time)
            if parsed:
                showtimes.append(Showtime(time=parsed))

    if showtimes:
        return _dedupe_showtimes(showtimes)

    if normalized_movie.replace(" ", "") in html.lower().replace(" ", ""):
        for time_match in re.finditer(
            r'(?i)' + re.escape(movie_name) + r'.{0,800}?(\d{1,2}:\d{2}\s*(?:AM|PM))',
            html,
            flags=re.DOTALL,
        ):
            showtimes.append(Showtime(time=time_match.group(1).upper()))

    return _dedupe_showtimes(showtimes)


def _parse_bms_time(raw_time: str) -> str | None:
    for fmt in ("%I:%M %p", "%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(raw_time.strip(), fmt)
            return parsed.strftime("%I:%M %p").lstrip("0")
        except ValueError:
            continue
    return None


def _dedupe_showtimes(showtimes: list[Showtime]) -> list[Showtime]:
    seen: set[tuple[str | None, str | None, str | None]] = set()
    unique: list[Showtime] = []
    for item in showtimes:
        key = (item.time, item.screen, item.format)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    unique.sort(key=lambda value: value.time)
    return unique


def _parse_known_dates_from_html(html: str) -> list[date]:
    dates: set[date] = set()
    for match in re.finditer(r'"DateCode"\s*:\s*"(\d{8})"', html):
        raw = match.group(1)
        dates.add(date(int(raw[0:4]), int(raw[4:6]), int(raw[6:8])))

    for match in re.finditer(r'data-date-code="(\d{8})"', html):
        raw = match.group(1)
        dates.add(date(int(raw[0:4]), int(raw[4:6]), int(raw[6:8])))

    return sorted(dates)


def _check_via_mobile_api(rule: WatchRule, target_date: date) -> AvailabilityResult | None:
    if not (rule.cinema.bms_region and rule.bms_event_code):
        return None

    params = {
        "regionCode": rule.cinema.bms_region,
        "subCode": "",
        "eventCode": rule.bms_event_code,
        "dateCode": target_date.strftime("%Y%m%d"),
    }

    endpoints = [
        f"{BMS_BASE}/api/v2/mobile/showtimes/byevent",
        f"{BMS_BASE}/pwa/api/de/showtimes/byevent",
    ]

    for endpoint in endpoints:
        response = requests.get(
            endpoint,
            params=params,
            headers=_bms_headers(rule.cinema.bms_region),
            timeout=25,
        )
        if response.status_code != 200:
            continue

        try:
            payload = response.json()
        except json.JSONDecodeError:
            continue

        showtimes = _parse_mobile_api_payload(payload, rule)
        known_dates = _parse_mobile_known_dates(payload)
        return AvailabilityResult(
            platform="bookmyshow",
            available=bool(showtimes),
            target_date=target_date,
            showtimes=showtimes,
            known_dates=known_dates,
            raw={"endpoint": endpoint},
        )

    return None


def _parse_mobile_known_dates(payload: dict) -> list[date]:
    dates: set[date] = set()
    show_details = payload.get("BookMyShow", {}).get("ShowDetails", [])
    for detail in show_details:
        date_code = detail.get("DateCode")
        if date_code and str(date_code).isdigit() and len(str(date_code)) == 8:
            raw = str(date_code)
            dates.add(date(int(raw[0:4]), int(raw[4:6]), int(raw[6:8])))
    return sorted(dates)


def _parse_mobile_api_payload(payload: dict, rule: WatchRule) -> list[Showtime]:
    showtimes: list[Showtime] = []
    show_details = payload.get("BookMyShow", {}).get("ShowDetails", [])
    venue_hint = rule.cinema.name.lower()

    for detail in show_details:
        for venue in detail.get("Venues", []):
            venue_name = str(venue.get("VenueName", ""))
            if venue_hint and venue_hint not in venue_name.lower():
                continue

            for child_event in venue.get("ChildEvents", []):
                title = str(child_event.get("EventTitle", ""))
                if title and not movie_matches(title, rule.movie):
                    continue

                for session in child_event.get("SessionDetails", []):
                    raw_time = session.get("ShowTime") or session.get("ShowTimes")
                    parsed = _parse_bms_time(str(raw_time)) if raw_time else None
                    if parsed:
                        showtimes.append(
                            Showtime(
                                time=parsed,
                                screen=session.get("ScreenName") or session.get("Auditorium"),
                                format=session.get("EventDimension") or session.get("EventFormat"),
                            )
                        )

    return _dedupe_showtimes(showtimes)


def _check_via_cinema_page(rule: WatchRule, target_date: date) -> AvailabilityResult:
    page_url = _cinema_page_url(rule, target_date)
    if not page_url:
        return AvailabilityResult(
            platform="bookmyshow",
            available=False,
            target_date=target_date,
            error="Missing bookmyshow region, slug, or venue_code in rule",
        )

    browser_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-IN,en;q=0.9",
    }
    response = requests.get(page_url, headers=browser_headers, timeout=25)

    if response.status_code != 200:
        return AvailabilityResult(
            platform="bookmyshow",
            available=False,
            target_date=target_date,
            error=f"BookMyShow returned HTTP {response.status_code}",
        )

    known_dates = _parse_known_dates_from_html(response.text)
    showtimes = _parse_showtimes_from_html(response.text, rule.movie)

    return AvailabilityResult(
        platform="bookmyshow",
        available=bool(showtimes),
        target_date=target_date,
        showtimes=showtimes,
        known_dates=known_dates,
        raw={"url": page_url},
    )


def check_bookmyshow(rule: WatchRule, target_date: date) -> AvailabilityResult:
    try:
        api_result = _check_via_mobile_api(rule, target_date)
        if api_result is not None:
            return api_result
        return _check_via_cinema_page(rule, target_date)
    except Exception as exc:  # noqa: BLE001
        return AvailabilityResult(
            platform="bookmyshow",
            available=False,
            target_date=target_date,
            error=str(exc),
        )
