from __future__ import annotations

from datetime import date
from typing import Any

from src.checkers.bookmyshow import check_bookmyshow
from src.checkers.district import check_district
from src.config import load_rules, load_state, save_state, utc_now_iso
from src.models import AvailabilityResult, WatchRule
from src.notifier.telegram import send_telegram_message

CHECKERS = {
    "district": check_district,
    "bookmyshow": check_bookmyshow,
}


def _format_showtimes(showtimes: list) -> str:
    if not showtimes:
        return "Showtimes detected, but exact times could not be parsed."
    lines = []
    for item in showtimes[:8]:
        extra = []
        if item.screen:
            extra.append(item.screen)
        if item.format:
            extra.append(item.format)
        suffix = f" ({', '.join(extra)})" if extra else ""
        lines.append(f"- {item.time}{suffix}")
    if len(showtimes) > 8:
        lines.append(f"- ...and {len(showtimes) - 8} more")
    return "\n".join(lines)


def _build_alert(rule: WatchRule, target_date: date, results: list[AvailabilityResult]) -> str:
    date_label = target_date.strftime("%A, %d %b %Y")
    lines = [
        "Tickets are LIVE",
        "",
        f"Movie: {rule.movie}",
        f"Cinema: {rule.cinema.name}",
        f"Date: {date_label}",
        "",
    ]

    for result in results:
        lines.append(f"{result.platform.title()}:")
        lines.append(_format_showtimes(result.showtimes))
        lines.append("")

    if rule.links.get("district"):
        lines.append(f"District: {rule.links['district']}")
    if rule.links.get("bookmyshow"):
        bms_link = rule.links["bookmyshow"]
        if bms_link.endswith("/"):
            bms_link = bms_link[:-1]
        lines.append(f"BookMyShow: {bms_link}/{target_date.strftime('%Y%m%d')}")

    lines.append("")
    lines.append(f"Rule: {rule.id}")
    return "\n".join(lines)


def _ensure_rule_bucket(state: dict[str, Any], rule_id: str) -> dict[str, Any]:
    rules = state.setdefault("rules", {})
    return rules.setdefault(rule_id, {})


def _should_skip_rule(rule: WatchRule, today: date) -> bool:
    return bool(rule.watch_until and today > rule.watch_until)


def _validate_rule(rule: WatchRule) -> list[str]:
    errors: list[str] = []
    for platform in rule.platforms:
        if platform not in CHECKERS:
            errors.append(f"Unknown platform '{platform}'")
        if platform == "district" and not rule.cinema.district_cinema_id:
            errors.append("Missing cinema.district.cinema_id")
        if platform == "bookmyshow" and not rule.cinema.bms_venue_code:
            errors.append("Missing cinema.bookmyshow.venue_code")
    return errors


def run_checks(today: date | None = None, dry_run: bool = False) -> dict[str, Any]:
    today = today or date.today()
    rules = load_rules()
    state = load_state()
    summary = {"checked": 0, "alerts_sent": 0, "errors": []}

    for rule in rules:
        if _should_skip_rule(rule, today):
            continue

        validation_errors = _validate_rule(rule)
        if validation_errors:
            for error in validation_errors:
                summary["errors"].append(f"{rule.id}: {error}")
            continue

        try:
            target_dates = rule.resolve_target_dates(today=today)
        except ValueError as exc:
            summary["errors"].append(str(exc))
            continue

        target_date = target_dates[0]
        rule_bucket = _ensure_rule_bucket(state, rule.id)
        date_key = target_date.isoformat()
        date_bucket = rule_bucket.setdefault(date_key, {})

        platform_results: list[AvailabilityResult] = []
        newly_available: list[AvailabilityResult] = []

        for platform in rule.platforms:
            checker = CHECKERS[platform]
            result = checker(rule, target_date)
            platform_results.append(result)
            summary["checked"] += 1

            platform_bucket = date_bucket.setdefault(platform, {})
            previous_available = platform_bucket.get("available")

            platform_bucket["last_checked"] = utc_now_iso()
            platform_bucket["available"] = result.available
            platform_bucket["showtimes"] = [
                {"time": show.time, "screen": show.screen, "format": show.format}
                for show in result.showtimes
            ]
            platform_bucket.pop("error", None)
            if result.error:
                platform_bucket["error"] = result.error
                summary["errors"].append(f"{rule.id}/{platform}: {result.error}")

            if result.available and previous_available is False:
                newly_available.append(result)
            elif result.available and previous_available is None:
                platform_bucket["notified"] = True
                platform_bucket["notified_at"] = utc_now_iso()

        if newly_available and not dry_run:
            available_now = [result for result in platform_results if result.available]
            send_telegram_message(_build_alert(rule, target_date, available_now))
            summary["alerts_sent"] += 1
            for result in newly_available:
                bucket = date_bucket.setdefault(result.platform, {})
                bucket["notified"] = True
                bucket["notified_at"] = utc_now_iso()

    save_state(state)
    return summary
