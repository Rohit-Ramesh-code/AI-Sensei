"""
adapters/ews_scraper.py — EWS (Exchange Web Services) adapter.

Wraps exchangelib to send alert emails through a Microsoft Exchange mailbox.
Supports mock mode for offline development and CI/CD environments where a live
Exchange server is not available.

Mock mode is enabled by:
  - Passing use_mock=True to EWSAdapter() directly, OR
  - Setting the environment variable USE_MOCK_EWS=true

In mock mode, send_alert() logs the email to the Python logger instead of
sending it. No exchangelib is imported or used.

In production mode (use_mock=False), exchangelib is required:
  pip install exchangelib

Required environment variables (production only):
  EWS_SERVER      — Exchange EWS endpoint URL
  EWS_USERNAME    — Service account email / username
  EWS_PASSWORD    — Service account password
  EWS_AUTH_TYPE   — Auth type: NTLM (default), BASIC. MSAL not supported in v1.
  ALERT_RECIPIENT — Default alert recipient (used by callers; not required here)
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class EWSAdapter:
    """Sends alert emails via Microsoft Exchange Web Services.

    Parameters
    ----------
    server:
        EWS endpoint URL. Overrides EWS_SERVER env var.
    username:
        Exchange service account username. Overrides EWS_USERNAME env var.
    password:
        Exchange service account password. Overrides EWS_PASSWORD env var.
    sender_email:
        The From address used when sending. Defaults to username (service account).
    auth_type:
        Authentication type string: "NTLM" (default) or "BASIC".
        Overrides EWS_AUTH_TYPE env var.
    use_mock:
        If True, skip all Exchange setup. send_alert() logs instead of sending.
        Also activated by setting USE_MOCK_EWS=true in the environment.
    """

    def __init__(
        self,
        server: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        sender_email: Optional[str] = None,
        auth_type: Optional[str] = None,
        use_mock: bool = False,
    ) -> None:
        # Determine mock mode: kwarg OR environment variable
        env_mock = os.getenv("USE_MOCK_EWS", "false").lower() == "true"
        self._use_mock = use_mock or env_mock

        # auth_type is always stored (useful for callers and logging)
        self.auth_type: str = (
            auth_type
            or os.getenv("EWS_AUTH_TYPE", "NTLM")
        )

        if self._use_mock:
            # Mock mode — no Exchange connection needed
            logger.debug(
                "EWSAdapter initialised in mock mode "
                "(USE_MOCK_EWS=true or use_mock=True). "
                "Emails will be logged, not sent."
            )
            self._account = None
            return

        # --- Production mode: build exchangelib Account once ---
        resolved_server = server or os.getenv("EWS_SERVER")
        if not resolved_server:
            raise ValueError(
                "EWS_SERVER must be set or passed to EWSAdapter. "
                "Set the EWS_SERVER environment variable to your Exchange EWS "
                "endpoint URL (e.g. https://mail.company.com/EWS/Exchange.asmx) "
                "or enable mock mode with USE_MOCK_EWS=true for offline use."
            )

        resolved_username = username or os.getenv("EWS_USERNAME")
        resolved_password = password or os.getenv("EWS_PASSWORD")
        resolved_sender = sender_email or resolved_username

        # Import exchangelib only when we actually need it (production path).
        # This allows the module to be imported in mock mode without exchangelib
        # installed.
        try:
            from exchangelib import (  # type: ignore[import]
                Account,
                BASIC,
                Configuration,
                Credentials,
                DELEGATE,
                NTLM,
            )
        except ImportError as exc:
            raise ImportError(
                "exchangelib is required for production EWS mode. "
                "Install it with: pip install exchangelib. "
                "For offline/development use, set USE_MOCK_EWS=true instead."
            ) from exc

        auth_map = {
            "NTLM": NTLM,
            "BASIC": BASIC,
        }
        auth_type_upper = self.auth_type.upper()
        if auth_type_upper == "MSAL":
            raise NotImplementedError(
                "MSAL authentication is not supported in Phase 1. "
                "Use NTLM for on-prem Exchange 2016 or BASIC if NTLM is disabled."
            )
        if auth_type_upper not in auth_map:
            raise ValueError(
                f"Unsupported EWS_AUTH_TYPE '{self.auth_type}'. "
                f"Supported values: {list(auth_map.keys())}"
            )

        try:
            credentials = Credentials(
                username=resolved_username,
                password=resolved_password,
            )
            config = Configuration(
                server=resolved_server,
                credentials=credentials,
                auth_type=auth_map[auth_type_upper],
            )
            self._account = Account(
                primary_smtp_address=resolved_sender,
                config=config,
                autodiscover=False,
                access_type=DELEGATE,
            )
        except Exception as exc:
            raise RuntimeError(
                f"EWS connection failed (check EWS_SERVER, credentials, and "
                f"auth type): {exc}"
            ) from exc

        logger.info(
            "EWSAdapter connected to Exchange server=%s user=%s auth=%s",
            resolved_server,
            resolved_username,
            self.auth_type,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_alert(self, recipient: str, subject: str, body: str) -> None:
        """Send an alert email.

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
                "[MOCK EWS] Would send email to=%s subject='%s' body_preview='%s'",
                recipient,
                subject,
                body[:100],
            )
            return

        # Production path — exchangelib imports are already done in __init__
        from exchangelib import Mailbox, Message  # type: ignore[import]

        message = Message(
            account=self._account,
            subject=subject,
            body=body,
            to_recipients=[Mailbox(email_address=recipient)],
        )
        message.send()
        logger.info(
            "Alert email sent via EWS to=%s subject='%s'",
            recipient,
            subject,
        )
