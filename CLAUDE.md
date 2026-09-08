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

### Game film sync

`src/data/game_film.py` and `src/data/scoreboard_ocr.py` connect local game
film to CFBD play-by-play data: given a video timestamp, find the matching
play. Film lives in the gitignored `game_film/{team}_{year}/wk{week}_{opponent}/`
directory (large binaries, never committed) alongside a tracked
`game_film/sync_anchors.csv`. Two sync paths:

- Manual — mark a few known video-timestamp/game-clock pairs per video in
  `sync_anchors.csv`; `estimate_game_clock()` interpolates between them.
- Automatic — `scoreboard_ocr.py` OCRs the broadcast's on-screen clock via
  Apple's Vision framework (`build_video_play_sync()`), so no manual anchors
  are needed for film with a readable overlay. This path is macOS-only
  (`pyobjc-framework-Vision`/`Quartz` in `requirements.txt`).

`src/viz/game_film_review.py` renders a sync's output (a `build_video_play_sync`
DataFrame) into a standalone HTML page pairing each matched play window with
its source video frame(s), for visually QA'ing the OCR/match before trusting
it — `python -m src.viz.game_film_review --play-sync-csv ... --frame-cache-dir
... --fps ...`.

Not yet built: anything player-tracking/CV related — this only maps a video
timestamp to a play, not what happened in the frame.

## Secrets

`CFBD_API_KEY` and SMTP credentials are read from environment variables via
`python-dotenv` (`.env`, gitignored). `.env.example` documents the required
variables — keep it in sync when adding new config.
