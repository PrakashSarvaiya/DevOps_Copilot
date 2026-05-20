import logging
import smtplib
from email.message import EmailMessage
from app.core.config import settings

logger = logging.getLogger("DevOps_notifier")


def send_failure_email(
    recipient: str,
    subject: str,
    body: str,
) -> bool:
    if not recipient:
        logger.info("No recipient configured for failure notification.")
        return False

    if not settings.SMTP_HOST or not settings.SMTP_FROM_EMAIL:
        logger.info("SMTP is not configured. Notification skipped for %s.", recipient)
        return False

    message = EmailMessage()
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
        if settings.SMTP_USE_TLS:
            smtp.starttls()
        if settings.SMTP_USERNAME:
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        smtp.send_message(message)

    return True
