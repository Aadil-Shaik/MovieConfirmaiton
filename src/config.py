from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from src.models import CinemaConfig, WatchRule


ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "rules.yaml"
STATE_PATH = ROOT / "state.json"


def load_rules(path: Path | None = None) -> list[WatchRule]:
    rules_path = path or RULES_PATH
    with rules_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}

    rules: list[WatchRule] = []
    for item in payload.get("rules", []):
        cinema_raw = item.get("cinema", {})
        district = cinema_raw.get("district", {})
        bms = cinema_raw.get("bookmyshow", {})

        target_date = None
        if item.get("target_date"):
            target_date = date.fromisoformat(str(item["target_date"]))

        watch_until = None
        if item.get("watch_until"):
            watch_until = date.fromisoformat(str(item["watch_until"]))

        target_weekday = item.get("target_weekday")
        if target_weekday:
            target_weekday = str(target_weekday).lower()

        rules.append(
            WatchRule(
                id=str(item["id"]),
                enabled=bool(item.get("enabled", True)),
                movie=str(item["movie"]),
                cinema=CinemaConfig(
                    name=str(cinema_raw.get("name", "")),
                    district_cinema_id=str(district.get("cinema_id")) if district.get("cinema_id") else None,
                    district_slug=str(district.get("slug")) if district.get("slug") else None,
                    bms_region=str(bms.get("region")) if bms.get("region") else None,
                    bms_venue_code=str(bms.get("venue_code")) if bms.get("venue_code") else None,
                    bms_slug=str(bms.get("slug")) if bms.get("slug") else None,
                ),
                target_date=target_date,
                target_weekday=target_weekday,
                platforms=[str(p).lower() for p in item.get("platforms", ["district", "bookmyshow"])],
                links={str(k): str(v) for k, v in (item.get("links") or {}).items()},
                bms_event_code=item.get("bookmyshow_event_code"),
                watch_until=watch_until,
            )
        )

    return [rule for rule in rules if rule.enabled]


def load_state(path: Path | None = None) -> dict[str, Any]:
    state_path = path or STATE_PATH
    if not state_path.exists():
        return {"rules": {}}
    with state_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_state(state: dict[str, Any], path: Path | None = None) -> None:
    state_path = path or STATE_PATH
    with state_path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)


def load_env_file(path: Path | None = None) -> None:
    env_path = path or ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
