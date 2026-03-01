"""
adapters/smtp_adapter.py — SMTP email adapter for sending alert emails.

Uses Python's built-in smtplib with STARTTLS — no third-party library required.
Compatible with personal Outlook (smtp.office365.com:587) and any standard SMTP server.

Mock mode is enabled by:
  - Passing use_mock=True to SMTPAdapter() directly, OR
  - Setting the environment variable USE_MOCK_SMTP=true

In mock mode, send_alert() logs the email to the Python logger instead of
sending it. No SMTP connection is made.

Required environment variables (production only):
  SMTP_HOST        — SMTP server hostname (default: smtp.office365.com)
  SMTP_PORT        — SMTP port (default: 587 for STARTTLS)
  SMTP_USERNAME    — Your Outlook email address
  SMTP_PASSWORD    — Your Outlook password or App Password (if MFA enabled)
  SMTP_FROM        — From address (optional, defaults to SMTP_USERNAME)
  ALERT_RECIPIENT  — Default alert recipient (used by callers; not required here)
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger(__name__)


class SMTPAdapter:
    """Sends alert emails via SMTP with STARTTLS (Outlook.com / Office 365 compatible).

    Parameters
    ----------
    host:
        SMTP server hostname. Overrides SMTP_HOST env var.
        Defaults to smtp.office365.com for personal Outlook accounts.
    port:
        SMTP port. Overrides SMTP_PORT env var. Defaults to 587 (STARTTLS).
    username:
        Your Outlook email address. Overrides SMTP_USERNAME env var.
    password:
        Your Outlook password or App Password. Overrides SMTP_PASSWORD env var.
    from_addr:
        From address. Overrides SMTP_FROM env var. Defaults to username.
    use_mock:
        If True, skip all SMTP setup. send_alert() logs instead of sending.
        Also activated by setting USE_MOCK_SMTP=true in the environment.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        from_addr: Optional[str] = None,
        use_mock: bool = False,
    ) -> None:
        # Determine mock mode: kwarg OR environment variable
        env_mock = os.getenv("USE_MOCK_SMTP", "false").lower() == "true"
        self._use_mock = use_mock or env_mock

        if self._use_mock:
            logger.debug(
                "SMTPAdapter initialised in mock mode "
                "(USE_MOCK_SMTP=true or use_mock=True). "
                "Emails will be logged, not sent."
            )
            return

        # --- Production mode: resolve and validate connection parameters ---
        self._host = host or os.getenv("SMTP_HOST", "smtp.office365.com")
        self._port = int(port or os.getenv("SMTP_PORT", "587"))
        self._username = username or os.getenv("SMTP_USERNAME")
        self._password = password or os.getenv("SMTP_PASSWORD")
        self._from_addr = from_addr or os.getenv("SMTP_FROM") or self._username

        if not self._username:
            raise ValueError(
                "SMTP_USERNAME must be set or passed to SMTPAdapter. "
                "Set the SMTP_USERNAME environment variable to your Outlook email address "
                "(e.g. you@outlook.com), or enable mock mode with USE_MOCK_SMTP=true."
            )
        if not self._password:
            raise ValueError(
                "SMTP_PASSWORD must be set or passed to SMTPAdapter. "
                "Set the SMTP_PASSWORD environment variable to your Outlook password or "
                "App Password (recommended if MFA is enabled), "
                "or enable mock mode with USE_MOCK_SMTP=true."
            )

        logger.info(
            "SMTPAdapter configured: host=%s port=%d user=%s",
            self._host,
            self._port,
            self._username,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_alert(self, recipient: str, subject: str, body: str) -> None:
        """Send a plain-text alert email.

        Parameters
        ----------
        recipient:
            Destination email address.
        subject:
            Email subject line.
        body:
            Plain-text email body.
        """
        if self._use_mock:
            logger.info(
                "[MOCK SMTP] Would send email to=%s subject='%s' body_preview='%s'",
                recipient,
                subject,
                body[:100],
            )
            return

        # Build the MIME message
        msg = MIMEMultipart()
        msg["From"] = self._from_addr
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        # A new connection per send_alert avoids stale-connection issues across
        # long polling intervals (e.g. hourly polls where idle timeout would
        # disconnect a persistent connection).
        with smtplib.SMTP(self._host, self._port) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(self._username, self._password)
            smtp.send_message(msg)

        logger.info(
            "Alert email sent via SMTP to=%s subject='%s'",
            recipient,
            subject,
        )
