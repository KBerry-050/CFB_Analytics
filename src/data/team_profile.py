from typing import Callable

import cfbd
import pandas as pd

from src.data.cache import cached_dataframe
from src.data.client import get_client


def _slug(team: str) -> str:
    return team.lower().replace(" ", "_").replace("&", "and")


def _records_to_df(records: list) -> pd.DataFrame:
    return pd.json_normalize([r.to_dict() for r in records])


def _cached_team_records(category: str, team: str, year: int, fetch_records: Callable[[], list]) -> pd.DataFrame:
    """Cache a team+year API pull as a flattened parquet, keyed by category/team/year."""

    def fetch() -> pd.DataFrame:
        return _records_to_df(fetch_records())

    return cached_dataframe(f"{category}_{_slug(team)}_{year}", fetch)


# --- team & roster --------------------------------------------------------


def get_team_roster(team: str, year: int) -> pd.DataFrame:
    def fetch_records():
        with get_client() as client:
            return cfbd.TeamsApi(client).get_roster(team=team, year=year)

    return _cached_team_records("roster", team, year, fetch_records)


def get_all_teams_talent(year: int) -> pd.DataFrame:
    """Recruiting talent composite for every FBS team in a season. The
    endpoint isn't team-filterable, so this full table is what's actually
    cached; `get_team_talent` just slices it."""

    def fetch() -> pd.DataFrame:
        with get_client() as client:
            records = cfbd.TeamsApi(client).get_talent(year=year)
        return _records_to_df(records)

    return cached_dataframe(f"talent_{year}", fetch)


def get_team_talent(team: str, year: int) -> pd.DataFrame:
    df = get_all_teams_talent(year)
    return df[df["team"] == team].reset_index(drop=True)


def get_team_coaches(team: str, min_year: int, max_year: int) -> pd.DataFrame:
    """One row per coach-season for the team, across the given year range."""

    def fetch() -> pd.DataFrame:
        with get_client() as client:
            coaches = cfbd.CoachesApi(client).get_coaches(team=team, min_year=min_year, max_year=max_year)
        rows = []
        for coach in coaches:
            for season in coach.seasons:
                rows.append({"first_name": coach.first_name, "last_name": coach.last_name, **season.to_dict()})
        return pd.DataFrame(rows)

    return cached_dataframe(f"coaches_{_slug(team)}_{min_year}_{max_year}", fetch)


# --- schedule & results -----------------------------------------------------


def get_team_schedule(team: str, year: int) -> pd.DataFrame:
    def fetch_records():
        with get_client() as client:
            return cfbd.GamesApi(client).get_games(year=year, team=team)

    return _cached_team_records("schedule", team, year, fetch_records)


def get_team_game_stats(team: str, year: int) -> pd.DataFrame:
    """One row per team per game (so both sides of each matchup are present),
    with each box-score category (`totalYards`, `possessionTime`, ...) pivoted
    into its own column instead of a nested category/value list."""

    def fetch() -> pd.DataFrame:
        with get_client() as client:
            games = cfbd.GamesApi(client).get_game_team_stats(year=year, team=team)
        rows = []
        for game in games:
            for team_stats in game.teams:
                row = {
                    "game_id": game.id,
                    "team_id": team_stats.team_id,
                    "team": team_stats.team,
                    "conference": team_stats.conference,
                    "home_away": team_stats.home_away,
                    "points": team_stats.points,
                }
                row.update({s.category: s.stat for s in team_stats.stats})
                rows.append(row)
        return pd.DataFrame(rows)

    return cached_dataframe(f"game_team_stats_{_slug(team)}_{year}", fetch)


def get_team_records(team: str, year: int) -> pd.DataFrame:
    def fetch_records():
        with get_client() as client:
            return cfbd.GamesApi(client).get_records(year=year, team=team)

    return _cached_team_records("records", team, year, fetch_records)


def get_all_teams_records(year: int) -> pd.DataFrame:
    """Season win/loss records for every team CFBD tracks (all classifications
    — filter to FBS yourself, e.g. by inner-joining against `get_teams`).
    One unfiltered API call, cached once per year."""

    def fetch() -> pd.DataFrame:
        with get_client() as client:
            records = cfbd.GamesApi(client).get_records(year=year)
        return _records_to_df(records)

    return cached_dataframe(f"all_records_{year}", fetch)


# --- efficiency / advanced metrics ------------------------------------------


def get_team_advanced_season_stats(team: str, year: int) -> pd.DataFrame:
    def fetch_records():
        with get_client() as client:
            return cfbd.StatsApi(client).get_advanced_season_stats(year=year, team=team)

    return _cached_team_records("advanced_season_stats", team, year, fetch_records)


def get_team_advanced_game_stats(team: str, year: int) -> pd.DataFrame:
    def fetch_records():
        with get_client() as client:
            return cfbd.StatsApi(client).get_advanced_game_stats(year=year, team=team)

    return _cached_team_records("advanced_game_stats", team, year, fetch_records)


def get_team_havoc_stats(team: str, year: int) -> pd.DataFrame:
    def fetch_records():
        with get_client() as client:
            return cfbd.StatsApi(client).get_game_havoc_stats(year=year, team=team)

    return _cached_team_records("havoc_stats", team, year, fetch_records)


def get_team_adjusted_season_stats(team: str, year: int) -> pd.DataFrame:
    def fetch_records():
        with get_client() as client:
            return cfbd.AdjustedMetricsApi(client).get_adjusted_team_season_stats(year=year, team=team)

    return _cached_team_records("adjusted_season_stats", team, year, fetch_records)


def get_team_ppa_by_team(team: str, year: int) -> pd.DataFrame:
    def fetch_records():
        with get_client() as client:
            return cfbd.MetricsApi(client).get_predicted_points_added_by_team(year=year, team=team)

    return _cached_team_records("ppa_by_team", team, year, fetch_records)


def get_team_pregame_win_probabilities(team: str, year: int) -> pd.DataFrame:
    """Pregame win probability + spread for each of the team's games.
    Columns: season, seasonType, week, gameId, homeTeam, awayTeam, spread,
    homeWinProbability — the caller flips `homeWinProbability` for `team`'s
    own perspective when it played away."""
    def fetch_records():
        with get_client() as client:
            return cfbd.MetricsApi(client).get_pregame_win_probabilities(year=year, team=team)

    return _cached_team_records("pregame_win_probabilities", team, year, fetch_records)


# --- ratings -----------------------------------------------------------------


def get_team_ratings(team: str, year: int) -> pd.DataFrame:
    """SP+, SRS, FPI (season-level) and Elo (season-end) merged into one row."""

    def fetch() -> pd.DataFrame:
        with get_client() as client:
            ratings_api = cfbd.RatingsApi(client)
            sp = _records_to_df(ratings_api.get_sp(year=year, team=team))
            srs = _records_to_df(ratings_api.get_srs(year=year, team=team))
            fpi = _records_to_df(ratings_api.get_fpi(year=year, team=team))
            elo = _records_to_df(ratings_api.get_elo(year=year, team=team))

        merged = pd.DataFrame({"team": [team], "year": [year]})
        for prefix, block in (("sp", sp), ("srs", srs), ("fpi", fpi), ("elo", elo)):
            if block.empty:
                continue
            # get_sp always includes a synthetic "nationalAverages" row alongside the
            # requested team's; drop anything that isn't an exact team match.
            block = block[block["team"] == team]
            if block.empty:
                continue
            merged = pd.concat([merged, block.tail(1).add_prefix(f"{prefix}.").reset_index(drop=True)], axis=1)
        return merged

    return cached_dataframe(f"ratings_{_slug(team)}_{year}", fetch)


# --- betting -------------------------------------------------------------


def get_team_betting_lines(team: str, year: int) -> pd.DataFrame:
    """One row per provider per game (a game can have several sportsbook lines)."""

    def fetch() -> pd.DataFrame:
        with get_client() as client:
            games = cfbd.BettingApi(client).get_lines(year=year, team=team)
        game_dicts = [g.to_dict() for g in games]
        if not game_dicts:
            return pd.DataFrame()
        return pd.json_normalize(
            game_dicts,
            record_path="lines",
            meta=["id", "season", "week", "homeTeam", "awayTeam", "homeScore", "awayScore"],
            meta_prefix="game.",
            record_prefix="line.",
        )

    return cached_dataframe(f"betting_lines_{_slug(team)}_{year}", fetch)


# --- players -----------------------------------------------------------------


def get_team_player_season_stats(team: str, year: int) -> pd.DataFrame:
    def fetch_records():
        with get_client() as client:
            return cfbd.StatsApi(client).get_player_season_stats(year=year, team=team)

    return _cached_team_records("player_season_stats", team, year, fetch_records)


def get_team_player_usage(team: str, year: int) -> pd.DataFrame:
    def fetch_records():
        with get_client() as client:
            return cfbd.PlayersApi(client).get_player_usage(year=year, team=team)

    return _cached_team_records("player_usage", team, year, fetch_records)


def get_team_returning_production(team: str, year: int) -> pd.DataFrame:
    def fetch_records():
        with get_client() as client:
            return cfbd.PlayersApi(client).get_returning_production(year=year, team=team)

    return _cached_team_records("returning_production", team, year, fetch_records)


def get_all_teams_returning_production(year: int) -> pd.DataFrame:
    """Returning production (% of last season's PPA production back on the
    roster) for every team — the standard roster-continuity metric in CFB
    analytics. One unfiltered API call, cached once per year."""

    def fetch() -> pd.DataFrame:
        with get_client() as client:
            records = cfbd.PlayersApi(client).get_returning_production(year=year)
        return _records_to_df(records)

    return cached_dataframe(f"all_returning_production_{year}", fetch)


def get_all_transfers(year: int) -> pd.DataFrame:
    """Every transfer portal entry for a season (all origins/destinations).
    The endpoint isn't team-filterable, so this full table is what's actually
    cached; `get_team_transfers` just slices it."""

    def fetch() -> pd.DataFrame:
        with get_client() as client:
            records = cfbd.PlayersApi(client).get_transfer_portal(year=year)
        return _records_to_df(records)

    return cached_dataframe(f"transfer_portal_{year}", fetch)


def get_team_transfers(team: str, year: int) -> pd.DataFrame:
    """Transfer portal entries where the team is the origin or destination."""
    df = get_all_transfers(year)
    return df[(df["origin"] == team) | (df["destination"] == team)].reset_index(drop=True)


# --- recruiting ----------------------------------------------------------


def get_team_recruits(team: str, year: int) -> pd.DataFrame:
    def fetch_records():
        with get_client() as client:
            return cfbd.RecruitingApi(client).get_recruits(year=year, team=team)

    return _cached_team_records("recruits", team, year, fetch_records)


def get_team_recruiting_ranking(team: str, year: int) -> pd.DataFrame:
    def fetch_records():
        with get_client() as client:
            return cfbd.RecruitingApi(client).get_team_recruiting_rankings(year=year, team=team)

    return _cached_team_records("recruiting_ranking", team, year, fetch_records)


# --- profile assembly ------------------------------------------------------

_PROFILE_BUILDERS: dict[str, Callable[[str, int], pd.DataFrame]] = {
    "roster": get_team_roster,
    "talent": get_team_talent,
    "schedule": get_team_schedule,
    "game_team_stats": get_team_game_stats,
    "records": get_team_records,
    "advanced_season_stats": get_team_advanced_season_stats,
    "advanced_game_stats": get_team_advanced_game_stats,
    "havoc_stats": get_team_havoc_stats,
    "adjusted_season_stats": get_team_adjusted_season_stats,
    "ppa_by_team": get_team_ppa_by_team,
    "pregame_win_probabilities": get_team_pregame_win_probabilities,
    "ratings": get_team_ratings,
    "betting_lines": get_team_betting_lines,
    "player_season_stats": get_team_player_season_stats,
    "player_usage": get_team_player_usage,
    "returning_production": get_team_returning_production,
    "transfers": get_team_transfers,
    "recruits": get_team_recruits,
    "recruiting_ranking": get_team_recruiting_ranking,
}


def build_team_profile(team: str, years: list[int]) -> dict[str, pd.DataFrame]:
    """Season + game level data for `team` across `years`, one DataFrame per
    category (concatenated across years). Coaches are fetched once over the
    full year range since the endpoint takes min/max year rather than a single
    season. Play-by-play/drive data is intentionally excluded — see
    `get_team_plays` / `get_team_drives` for on-demand granular pulls."""
    profile: dict[str, pd.DataFrame] = {}
    for category, builder in _PROFILE_BUILDERS.items():
        frames = [builder(team, year) for year in years]
        profile[category] = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    profile["coaches"] = get_team_coaches(team, min(years), max(years))
    return profile


# --- on-demand granular pulls (not part of the default profile) ------------


def get_team_plays(team: str, year: int, week: int) -> pd.DataFrame:
    """Play-by-play for one team/year/week. Cached per week so pulling a full
    season is just N cheap incremental calls instead of one huge one."""

    def fetch_records():
        with get_client() as client:
            return cfbd.PlaysApi(client).get_plays(year=year, week=week, team=team)

    return _cached_team_records(f"plays_wk{week}", team, year, fetch_records)


def get_team_drives(team: str, year: int) -> pd.DataFrame:
    def fetch_records():
        with get_client() as client:
            return cfbd.DrivesApi(client).get_drives(year=year, team=team)

    return _cached_team_records("drives", team, year, fetch_records)


if __name__ == "__main__":
    profile = build_team_profile("Notre Dame", [2024, 2025])
    for category, df in profile.items():
        print(f"{category}: {df.shape}")
