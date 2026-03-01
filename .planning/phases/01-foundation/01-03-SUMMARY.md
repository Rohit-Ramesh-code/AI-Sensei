---
phase: 01-foundation
plan: "03"
subsystem: adapter
tags: [smtp, smtplib, email, mock, outlook, office365, starttls]

# Dependency graph
requires: []
provides:
  - "SMTPAdapter class in adapters/smtp_adapter.py with send_alert() method"
  - "Mock mode for offline development (no Outlook account required)"
  - "SMTP_HOST defaults to smtp.office365.com for personal Outlook / Office 365"
  - "10 passing unit tests covering all mock behaviours and error paths"
affects: [agents/communicator.py, agents/supervisor.py]

# Tech tracking
tech-stack:
  added: [smtplib (stdlib), email.mime (stdlib)]
  removed: [exchangelib]
  patterns:
    - "New-connection-per-send: SMTP connection opened fresh per send_alert() call — avoids stale connections across long polling intervals"
    - "Mock-first adapter: env var or kwarg activates mock; tests never require live services"
    - "stdlib-only: no third-party library needed for email delivery"

key-files:
  created:
    - adapters/smtp_adapter.py
    - tests/test_smtp_adapter.py
  deleted:
    - adapters/ews_scraper.py
    - tests/test_ews_adapter.py
  modified:
    - requirements.txt
    - .env.example
    - CLAUDE.md

key-decisions:
  - "Switched from exchangelib/EWS to smtplib STARTTLS — personal Outlook account works directly, no Exchange server needed"
  - "New SMTP connection per send_alert() — avoids idle-timeout issues across hourly polling intervals"
  - "SMTP_HOST defaults to smtp.office365.com so users with personal Outlook only need to set USERNAME and PASSWORD"
  - "App Password guidance in .env.example and plan — required when MFA is enabled on Outlook account"
  - "All stdlib: smtplib, email.mime — no new package added to requirements.txt"

patterns-established:
  - "Mock-first adapters: all external adapters must support mock mode via use_mock kwarg and USE_MOCK_<ADAPTER> env var"

requirements-completed: [ALRT-01]

# Metrics
duration: rewrite
completed: 2026-03-01
---

# Phase 1 Plan 03: SMTP Adapter Summary

**SMTPAdapter class using Python's built-in smtplib for Outlook email alerts, with mock mode — 10 unit tests pass without a live account**

## Performance

- **Duration:** rewrite (EWS → SMTP migration)
- **Completed:** 2026-03-01
- **Tasks:** 1 of 2 (Task 2 is checkpoint:human-verify — awaiting live Outlook test)
- **Files modified:** 7

## Accomplishments
- SMTPAdapter class implemented with send_alert(recipient, subject, body) API
- Mock mode activated by use_mock=True kwarg or USE_MOCK_SMTP=true env var; logs email to Python logger, never opens a connection
- Production mode uses smtplib STARTTLS: ehlo → starttls → login → send_message
- SMTP_HOST defaults to smtp.office365.com; SMTP_PORT defaults to 587
- Clear ValueError raised when SMTP_USERNAME or SMTP_PASSWORD are missing in production mode
- No third-party library required — smtplib and email.mime are Python stdlib
- 10 unit tests written and passing
- exchangelib removed from requirements.txt; EWS files deleted

## Files Created/Modified
- `adapters/smtp_adapter.py` — SMTPAdapter class with send_alert() and mock mode
- `tests/test_smtp_adapter.py` — 10 unit tests covering mock mode and error paths
- `requirements.txt` — removed exchangelib (no longer needed)
- `.env.example` — replaced EWS vars with SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM, USE_MOCK_SMTP
- `CLAUDE.md` — updated architecture, env vars, and implementation order
- ~~`adapters/ews_scraper.py`~~ — deleted
- ~~`tests/test_ews_adapter.py`~~ — deleted

## Decisions Made
- smtplib chosen over exchangelib: works with personal Outlook directly, no Exchange server or IT involvement
- New SMTP connection opened per send_alert() rather than a persistent connection — avoids stale-connection errors from long idle periods between hourly polls
- SMTP_HOST defaults to smtp.office365.com so most users only need to set two env vars (USERNAME + PASSWORD)

## User Setup Required

**To send live email alerts, set these environment variables in `.env`:**

| Variable | Description | Required |
|----------|-------------|----------|
| `SMTP_USERNAME` | Your Outlook email address (e.g. you@outlook.com) | Yes |
| `SMTP_PASSWORD` | Your Outlook password or App Password | Yes |
| `ALERT_RECIPIENT` | Email that receives toner alerts | Yes |
| `SMTP_HOST` | SMTP server (default: smtp.office365.com) | No |
| `SMTP_PORT` | SMTP port (default: 587) | No |
| `SMTP_FROM` | From address (default: same as SMTP_USERNAME) | No |

**If MFA is enabled:** Generate an App Password at https://account.microsoft.com/security → App passwords, and use that as `SMTP_PASSWORD`.

Verify with:
```bash
python -c "
from dotenv import load_dotenv; load_dotenv()
from adapters.smtp_adapter import SMTPAdapter
import os
adapter = SMTPAdapter()
adapter.send_alert(
    recipient=os.getenv('ALERT_RECIPIENT'),
    subject='[Sentinel Test] SMTP Adapter Verification',
    body='This is a test email from Project Sentinel Phase 1.'
)
print('Email sent successfully')
"
```

## Next Phase Readiness
- SMTPAdapter is ready for use by `agents/communicator.py` (Phase 2)
- Mock mode means communicator.py can be developed and tested without Outlook access
- Live Outlook send test pending human verification (Task 2 checkpoint)

---
*Phase: 01-foundation*
*Completed: 2026-03-01*
