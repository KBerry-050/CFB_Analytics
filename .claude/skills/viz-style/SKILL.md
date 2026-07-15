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
