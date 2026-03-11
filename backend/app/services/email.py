"""Send verification code by email."""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger(__name__)


def _send_smtp(to_email: str, subject: str, body: str, body_html: str | None = None) -> bool:
    if not settings.smtp_host or not settings.smtp_from_email:
        logger.warning(
            "SMTP не настроен: smtp_host=%s, smtp_from_email=%s (задайте в .env или переменных окружения)",
            "есть" if settings.smtp_host else "нет",
            "есть" if settings.smtp_from_email else "нет",
        )
        return False
    try:
        logger.info(
            "Отправка письма на %s через %s:%s (SSL=%s)",
            to_email,
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_use_ssl or settings.smtp_port == 465,
        )
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from_email
        msg["To"] = to_email
        msg.attach(MIMEText(body, "plain", "utf-8"))
        if body_html:
            msg.attach(MIMEText(body_html, "html", "utf-8"))

        use_ssl = settings.smtp_use_ssl or settings.smtp_port == 465
        if use_ssl:
            with smtplib.SMTP_SSL(
                settings.smtp_host, settings.smtp_port, timeout=25
            ) as server:
                if settings.smtp_user and settings.smtp_password:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(settings.smtp_from_email, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(
                settings.smtp_host, settings.smtp_port, timeout=25
            ) as server:
                if settings.smtp_use_tls:
                    server.starttls()
                if settings.smtp_user and settings.smtp_password:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(settings.smtp_from_email, [to_email], msg.as_string())
        return True
    except Exception as e:
        logger.exception(
            "Ошибка SMTP при отправке на %s: %s (тип: %s). Проверьте SMTP_* в .env, для Mail.ru используйте пароль приложения.",
            to_email,
            e,
            type(e).__name__,
        )
        return False


def send_verification_code_email(email: str, code: str) -> bool:
    """Send code to email. Returns True if sent, False otherwise (e.g. no SMTP). Logs if not sent."""
    subject = "Код подтверждения — PingWin"
    minutes = settings.verification_code_expire_minutes_email
    expiry_text = "2 часа" if minutes == 120 else f"{minutes} мин."
    body = f"Ваш код подтверждения: {code}\n\nКод действителен {expiry_text}.\n\nЕсли вы не запрашивали код, проигнорируйте это письмо."
    if _send_smtp(email, subject, body):
        logger.info("Verification code email sent to %s", email)
        return True
    logger.warning("Verification code НЕ отправлен (проверьте SMTP): %s -> code %s", email, code)
    return False


def send_password_reset_code_email(email: str, code: str) -> bool:
    """Отправить код для сброса пароля. Код действителен 2 часа."""
    subject = "Сброс пароля — PingWin"
    minutes = settings.verification_code_expire_minutes_email
    expiry_text = "2 часа" if minutes == 120 else f"{minutes} мин."
    body = (
        f"Код для сброса пароля: {code}\n\n"
        f"Код действителен {expiry_text}.\n\n"
        "Если вы не запрашивали сброс пароля, проигнорируйте это письмо."
    )
    if _send_smtp(email, subject, body):
        logger.info("Password reset code email sent to %s", email)
        return True
    logger.warning("Password reset code НЕ отправлен (проверьте SMTP): %s", email)
    return False


def send_password_changed_email(email: str) -> bool:
    """Уведомить, что пароль был изменён (без указания пароля в письме)."""
    subject = "Пароль изменён — PingWin"
    body = "Ваш пароль был успешно изменён. Если это были не вы, свяжитесь с поддержкой."
    if _send_smtp(email, subject, body):
        logger.info("Password changed notification sent to %s", email)
        return True
    return False


def send_email_link_code_email(email: str, code: str) -> bool:
    """Код для привязки почты к аккаунту (уведомления). Действует 2 часа."""
    subject = "Привязка почты — PingWin"
    minutes = settings.verification_code_expire_minutes_email
    expiry_text = "2 часа" if minutes == 120 else f"{minutes} мин."
    body = (
        f"Код для привязки почты к аккаунту: {code}\n\n"
        f"Код действителен {expiry_text}. Введите его в настройках на сайте.\n\n"
        "Если вы не запрашивали привязку, проигнорируйте это письмо."
    )
    if _send_smtp(email, subject, body):
        logger.info("Email link code sent to %s", email)
        return True
    logger.warning("Email link code НЕ отправлен (SMTP): %s", email)
    return False


def send_text_email(email: str, subject: str, body: str) -> bool:
    """Send plain text email notification."""
    if _send_smtp(email, subject, body):
        logger.info("Text email sent to %s, subject=%s", email, subject)
        return True
    logger.warning("Text email НЕ отправлен (SMTP): %s, subject=%s", email, subject)
    return False


def send_html_email(email: str, subject: str, body_text: str, body_html: str) -> bool:
    """Send html+text email notification."""
    if _send_smtp(email, subject, body_text, body_html=body_html):
        logger.info("HTML email sent to %s, subject=%s", email, subject)
        return True
    logger.warning("HTML email НЕ отправлен (SMTP): %s, subject=%s", email, subject)
    return False
