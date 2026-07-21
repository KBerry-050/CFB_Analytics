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


def get_all_teams_schedule(year: int) -> pd.DataFrame:
    """Every FBS game in a season (`GamesApi.get_games` isn't team-filterable
    the same call still needs a scope, so this passes classification="fbs"
    instead). One call, cached once per year — use for anything needing the
    full schedule (e.g. league-wide scoring ranks) rather than looping
    `get_team_schedule` per team."""

    def fetch() -> pd.DataFrame:
        with get_client() as client:
            games = cfbd.GamesApi(client).get_games(year=year, classification="fbs")
        return _records_to_df(games)

    return cached_dataframe(f"all_schedule_fbs_{year}", fetch)


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


def get_team_season_totals(team: str, year: int) -> pd.DataFrame:
    """Season-total team stats (yards, TDs, completions, possession time,
    ...), pivoted from the API's long category/value list into one wide row.
    Includes the team's own totals only (CFBD also returns "...Opponent"
    categories — stats the team allowed — which are left in as-is if present)."""

    def fetch() -> pd.DataFrame:
        with get_client() as client:
            stats = cfbd.StatsApi(client).get_team_stats(year=year, team=team)
        row = {"team": team, "year": year}
        for s in stats:
            row[s.stat_name] = float(s.stat_value.actual_instance)
        return pd.DataFrame([row])

    return cached_dataframe(f"season_totals_{_slug(team)}_{year}", fetch)


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


def _flatten_player_overview(overview_dict: dict) -> dict:
    row = {
        "player": overview_dict["name"],
        "team": overview_dict["team"],
        "position": overview_dict["position"],
        "games": overview_dict["games"],
    }
    for category in overview_dict["boxScoreStats"]["categories"]:
        for stat in category["stats"]:
            row[f"{category['name']}.{stat['name']}"] = stat["value"]
    for scope in ("average", "total"):
        for key, value in overview_dict["ppa"][scope].items():
            row[f"ppa.{scope}.{key}"] = value
    for key, value in overview_dict["usage"].items():
        row[f"usage.{key}"] = value
    return row


def get_player_season_overview(player_name: str, team: str, year: int) -> pd.DataFrame:
    """Box-score stats (passing/rushing/etc., flattened out of their nested
    category/stat lists) plus PPA and usage splits for one named player's
    season. `PlayersApi.get_player_season_overview` needs a numeric player
    id, not a name, so this looks the player up first via the team's
    player-season stats."""

    def fetch() -> pd.DataFrame:
        season_stats = get_team_player_season_stats(team, year)
        matches = season_stats[season_stats["player"] == player_name]
        if matches.empty:
            raise ValueError(f"No player named {player_name!r} found for {team} in {year}.")
        player_id = int(matches["playerId"].iloc[0])
        with get_client() as client:
            overview = cfbd.PlayersApi(client).get_player_season_overview(player_id=player_id, year=year)
        return pd.DataFrame([_flatten_player_overview(overview.to_dict())])

    return cached_dataframe(f"player_overview_{_slug(team)}_{_slug(player_name)}_{year}", fetch)


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
    "season_totals": get_team_season_totals,
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


def get_team_play_stats(team: str, year: int) -> pd.DataFrame:
    """Per-player, per-play stat rows (Completion, Incompletion, Rush, Sack
    Taken, Interception Thrown, Touchdown, ...) for every game the team
    played that season. `PlaysApi.get_play_stats` requires a week filter, so
    this loops over the team's actual scheduled weeks (via
    `get_team_schedule`) rather than guessing a week range; cached once per
    team/year as a single combined table."""

    def fetch() -> pd.DataFrame:
        weeks = sorted(get_team_schedule(team, year)["week"].unique().tolist())
        frames = []
        with get_client() as client:
            plays_api = cfbd.PlaysApi(client)
            for week in weeks:
                stats = plays_api.get_play_stats(year=year, week=int(week), team=team)
                if stats:
                    frames.append(_records_to_df(stats))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    return cached_dataframe(f"play_stats_{_slug(team)}_{year}", fetch)


def get_qb_pass_chart_data(player_name: str, team: str, year: int) -> pd.DataFrame:
    """Every pass attempt thrown by `player_name` in a season, classified
    into complete/incomplete/interception with field position, receiver,
    touchdown flag, and game situation (quarter/clock/down/distance) — the
    dataset behind the interactive pass-chart artifact. Built from
    `get_team_play_stats` (not separately cached — cheap to recompute from
    that already-cached table).

    Field position is line-of-scrimmage only; CFBD has no throw-depth or
    lateral (hash) data, so `end_pos` reflects yards gained (including YAC),
    not a real target location — see the pass-chart artifact's own caption.
    """
    stats = get_team_play_stats(team, year)
    passer = stats[stats["athleteName"] == player_name]
    if passer.empty:
        raise ValueError(f"No play-stats rows for {player_name!r} on {team} in {year}.")

    rows = []
    for play_id, group in passer.groupby("playId"):
        types = set(group["statType"])
        first = group.iloc[0]

        if "Interception Thrown" in types:
            outcome = "interception"
        elif "Completion" in types:
            outcome = "complete"
        elif "Incompletion" in types:
            outcome = "incomplete"
        else:
            continue  # Rush, Sack Taken, or a trick-play Reception — not a pass attempt

        yards_row = group[group["statType"].isin(["Completion", "Incompletion", "Interception Thrown"])]
        yards_gained = int(yards_row["stat"].iloc[0]) if not yards_row.empty else 0
        start_pos = 100 - int(first["yardsToGoal"])
        end_pos = start_pos + yards_gained if outcome == "complete" else start_pos

        receiver = None
        if outcome == "complete":
            play_all = stats[stats["playId"] == play_id]
            rec_rows = play_all[(play_all["statType"] == "Reception") & (play_all["athleteName"] != player_name)]
            if not rec_rows.empty:
                receiver = rec_rows["athleteName"].iloc[0]

        rows.append(
            {
                "week": int(first["week"]),
                "opponent": first["opponent"],
                "down": int(first["down"]),
                "distance": int(first["distance"]),
                "start_pos": start_pos,
                "end_pos": end_pos,
                "yards_gained": yards_gained,
                "outcome": outcome,
                "receiver": receiver,
                "period": int(first["period"]),
                "clock_minutes": int(first["clock.minutes"]),
                "clock_seconds": int(first["clock.seconds"]),
                "is_touchdown": "Touchdown" in types,
            }
        )

    df = pd.DataFrame(rows).sort_values("week", kind="stable").reset_index(drop=True)
    return df


def get_team_drives(team: str, year: int) -> pd.DataFrame:
    def fetch_records():
        with get_client() as client:
            return cfbd.DrivesApi(client).get_drives(year=year, team=team)

    return _cached_team_records("drives", team, year, fetch_records)


if __name__ == "__main__":
    profile = build_team_profile("Notre Dame", [2024, 2025])
    for category, df in profile.items():
        print(f"{category}: {df.shape}")
