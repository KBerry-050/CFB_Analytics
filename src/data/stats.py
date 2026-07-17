import cfbd
import pandas as pd

from src.data.cache import cached_dataframe
from src.data.client import get_client


def _stat_value(stat: cfbd.TeamStat) -> float:
    return float(stat.stat_value.actual_instance)


def get_offense_season_stats(year: int) -> pd.DataFrame:
    """Per-team offensive totals + efficiency metrics for a season.

    Columns: team, conference, games, total_tds, total_yards, yards_per_game,
    ppa (predicted points added per play, offense), success_rate (offense).
    """

    def fetch() -> pd.DataFrame:
        with get_client() as client:
            raw_stats = cfbd.StatsApi(client).get_team_stats(year=year)
            advanced = cfbd.StatsApi(client).get_advanced_season_stats(year=year)

        totals: dict[str, dict] = {}
        for stat in raw_stats:
            row = totals.setdefault(stat.team, {"team": stat.team})
            if stat.stat_name in ("rushingTDs", "passingTDs", "totalYards", "games"):
                row[stat.stat_name] = _stat_value(stat)

        rows = []
        for team, values in totals.items():
            if "totalYards" not in values or "games" not in values or not values["games"]:
                continue
            total_tds = values.get("rushingTDs", 0) + values.get("passingTDs", 0)
            rows.append(
                {
                    "team": team,
                    "games": values["games"],
                    "total_tds": total_tds,
                    "total_yards": values["totalYards"],
                    "yards_per_game": values["totalYards"] / values["games"],
                }
            )
        totals_df = pd.DataFrame(rows)

        advanced_df = pd.DataFrame(
            [
                {
                    "team": a.team,
                    "conference": a.conference,
                    "ppa": a.offense.ppa,
                    "success_rate": a.offense.success_rate,
                }
                for a in advanced
                if a.offense is not None
            ]
        )

        return totals_df.merge(advanced_df, on="team", how="inner")

    return cached_dataframe(f"offense_season_stats_{year}", fetch)
