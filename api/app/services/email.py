"""Optional SMTP email delivery."""

import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger(__name__)

def email_configured() -> bool:
    return bool(settings.smtp_host.strip())


def send_email(to: str, subject: str, body: str) -> bool:
    """Send plain-text email. Returns True if sent, False if skipped/failed."""
    if not email_configured():
        logger.info("email skipped (no SMTP): subject=%s", subject)
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or settings.smtp_user or "fos@localhost"
    msg["To"] = to
    msg.set_content(body)
    try:
        with smtplib.SMTP(
            settings.smtp_host,
            settings.smtp_port,
            timeout=float(settings.smtp_timeout_seconds),
        ) as server:
            if settings.smtp_use_tls:
                server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        logger.info("email sent subject=%s", subject)
        return True
    except Exception as exc:  # noqa: BLE001 — never fail the API path on mail
        logger.warning("email failed subject=%s err=%s", subject, type(exc).__name__)
        return False


def send_invite_email(
    *,
    to: str,
    full_name: str,
    org_name: str,
    org_slug: str,
    invite_token: str | None,
    temp_password: bool,
) -> bool:
    app = settings.public_app_url.strip().rstrip("/") or "the Fos app"
    if invite_token:
        body = (
            f"Hi {full_name},\n\n"
            f"You were invited to {org_name} on Fos (slug: {org_slug}).\n\n"
            f"Open {app}, choose Accept invite, paste this token, and set your password:\n\n"
            f"{invite_token}\n\n"
            f"— Fos\n"
        )
    else:
        body = (
            f"Hi {full_name},\n\n"
            f"You were invited to {org_name} on Fos.\n"
            f"Log in with slug `{org_slug}`, this email, and the temporary password "
            f"your manager shared{' ' if temp_password else ' (set by your manager)'}.\n\n"
            f"App: {app}\n\n— Fos\n"
        )
    return send_email(to, f"Fos invite — {org_name}", body)


def send_reset_email(
    *,
    to: str,
    full_name: str,
    org_name: str,
    org_slug: str,
    reset_token: str,
) -> bool:
    app = settings.public_app_url.strip().rstrip("/") or "the Fos app"
    body = (
        f"Hi {full_name},\n\n"
        f"A password reset was issued for {org_name} (slug: {org_slug}).\n\n"
        f"Open {app}, choose Accept invite, paste this token, and set a new password:\n\n"
        f"{reset_token}\n\n"
        f"If you did not expect this, contact your owner.\n\n— Fos\n"
    )
    return send_email(to, f"Fos password reset — {org_name}", body)
