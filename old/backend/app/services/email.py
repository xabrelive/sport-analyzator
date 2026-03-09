"""Сервис отправки почты: верификация и рассылка сигналов. Отдельный модуль от Telegram."""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urlencode

from app.config import settings

logger = logging.getLogger(__name__)


def _send_via_smtp(to_email: str, subject: str, body_text: str) -> bool:
    """Отправить письмо через SMTP. Возвращает True при успехе."""
    if not settings.smtp_host or not settings.smtp_from_email:
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from_email
        msg["To"] = to_email
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            if settings.smtp_use_tls:
                server.starttls()
            if settings.smtp_user and settings.smtp_password:
                server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_from_email, [to_email], msg.as_string())
        return True
    except Exception as e:
        logger.exception("SMTP send failed: %s", e)
        return False


def send_verification_email(email: str, verify_link: str) -> None:
    """Send email with verification link. When no SMTP configured, only log."""
    if _send_via_smtp(
        email,
        "Подтверждение email — PingWin",
        f"Перейдите по ссылке для подтверждения: {verify_link}",
    ):
        logger.info("Verification email sent to %s", email)
    else:
        logger.info("Verification email (no SMTP): %s -> %s", email, verify_link)


def send_signal_email(to_email: str, subject: str, body_text: str) -> bool:
    """
    Отправить письмо с сигналом/уведомлением.
    Если SMTP не настроен — только логируем и возвращаем False.
    Не отправляем на placeholder-адреса (tg_...@telegram.pingwin.local).
    """
    if to_email.startswith("tg_") and "@telegram.pingwin.local" in to_email:
        logger.debug("Skip signal email for placeholder address")
        return False
    if _send_via_smtp(to_email, subject, body_text):
        logger.info("Signal email sent to %s: %s", to_email, subject[:50])
        return True
    logger.info("Signal email (no SMTP): to=%s subject=%s", to_email, subject)
    return False
