from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


def email_configured() -> bool:
    return all(os.environ.get(key) for key in ("EMAIL_USER", "EMAIL_APP_PASSWORD", "EMAIL_TO"))


def send_email(subject: str, body: str) -> None:
    user = os.environ.get("EMAIL_USER")
    password = os.environ.get("EMAIL_APP_PASSWORD")
    recipients = os.environ.get("EMAIL_TO")
    if not (user and password and recipients):
        raise RuntimeError("Set EMAIL_USER, EMAIL_APP_PASSWORD and EMAIL_TO in environment or .env")

    host = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("EMAIL_SMTP_PORT", "465"))

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = user
    message["To"] = recipients
    message.set_content(body)

    with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
        smtp.login(user, password.replace(" ", ""))
        smtp.send_message(message)
