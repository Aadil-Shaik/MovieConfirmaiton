from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime


from src.config import load_env_file, load_rules
from src.engine import run_checks
from src.notifier import notify


def cmd_check(args: argparse.Namespace) -> int:
    summary = run_checks(dry_run=args.dry_run)
    print(f"Checked: {summary['checked']} platform checks")
    print(f"Alerts sent: {summary['alerts_sent']}")
    if summary["errors"]:
        print("Errors:")
        for error in summary["errors"]:
            print(f"  - {error}")
    # Non-zero exit (red run on GitHub) when every check failed, e.g. the site blocked us.
    if summary["checked"] and summary["failed"] == summary["checked"]:
        return 1
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    print(f"Watching every {args.interval}s. Press Ctrl+C to stop.")
    while True:
        try:
            summary = run_checks()
            status = f"alerts={summary['alerts_sent']}"
            if summary["errors"]:
                status += " errors=" + " | ".join(summary["errors"])
            print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] checked={summary['checked']} {status}", flush=True)
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] run failed: {exc}", flush=True)
        time.sleep(args.interval)


def cmd_list_rules(_: argparse.Namespace) -> int:
    rules = load_rules()
    if not rules:
        print("No enabled rules found in rules.yaml")
        return 0

    for rule in rules:
        target = rule.target_date.isoformat() if rule.target_date else (rule.target_weekday or "any date")
        platforms = ", ".join(rule.platforms)
        print(f"- {rule.id}: {rule.movie} @ {rule.cinema.name} | target={target} | platforms={platforms}")
    return 0


def cmd_test_alert(_: argparse.Namespace) -> int:
    errors = notify(
        "Movie ticket watcher: test alert",
        "If you received this, alerts are configured correctly.",
    )
    for error in errors:
        print(f"Channel failed - {error}")
    print("Test alert sent." if not errors else "Test alert sent on at least one channel.")
    return 1 if errors else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Movie ticket availability monitor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="Run all enabled watch rules")
    check_parser.add_argument("--dry-run", action="store_true", help="Print alerts instead of sending them; do not save state")
    check_parser.set_defaults(func=cmd_check)

    watch_parser = subparsers.add_parser("watch", help="Run checks in a loop on this computer")
    watch_parser.add_argument("--interval", type=int, default=300, help="Seconds between checks (min 120)")
    watch_parser.set_defaults(func=cmd_watch)

    list_parser = subparsers.add_parser("list-rules", help="Show enabled rules")
    list_parser.set_defaults(func=cmd_list_rules)

    test_parser = subparsers.add_parser("test-alert", help="Send a test message to Telegram and email")
    test_parser.set_defaults(func=cmd_test_alert)

    return parser


def main() -> int:
    load_env_file()
    parser = build_parser()
    args = parser.parse_args()
    if getattr(args, "interval", None) is not None:
        args.interval = max(args.interval, 120)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
