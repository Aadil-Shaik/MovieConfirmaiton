from __future__ import annotations

import argparse
import sys
from datetime import date

from src.config import load_env_file, load_rules
from src.engine import run_checks
from src.notifier.telegram import send_telegram_message


def cmd_check(args: argparse.Namespace) -> int:
    summary = run_checks(dry_run=args.dry_run)
    print(f"Checked: {summary['checked']} platform checks")
    print(f"Alerts sent: {summary['alerts_sent']}")
    if summary["errors"]:
        print("Errors:")
        for error in summary["errors"]:
            print(f"  - {error}")
    return 0


def cmd_list_rules(_: argparse.Namespace) -> int:
    rules = load_rules()
    if not rules:
        print("No enabled rules found in rules.yaml")
        return 0

    for rule in rules:
        target = rule.target_date.isoformat() if rule.target_date else rule.target_weekday
        platforms = ", ".join(rule.platforms)
        print(f"- {rule.id}: {rule.movie} @ {rule.cinema.name} | target={target} | platforms={platforms}")
    return 0


def cmd_test_alert(_: argparse.Namespace) -> int:
    send_telegram_message(
        "Movie Confirmation bot test\n\nIf you received this, Telegram alerts are configured correctly."
    )
    print("Test alert sent.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Movie ticket availability monitor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="Run all enabled watch rules")
    check_parser.add_argument("--dry-run", action="store_true", help="Do not send Telegram alerts")
    check_parser.set_defaults(func=cmd_check)

    list_parser = subparsers.add_parser("list-rules", help="Show enabled rules")
    list_parser.set_defaults(func=cmd_list_rules)

    test_parser = subparsers.add_parser("test-alert", help="Send a Telegram test message")
    test_parser.set_defaults(func=cmd_test_alert)

    return parser


def main() -> int:
    load_env_file()
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
