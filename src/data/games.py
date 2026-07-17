import cfbd
import pandas as pd

from src.data.cache import cached_dataframe
from src.data.client import get_client


def get_games(year: int, week: int | None = None, season_type: str = "regular") -> pd.DataFrame:
    def fetch() -> pd.DataFrame:
        with get_client() as client:
            games = cfbd.GamesApi(client).get_games(
                year=year, week=week, season_type=season_type
            )
        return pd.DataFrame(
            [
                {
                    "id": g.id,
                    "week": g.week,
                    "start_date": g.start_date,
                    "home_team": g.home_team,
                    "home_points": g.home_points,
                    "away_team": g.away_team,
                    "away_points": g.away_points,
                    "completed": g.completed,
                }
                for g in games
            ]
        )

    cache_key = f"games_{year}" + (f"_wk{week}" if week else "_full")
    return cached_dataframe(cache_key, fetch)


def current_week(year: int) -> tuple[int, str]:
    """Return the (week, season_type) whose date range contains today, or the
    most recently started one if today is past the whole season.

    Week numbers restart at 1 for postseason, so season_type must be returned
    alongside week to disambiguate (e.g. regular week 1 vs postseason week 1).
    """
    with get_client() as client:
        calendar = cfbd.GamesApi(client).get_calendar(year=year)
    today = pd.Timestamp.now(tz="UTC")
    elapsed = [w for w in calendar if pd.Timestamp(w.start_date) <= today]
    current = elapsed[-1] if elapsed else calendar[0]
    season_type = current.season_type.value if hasattr(current.season_type, "value") else str(current.season_type)
    return current.week, season_type
