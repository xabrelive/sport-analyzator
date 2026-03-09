"""Send verification code by email."""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger(__name__)


def _send_smtp(to_email: str, subject: str, body: str) -> bool:
    if not settings.smtp_host or not settings.smtp_from_email:
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from_email
        msg["To"] = to_email
        msg.attach(MIMEText(body, "plain", "utf-8"))
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


def send_verification_code_email(email: str, code: str) -> bool:
    """Send code to email. Returns True if sent, False otherwise (e.g. no SMTP). Logs if not sent."""
    subject = "Код подтверждения — PingWin"
    body = f"Ваш код подтверждения: {code}\n\nКод действителен {settings.verification_code_expire_minutes} минут.\n\nЕсли вы не запрашивали код, проигнорируйте это письмо."
    if _send_smtp(email, subject, body):
        logger.info("Verification code email sent to %s", email)
        return True
    logger.info("Verification code (no SMTP): %s -> code %s", email, code)
    return False
