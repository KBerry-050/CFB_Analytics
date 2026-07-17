---
name: viz-style
description: House visual style for great_tables tables and matplotlib charts in this project — colors, fonts, team branding. Use whenever building or editing a table or chart in src/viz/.
---

# Visualization house style

All tables and charts in this project should look like they came from the same
report. Style definitions live in `src/viz/style.py` — import from there rather
than restating colors/fonts inline in individual chart/table scripts.

## Tables (great_tables)

- Use `great_tables.GT` for all tabular output — not raw pandas `.to_html()` or
  matplotlib tables.
- Team rows/cells should use each team's primary/secondary color from CFBD's
  team metadata (`TeamsApi.get_teams()` returns `color` and `alt_color`) rather
  than a fixed palette, so tables stay visually tied to the teams they describe.
- Team logos (see [[cfbd-data]]) belong in their own column via
  `GT.fmt_image()` / `GT.cols_align()`, not embedded as text.
- Keep number formatting consistent: one decimal place for rates/percentages,
  no decimals for counting stats (wins, TDs, etc.).
- Set explicit `cols_width()` on every column rather than leaving it to
  auto-size — headers like "Off Success%" or "24.4 (No. 1)"-style
  value+rank cells wrap onto two lines otherwise. Use the named constants in
  `src/viz/style.py` (`NARROW_COL_WIDTH`, `PERCENT_COL_WIDTH`,
  `RATING_COL_WIDTH`) instead of picking pixel values from scratch.
- Combining multiple GT tables into one page/export (a "dashboard")? Use
  `src/viz/render.py::combine_gt_tables()` rather than hand-rolling the
  wrapper `<div>` — a fixed `max-width` narrower than the actual table
  content will silently clip columns instead of wrapping them.
- Every table gets a source/attribution footnote via `base_table()`
  (`SOURCE_NOTE` in `src/viz/style.py`) — don't add a one-off footnote in
  individual chart/table files.
- Title and footnote sizing is also set house-wide in `base_table()`
  (`HEADING_TITLE_SIZE`, bold; `SOURCE_NOTE_SIZE`) — don't override per table.
- Any team-specific table's `tab_header(title=...)` should use
  `src/viz/style.py::team_header_title()` to put the team's logo inline
  before the title text, rather than a plain string — this is the standard
  for team dashboards/profile tables (see `src/viz/team_dashboard.py`).

## Emailing tables/dashboards

**Never email a GT table's `as_raw_html()` (or any HTML built from one)
directly as the message body.** Gmail, Outlook, and most email clients don't
reliably support the CSS grid/flexbox great_tables emits — the table degrades
badly (this was confirmed the hard way). Always render to a PNG first via
`src/viz/render.py::render_html_to_png()`, then send it as an inline image.

For the common case — one or more GT tables, straight to someone's inbox —
use `src/app/send_report.py::send_gt_report(subject, *tables)`. It combines
the tables, renders to a cropped PNG via headless Chrome, and emails it inline
in one call. Only reach for `send_html_report()` directly when the body truly
needs to be live HTML (not table/dashboard content).

## Charts (matplotlib)

- Apply the shared style via a single call at the top of each chart function,
  e.g. `plt.style.use(...)` or applying `rcParams` from `src/viz/style.py` —
  don't set fonts/colors ad hoc per chart.
- Default figure background transparent or white (not matplotlib's default
  gray) since charts get embedded in reports/emails.
- When comparing two teams, use their actual team colors (from CFBD) instead
  of matplotlib's default color cycle.
- Export at a resolution suitable for email embedding (e.g. `dpi=150`) and
  save to a consistent location under `src/app/` output or `reports/` (see
  [[weekly-automation]]) rather than scattering PNGs across the repo.

## Adding a new chart/table type

1. Put the reusable style constants/helpers in `src/viz/style.py` if they
   don't exist yet — don't duplicate color/font logic across chart files.
2. New chart/table functions go in `src/viz/`, one file per chart "type"
   (e.g. `src/viz/win_probability.py`), taking a DataFrame in and returning a
   figure/GT object out — no data-fetching inside viz code (that's
   [[cfbd-data]]'s job).
