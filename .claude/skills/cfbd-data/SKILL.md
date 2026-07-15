---
name: cfbd-data
description: Pull data from the CollegeFootballData.com (cfbd) API and fetch ESPN team logos. Use whenever a task needs game/team/player/stat data or a team's logo image.
---

# CFBD data access

## Auth

The CFBD API key lives in the `CFBD_API_KEY` environment variable, loaded from a
`.env` file at the project root via `python-dotenv`. Never hardcode the key or
commit `.env` (it's gitignored — only `.env.example` is tracked).

```python
import os
from dotenv import load_dotenv
import cfbd

load_dotenv()

configuration = cfbd.Configuration(
    access_token=os.environ["CFBD_API_KEY"]
)
```

If `CFBD_API_KEY` is unset, raise immediately with a message pointing at
`.env.example` rather than letting the API call fail with an opaque 401.

## Fetching data

Use the official `cfbd` Python client (add to `requirements.txt` if not already
present) rather than hand-rolled `requests` calls — it has typed models for
games, teams, rosters, stats, rankings, betting lines, etc.

```python
with cfbd.ApiClient(configuration) as api_client:
    games_api = cfbd.GamesApi(api_client)
    games = games_api.get_games(year=2026, week=5, season_type="regular")
```

Common endpoints used in this project:
- `GamesApi` — schedules, scores, results
- `TeamsApi` — team metadata (conference, colors, logos list)
- `StatsApi` — team/player season and game stats
- `RankingsApi` — AP/Coaches/CFP poll rankings
- `BettingApi` — lines/spreads if needed for analysis

Cache raw API responses to `src/data/` (as parquet/CSV) when iterating locally
so repeated runs don't re-hit the API — the free tier has rate limits.

## ESPN team logos

CFBD's `TeamsApi.get_teams()` response includes a `logos` field with ESPN CDN
URLs directly — prefer that over constructing URLs by hand:

```python
teams = TeamsApi(api_client).get_teams(year=2026)
logo_url = teams[0].logos[0]  # highest-res logo first
```

Download and cache logos locally (e.g. `src/data/logos/{team_id}.png`) instead
of re-fetching from ESPN on every visualization build.
