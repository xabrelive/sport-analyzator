"""Send verification email. In dev logs link; extend with SMTP for production."""
import logging
from urllib.parse import urlencode

from app.config import settings

logger = logging.getLogger(__name__)


def send_verification_email(email: str, verify_link: str) -> None:
    """Send email with verification link. When no SMTP configured, only log."""
    # TODO: add SMTP (e.g. fastapi-mail, sendgrid) and send real email
    logger.info("Verification email for %s: %s", email, verify_link)
