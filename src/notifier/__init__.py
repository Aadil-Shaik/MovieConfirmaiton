from __future__ import annotations

import os

from src.notifier.email import email_configured, send_email
from src.notifier.telegram import send_telegram_message


def telegram_configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def notify(subject: str, body: str) -> list[str]:
    """Send to every configured channel. Returns per-channel errors.

    Raises only if no channel succeeded, so the caller can retry on the next run.
    """
    channels = []
    if telegram_configured():
        channels.append(("telegram", lambda: send_telegram_message(f"{subject}\n\n{body}")))
    if email_configured():
        channels.append(("email", lambda: send_email(subject, body)))
    if not channels:
        raise RuntimeError("No alert channel configured: set Telegram and/or email variables in .env")

    errors: list[str] = []
    for name, send in channels:
        try:
            send()
        except Exception as exc:  # noqa: BLE001 - one channel failing must not block the other
            errors.append(f"{name}: {exc}")

    if len(errors) == len(channels):
        raise RuntimeError("All alert channels failed: " + "; ".join(errors))
    return errors
