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
3. **Deliver** — email the finished report, and/or upload it to Google Drive.

## Delivery (email)

Sent via SMTP using `smtplib` + `email.mime`. Config comes from environment
variables (loaded via `python-dotenv`, same as [[cfbd-data]]'s API key):

- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` — sender
  credentials (e.g. a Gmail app password, not the main account password).
- `REPORT_RECIPIENTS` — comma-separated list of destination addresses.

Embed everything — charts and great_tables output alike — as inline images
(`Content-ID` + `multipart/related`) rather than attachments, so the report is
readable directly in an email client without opening attachments. **Never put
raw GT `as_raw_html()` output in the message body** — email clients don't
reliably render the CSS it emits (see [[viz-style]]'s "Emailing
tables/dashboards" section). Use `send_gt_report()` from
`src/app/send_report.py`, which renders GT tables to PNG before sending.

Wrap the actual SMTP `.send_message()` call so failures are logged clearly
(recipient, subject, error) — a silent failure on a scheduled run means no one
notices the report never went out.

## Delivery (Google Drive)

An additional/alternative delivery path to email, via `src/app/upload_drive.py`.
Auth is a **service account** (not OAuth user login) so it runs unattended —
no browser consent step on a scheduled run. Config:

- `GOOGLE_SERVICE_ACCOUNT_KEY_PATH` — path to the service account's JSON key
  (convention: `credentials/google-drive-service-account.json`, gitignored —
  never commit it).
- `GOOGLE_DRIVE_FOLDER_ID` — the target Drive folder's ID.

Full one-time GCP setup steps (create project, enable Drive API, create
service account, share the target folder with its email) are documented in
`.env.example` — read those before assuming the feature is misconfigured.

Use `upload_gt_report_to_drive(filename, *tables)` for GT tables/dashboards
(same PNG-rendering path as `send_gt_report` — see [[viz-style]]) or
`upload_file_to_drive(path)` for anything already-rendered (a chart PNG, an
Excel export). Both return the file's Drive `webViewLink` — log or email that
link so whoever's watching the pipeline can confirm delivery without opening
Drive.

## Running it

- Manual run: `python src/app/weekly_report.py` (with `.venv` activated).
- Idempotent: re-running for a week that's already been sent should not
  silently re-send — either check a local "last sent" marker or require an
  explicit `--force` flag.
- Scheduling (cron/launchd/etc.) is not yet set up — when it is, document the
  actual schedule and invocation command here.

## Weekly ATS report (installed, scheduled)

A narrower, already-scheduled instance of this same pattern — separate from
`weekly_report.py` above, which is still just the planned umbrella pipeline.
`src/app/weekly_ats_report.py` emails the two `src/viz/ats_vs_ap_rank.py`
charts (AP-rank order, and performance-ranked with no x axis) for whatever
week `current_week()` (`src/data/games.py`) resolves to as "current" —
whichever week's date range contains today, which by Monday morning means the
weekend just played.

- Manual run: `python -m src.app.weekly_ats_report` (`--force` to resend a
  week already marked sent; `--year` to override the season).
- Idempotent per chart via a JSON marker at
  `src/data/output/ats_report_last_sent.json` (gitignored — it's run-state,
  not data) — updated after each chart actually sends, so if one chart's data
  isn't ready yet (a `ValueError`/`RuntimeError` from `build_ats_vs_rank_data`,
  logged and skipped rather than raised) or a send fails, the next run
  retries only what's still missing rather than resending everything.
- Scheduled via macOS launchd, Mondays at 9am: `ops/launchd/com.kbanalytix.weekly-ats-report.plist`
  (tracked in-repo; installed copy lives at
  `~/Library/LaunchAgents/com.kbanalytix.weekly-ats-report.plist`, outside
  the repo since that's where launchd requires it). Logs to
  `src/data/output/weekly_ats_report{,.err}.log`. To change the schedule,
  edit both copies (or re-copy the repo one over the installed one) and
  `launchctl unload`/`load` the installed path. To stop it entirely:
  `launchctl unload ~/Library/LaunchAgents/com.kbanalytix.weekly-ats-report.plist`.
