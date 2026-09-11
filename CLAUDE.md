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

### Webapp

`src/app/webapp.py` is a local-only Streamlit app for interactively browsing
any FBS team: search by name, then view its roster, schedule, and
season-entering metrics (`src/viz/team_dashboard.py`), or run the
matchup-analysis tool against any other team (`src/viz/matchup_preview.py`).
Run it with `streamlit run src/app/webapp.py`. It's a thin wiring layer only
— it embeds `great_tables` HTML straight from `src/viz` and never fetches
data itself; searching a team not yet cached hits the live CFBD API and
caches it via the normal `cached_dataframe` path (`src/data/cache.py`), so
repeat lookups are instant.

### Post-game report

`src/data/postgame.py` + `src/viz/postgame_report.py` build a single-page
"broadcast card" summarizing one finished game: both teams and marks, the
quarter-by-quarter score, a play-by-play win-probability chart, dueling
traditional and advanced box-score bars, per-quarter momentum, a drive-flow
ribbon, and the players who moved the game most by PPA. Run it with
`python -m src.viz.postgame_report`, or
`render_postgame_report(game_id, out_stem)` for any completed game
(`resolve_game_id(year, week, team)` looks up the id from names). Output is a
standalone HTML page plus a 2x PNG in `src/viz/output/`. To email one,
`send_postgame_report(game_id)` in `src/app/send_report.py` renders it and
sends the PNG inline — like `send_gt_report`, never the raw HTML.

It's the one place in `src/viz/` that deliberately ignores the `viz-style`
house style — no `great_tables`, no light striped tables. It's a dark,
hand-built HTML + inline-SVG poster with team-branded color, rendered through
`render_html_to_png` like everything else. Don't refactor it toward
`src/viz/style.py`; the only thing it borrows is the source/attribution
wording.

Everything it needs is cached per game id, so a rebuilt report costs zero API
calls. It draws on the endpoints only meaningful after a game is final —
`get_advanced_box_score` (havoc, field position, scoring opportunities,
rushing detail, and efficiency split by quarter), `get_win_probability` joined
to `get_plays` for a real game-clock axis, `get_drives`, `get_game_team_stats`,
`get_game_player_stats`, plus betting lines, weather, Elo and polls for
pre-game context.

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

### Field viewer

`src/app/game_field_viewer.py` is a local-only Streamlit app
(`streamlit run src/app/game_field_viewer.py`) that draws one team's
offensive plays for a game on an actual field diagram — a line from each
play's starting to ending field position, colored by gain/loss, with the
ball-carrier's headshot at the endpoint — filterable by quarter and player.
Parameterized by team/year/week, not hardcoded to one game.

The field drawing itself lives in `src/viz/field_plot.py`
(`build_field_figure`). Its data comes from
`get_offensive_plays_with_field_position()` in `src/data/postgame.py`, which
attributes each rush/reception to a ball-carrier by regex-parsing the jersey
number out of CFBD's play-text description (`_ball_carrier_plays()`) — CFBD's
play-by-play carries no structured player field. That attribution is
best-effort: an unparseable play is skipped rather than raising, with the
skipped count surfaced via the DataFrame's `.attrs["unparsed_count"]` so a
caller can sanity-check it.

Player names/positions/photos aren't available from CFBD at all, so they come
from a hand-curated roster file per team/season,
`src/data/rosters/{team}_{year}.json` (slug from `roster_slug()` in
`src/data/teams.py`; see `load_roster_lookup()`'s docstring for the file
shape). Add a team's next season the same way — there's no live-scraping
path by design, since scraping a specific roster page's HTML in a deployed
app is fragile. A jersey number missing from the roster file falls back to
CFBD's own abbreviated name with no photo, rather than failing; a missing
roster file entirely is surfaced as an in-app notice rather than only
inferred play-by-play from a wall of bare jersey numbers.

## Secrets

`CFBD_API_KEY` and SMTP credentials are read from environment variables via
`python-dotenv` (`.env`, gitignored). `.env.example` documents the required
variables — keep it in sync when adding new config.
