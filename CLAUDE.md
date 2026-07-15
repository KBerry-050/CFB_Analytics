# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A college football analytics project: pull data from the CollegeFootballData.com
(CFBD) API, build styled tables/charts, and email a weekly report.

## Setup

```
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in CFBD_API_KEY, SMTP_*, REPORT_RECIPIENTS
```

Python is managed via a local `.venv` (Python 3.12, created with homebrew's
`python@3.12`). Activate it before running anything in `src/`.

## Architecture

The pipeline is three stages, each owned by a skill in `.claude/skills/`:

- **`src/data/`** — CFBD API access and cached data (parquet/CSV, logos).
  See `.claude/skills/cfbd-data/SKILL.md` for auth and endpoint conventions.
- **`src/viz/`** — table (great_tables) and chart (matplotlib) rendering,
  with shared house style in `src/viz/style.py`. See
  `.claude/skills/viz-style/SKILL.md`.
- **`src/app/`** — the weekly pipeline entry point
  (`src/app/weekly_report.py`) that chains fetch → build → email. See
  `.claude/skills/weekly-automation/SKILL.md`.

Data flows one direction: `src/data` → `src/viz` → `src/app`. Viz code takes
DataFrames in and returns figures/tables out — it does not fetch data itself.
App code doesn't build tables/charts directly — it calls into `src/viz`.

`notebooks/` is for exploratory analysis only, not production pipeline code.

## Secrets

`CFBD_API_KEY` and SMTP credentials are read from environment variables via
`python-dotenv` (`.env`, gitignored). `.env.example` documents the required
variables — keep it in sync when adding new config.
