from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def movie_matches(candidate: str, target: str) -> bool:
    left = normalize_text(candidate)
    right = normalize_text(target)
    if not left or not right:
        return False
    return left == right or left in right or right in left


@dataclass
class CinemaConfig:
    name: str
    district_cinema_id: str | None = None
    district_slug: str | None = None
    bms_region: str | None = None
    bms_venue_code: str | None = None
    bms_slug: str | None = None


@dataclass
class WatchRule:
    id: str
    enabled: bool
    movie: str
    cinema: CinemaConfig
    target_date: date | None = None
    target_weekday: str | None = None
    platforms: list[str] = field(default_factory=lambda: ["district", "bookmyshow"])
    links: dict[str, str] = field(default_factory=dict)
    bms_event_code: str | None = None
    watch_until: date | None = None

    def resolve_target_dates(self, today: date, known_dates: list[date] | None = None) -> list[date]:
        del known_dates  # weekday rules always use the next upcoming weekday occurrence

        if self.target_date:
            return [self.target_date]

        if not self.target_weekday:
            raise ValueError(f"Rule '{self.id}' needs target_date or target_weekday")

        weekday = WEEKDAYS[self.target_weekday.lower()]
        cursor = today
        for _ in range(21):
            if cursor.weekday() == weekday:
                return [cursor]
            cursor = date.fromordinal(cursor.toordinal() + 1)

        raise ValueError(f"Rule '{self.id}' could not resolve upcoming {self.target_weekday}")


@dataclass
class Showtime:
    time: str
    screen: str | None = None
    format: str | None = None


@dataclass
class AvailabilityResult:
    platform: str
    available: bool
    target_date: date
    showtimes: list[Showtime] = field(default_factory=list)
    known_dates: list[date] = field(default_factory=list)
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
