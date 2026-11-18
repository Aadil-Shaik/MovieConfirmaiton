from __future__ import annotations

from datetime import date
from typing import Any

from src.checkers import district
from src.checkers.bookmyshow import check_bookmyshow
from src.checkers.district import check_district, find_listings
from src.config import load_rules, load_state, save_state, utc_now_iso
from src.models import AvailabilityResult, Showtime, WatchRule
from src.notifier import notify

CHECKERS = {
    "district": check_district,
    "bookmyshow": check_bookmyshow,
}

# Consecutive failed runs before a "watcher can't reach District" alert (6 runs ~ 30-60 min).
ERROR_ALERT_THRESHOLD = 6


def _format_showtimes(showtimes: list[Showtime]) -> str:
    if not showtimes:
        return "Showtimes detected, but exact times could not be parsed."
    lines = []
    for item in showtimes[:10]:
        extra = [part for part in (item.screen, item.format, item.seats) if part]
        suffix = f" ({', '.join(extra)})" if extra else ""
        lines.append(f"- {item.time}{suffix}")
    if len(showtimes) > 10:
        lines.append(f"- ...and {len(showtimes) - 10} more")
    return "\n".join(lines)


def _district_link(rule: WatchRule, day: date | None = None) -> str | None:
    link = rule.links.get("district")
    if link and day:
        link = f"{link}?fromdate={day.isoformat()}"
    return link


def _build_alert(rule: WatchRule, target_date: date, results: list[AvailabilityResult]) -> tuple[str, str]:
    date_label = target_date.strftime("%A, %d %b %Y")
    lines = [
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
        lines.append(f"District: {_district_link(rule, target_date)}")
    if rule.links.get("bookmyshow"):
        bms_link = rule.links["bookmyshow"].rstrip("/")
        lines.append(f"BookMyShow: {bms_link}/{target_date.strftime('%Y%m%d')}")

    lines.append("")
    lines.append(f"Rule: {rule.id}")
    return f"Tickets LIVE: {rule.movie} @ {rule.cinema.name}", "\n".join(lines)


def _build_listing_alert(rule: WatchRule, listings: dict[date, list[Showtime]], first_alert: bool) -> tuple[str, str]:
    headline = "BOOKING OPEN" if first_alert else "New dates added"
    subject = f"{headline}: {rule.movie} @ {rule.cinema.name}"
    lines = [f"Movie: {rule.movie}", f"Cinema: {rule.cinema.name}", ""]
    for day in sorted(listings):
        lines.append(day.strftime("%A, %d %b %Y") + ":")
        lines.append(_format_showtimes(listings[day]))
        link = _district_link(rule, day)
        if link:
            lines.append(f"Book: {link}")
        lines.append("")
    lines.append(f"Rule: {rule.id}")
    return subject, "\n".join(lines)


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
    if rule.watches_any_date and rule.platforms != ["district"]:
        errors.append("Rules without target_date/target_weekday only support platforms: [district]")
    return errors


def _run_listing_rule(rule: WatchRule, state: dict[str, Any], summary: dict[str, Any], dry_run: bool) -> None:
    """Alert the first time the movie appears at this cinema (on target_date, or any date), then on new dates."""
    bucket = _ensure_rule_bucket(state, rule.id)
    alerted: dict[str, str] = bucket.setdefault("alerted_dates", {})
    skip = {date.fromisoformat(day) for day in alerted}
    summary["checked"] += 1

    try:
        listings = find_listings(rule, skip)
    except Exception as exc:  # noqa: BLE001
        failures = bucket.get("consecutive_errors", 0) + 1
        bucket["consecutive_errors"] = failures
        bucket["last_error"] = str(exc)
        summary["errors"].append(f"{rule.id}/district: {exc}")
        if failures >= ERROR_ALERT_THRESHOLD and not bucket.get("error_alert_sent") and not dry_run:
            try:
                notify(
                    f"Ticket watcher can't reach District ({rule.movie})",
                    f"The last {failures} checks for '{rule.movie}' at {rule.cinema.name} failed.\n"
                    f"Latest error: {exc}\n\n"
                    "Until this is fixed you will NOT get a booking alert. Check manually:\n"
                    f"{rule.links.get('district', '')}",
                )
                bucket["error_alert_sent"] = True
                summary["alerts_sent"] += 1
            except Exception as notify_exc:  # noqa: BLE001
                summary["errors"].append(f"{rule.id}: alert failed: {notify_exc}")
        return

    if bucket.pop("consecutive_errors", None) is not None:
        bucket.pop("last_error", None)
        bucket.pop("error_alert_sent", None)

    if not listings:
        return

    first_alert = not alerted
    subject, body = _build_listing_alert(rule, listings, first_alert)
    if dry_run:
        print(f"[dry-run] would send:\n{subject}\n\n{body}\n")
        return

    try:
        channel_errors = notify(subject, body)
    except Exception as exc:  # noqa: BLE001 - leave dates un-alerted so the next run retries
        summary["errors"].append(f"{rule.id}: alert failed: {exc}")
        return

    summary["errors"].extend(f"{rule.id}: {err}" for err in channel_errors)
    summary["alerts_sent"] += 1
    now = utc_now_iso()
    for day in listings:
        alerted[day.isoformat()] = now


def _run_target_rule(rule: WatchRule, today: date, state: dict[str, Any], summary: dict[str, Any], dry_run: bool) -> None:
    try:
        target_date = rule.resolve_target_dates(today=today)[0]
    except ValueError as exc:
        summary["errors"].append(str(exc))
        return

    date_bucket = _ensure_rule_bucket(state, rule.id).setdefault(target_date.isoformat(), {})
    platform_results: list[AvailabilityResult] = []
    newly_available: list[AvailabilityResult] = []

    for platform in rule.platforms:
        result = CHECKERS[platform](rule, target_date)
        platform_results.append(result)
        summary["checked"] += 1

        platform_bucket = date_bucket.setdefault(platform, {})
        previous_available = platform_bucket.get("available")
        platform_bucket["available"] = result.available
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
        subject, body = _build_alert(rule, target_date, available_now)
        try:
            notify(subject, body)
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"{rule.id}: alert failed: {exc}")
            for result in newly_available:
                date_bucket[result.platform]["available"] = False  # retry next run
            return
        summary["alerts_sent"] += 1
        for result in newly_available:
            bucket = date_bucket.setdefault(result.platform, {})
            bucket["notified"] = True
            bucket["notified_at"] = utc_now_iso()


def run_checks(today: date | None = None, dry_run: bool = False) -> dict[str, Any]:
    today = today or date.today()
    rules = load_rules()
    state = load_state()
    summary: dict[str, Any] = {"checked": 0, "alerts_sent": 0, "errors": []}
    district.clear_cache()

    for rule in rules:
        if _should_skip_rule(rule, today):
            continue

        validation_errors = _validate_rule(rule)
        if validation_errors:
            summary["errors"].extend(f"{rule.id}: {error}" for error in validation_errors)
            continue

        if rule.uses_listing_mode:
            _run_listing_rule(rule, state, summary, dry_run)
        else:
            _run_target_rule(rule, today, state, summary, dry_run)

    if not dry_run:
        save_state(state)
    return summary
