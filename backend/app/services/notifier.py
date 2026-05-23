import logging
import re
import smtplib
from email.message import EmailMessage
from typing import Optional

from app.core.config import settings

logger = logging.getLogger("DevOps_notifier")


def send_failure_email(
    recipient: str,
    subject: str,
    body: str,
    html_body: Optional[str] = None,
) -> bool:
    """
    Send an SMTP message to one or more recipients.

    `recipient` may be a single address or a comma/semicolon-separated list
    (e.g. "alice@x.com, bob@x.com") — we split it before handing to the
    server. `body` is the plain-text body. When `html_body` is provided we
    emit a multipart/alternative message so clients that render HTML get the
    pretty template, and clients that don't fall back to the plain text.
    """
    if not recipient:
        logger.info("No recipient configured for failure notification.")
        return False

    if not settings.SMTP_HOST or not settings.SMTP_FROM_EMAIL:
        logger.info("SMTP is not configured. Notification skipped for %s.", recipient)
        return False

    recipients = [addr.strip() for addr in re.split(r"[;,]", recipient) if addr.strip()]
    if not recipients:
        logger.info("No valid recipient addresses found for failure notification.")
        return False

    message = EmailMessage()
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
        if settings.SMTP_USE_TLS:
            smtp.starttls()
        if settings.SMTP_USERNAME:
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        smtp.send_message(message)

    return True
