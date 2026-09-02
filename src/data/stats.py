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


def get_qb_season_efficiency(year: int, min_plays: int = 100) -> pd.DataFrame:
    """Season-level passing efficiency for every FBS QB with at least
    `min_plays` recorded plays that season: completion %, yards/attempt,
    PPA/play (overall and passing-specific), and counting stats — for
    scatter/leaderboard use across the whole league in one call.
    """

    def fetch() -> pd.DataFrame:
        with get_client() as client:
            ppa = cfbd.MetricsApi(client).get_predicted_points_added_by_player_season(
                year=year, position="QB", threshold=min_plays
            )
            passing = cfbd.StatsApi(client).get_player_season_stats(year=year, category="passing")

        ppa_df = pd.DataFrame(
            [
                {
                    "player_id": p.id,
                    "player": p.name,
                    "team": p.team,
                    "conference": p.conference,
                    "ppa_per_play": p.average_ppa.all,
                    "passing_ppa_per_play": p.average_ppa.var_pass,
                    "total_ppa": p.total_ppa.all,
                }
                for p in ppa
            ]
        )

        passing_df = (
            pd.DataFrame([{"player_id": s.player_id, "stat_type": s.stat_type, "stat": s.stat} for s in passing])
            .pivot_table(index="player_id", columns="stat_type", values="stat", aggfunc="first")
            .reset_index()
            .rename(
                columns={
                    "ATT": "attempts",
                    "COMPLETIONS": "completions",
                    "PCT": "completion_pct",
                    "YPA": "yards_per_attempt",
                    "YDS": "yards",
                    "TD": "tds",
                    "INT": "interceptions",
                }
            )
        )
        stat_cols = ["attempts", "completions", "completion_pct", "yards_per_attempt", "yards", "tds", "interceptions"]
        for col in stat_cols:
            if col in passing_df.columns:
                passing_df[col] = pd.to_numeric(passing_df[col], errors="coerce")

        return ppa_df.merge(passing_df, on="player_id", how="inner")

    return cached_dataframe(f"qb_season_efficiency_{year}_min{min_plays}", fetch)
