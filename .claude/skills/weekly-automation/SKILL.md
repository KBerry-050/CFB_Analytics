---
name: weekly-automation
description: The weekly pipeline that pulls the latest week's CFB data, builds the report, and emails it out. Use when building, running, or debugging the weekly automated report.
---

# Weekly automation pipeline

Entry point: `src/app/weekly_report.py`. The pipeline has three stages, each
building on the corresponding skill:

1. **Fetch** — pull the current week's games/stats via [[cfbd-data]]. Determine
   "current week" from CFBD's `/calendar` endpoint rather than hardcoding a
   week number, since the script should be safe to (re)run any time.
2. **Build** — render tables/charts via [[viz-style]] into a single report
   artifact (e.g. one combined HTML file, or a set of PNGs assembled into an
   HTML email body).
3. **Deliver** — email the finished report.

## Delivery (email)

Sent via SMTP using `smtplib` + `email.mime`. Config comes from environment
variables (loaded via `python-dotenv`, same as [[cfbd-data]]'s API key):

- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` — sender
  credentials (e.g. a Gmail app password, not the main account password).
- `REPORT_RECIPIENTS` — comma-separated list of destination addresses.

Embed charts as inline images (`Content-ID` + `multipart/related`) rather than
attachments, and inline the great_tables output as HTML in the message body,
so the report is readable directly in an email client without opening
attachments.

Wrap the actual SMTP `.send_message()` call so failures are logged clearly
(recipient, subject, error) — a silent failure on a scheduled run means no one
notices the report never went out.

## Running it

- Manual run: `python src/app/weekly_report.py` (with `.venv` activated).
- Idempotent: re-running for a week that's already been sent should not
  silently re-send — either check a local "last sent" marker or require an
  explicit `--force` flag.
- Scheduling (cron/launchd/etc.) is not yet set up — when it is, document the
  actual schedule and invocation command here.
