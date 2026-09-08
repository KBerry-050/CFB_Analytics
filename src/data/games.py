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


def get_week_betting_lines(year: int, week: int, season_type: str = "regular") -> pd.DataFrame:
    """Consensus closing spread and over/under for every game in a week.

    The spread is the median across books rather than any one provider's
    number, so a single outlier doesn't define the line. It stays
    home-relative, which is how CFBD reports it: negative means the home team
    was favored, so the home team's expected margin is `-spread`.

    Columns: id, home_team, away_team, spread, over_under, books.
    """

    def fetch() -> pd.DataFrame:
        with get_client() as client:
            games = cfbd.BettingApi(client).get_lines(
                year=year, week=week, season_type=season_type
            )
        rows = []
        for game in games:
            spreads = [line.spread for line in game.lines if line.spread is not None]
            totals = [line.over_under for line in game.lines if line.over_under is not None]
            rows.append(
                {
                    "id": game.id,
                    "home_team": game.home_team,
                    "away_team": game.away_team,
                    "spread": float(pd.Series(spreads).median()) if spreads else None,
                    "over_under": float(pd.Series(totals).median()) if totals else None,
                    "books": len(spreads),
                }
            )
        return pd.DataFrame(rows)

    return cached_dataframe(f"betting_lines_{year}_{season_type}_wk{week}", fetch)


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
