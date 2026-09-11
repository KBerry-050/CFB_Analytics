"""Post-game data for a single game: everything `src/viz/postgame_report.py`
needs to build the post-game summary card, pulled from the CFBD endpoints that
only become meaningful once a game is final.

Nine endpoints feed this module:

- `GamesApi.get_games`               line scores, pre/post Elo, excitement index
- `GamesApi.get_advanced_box_score`  havoc, field position, scoring opportunities,
                                     rushing detail, and success rate /
                                     explosiveness / PPA split out by quarter,
                                     plus per-player PPA and usage
- `GamesApi.get_game_team_stats`     the traditional box score
- `GamesApi.get_game_player_stats`   per-player passing/rushing/receiving lines
- `MetricsApi.get_win_probability`   play-by-play win probability
- `PlaysApi.get_plays`               period/clock/scoring, joined onto the WP rows
- `DrivesApi.get_drives`             drive-by-drive results
- `BettingApi.get_lines`             closing spread / over-under
- `GamesApi.get_weather`             game conditions
- `RankingsApi.get_rankings`         the polls the teams entered the game with

Every piece is cached per game id via `cached_dataframe`, so a report only ever
hits the API once per game.
"""

import base64
import functools
import json
import re
from pathlib import Path

import cfbd
import pandas as pd

from src.data.cache import cached_dataframe
from src.data.client import get_client
from src.data.teams import download_logo, get_teams

# Traditional box-score categories that arrive as compound strings rather than a
# plain number: "3-13", "19-38", "6-57", "22:50". Each maps to the pair of
# numeric columns it unpacks into.
_PAIR_STATS = {
    "thirdDownEff": ("third_down_conv", "third_down_att"),
    "fourthDownEff": ("fourth_down_conv", "fourth_down_att"),
    "completionAttempts": ("completions", "pass_attempts"),
    "totalPenaltiesYards": ("penalties", "penalty_yards"),
}

_SIMPLE_STATS = {
    "firstDowns": "first_downs",
    "totalYards": "total_yards",
    "netPassingYards": "passing_yards",
    "yardsPerPass": "yards_per_pass",
    "rushingYards": "rushing_yards",
    "rushingAttempts": "rushing_attempts",
    "yardsPerRushAttempt": "yards_per_rush",
    "turnovers": "turnovers",
    "fumblesLost": "fumbles_lost",
    "interceptions": "interceptions_thrown",
    "sacks": "sacks",
    "tacklesForLoss": "tackles_for_loss",
    "qbHurries": "qb_hurries",
    "passesDeflected": "passes_deflected",
    "kickingPoints": "kicking_points",
    "passingTDs": "passing_tds",
    "rushingTDs": "rushing_tds",
}


@functools.lru_cache(maxsize=None)
def resolve_game_id(year: int, week: int, team: str, season_type: str = "regular") -> int:
    """The CFBD game id for `team`'s game in a given week — so a report can be
    built from names ("LSU", 2025, week 1) rather than a memorized id.

    Memoized in-process (not via `cached_dataframe`, which is parquet-backed
    and expects a DataFrame) since a report often resolves the same game
    more than once — e.g. building a half-split table and a player table
    back to back — and this is a real network call, not a free lookup."""
    with get_client() as client:
        games = cfbd.GamesApi(client).get_games(
            year=year, week=week, season_type=season_type, team=team
        )
    if not games:
        raise ValueError(f"No {year} week {week} ({season_type}) game found for {team}.")
    return games[0].id


def get_game_result(team: str, game_id: int) -> dict:
    """`team`'s opponent and each side's final score for one game — the
    "which side of the box score is this team" lookup that every per-team
    report needs at least once, pulled out of `get_game_summary` so it isn't
    reimplemented (the same `is_home` ternary, four times over) in every
    chart/table module that needs a game's context."""
    summary = get_game_summary(game_id).iloc[0]
    is_home = summary["home_team"] == team
    return {
        "opponent": summary["away_team"] if is_home else summary["home_team"],
        "team_points": summary["home_points"] if is_home else summary["away_points"],
        "opp_points": summary["away_points"] if is_home else summary["home_points"],
    }


def get_game_summary(game_id: int) -> pd.DataFrame:
    """One row of game-level facts: teams, scores, quarter line scores, Elo
    before and after, postgame win probability, excitement, venue, attendance."""

    def fetch() -> pd.DataFrame:
        with get_client() as client:
            games = cfbd.GamesApi(client).get_games(id=game_id)
        if not games:
            raise ValueError(f"No CFBD game with id {game_id}.")
        g = games[0]
        return pd.DataFrame(
            [
                {
                    "id": g.id,
                    "season": g.season,
                    "week": g.week,
                    "season_type": str(getattr(g.season_type, "value", g.season_type)),
                    "start_date": str(g.start_date),
                    "neutral_site": g.neutral_site,
                    "conference_game": g.conference_game,
                    "venue": g.venue,
                    "attendance": g.attendance,
                    "excitement": g.excitement_index,
                    "home_id": g.home_id,
                    "home_team": g.home_team,
                    "home_conference": g.home_conference,
                    "home_points": g.home_points,
                    "home_line_scores": ",".join(str(s) for s in (g.home_line_scores or [])),
                    "home_pregame_elo": g.home_pregame_elo,
                    "home_postgame_elo": g.home_postgame_elo,
                    "home_postgame_wp": g.home_postgame_win_probability,
                    "away_id": g.away_id,
                    "away_team": g.away_team,
                    "away_conference": g.away_conference,
                    "away_points": g.away_points,
                    "away_line_scores": ",".join(str(s) for s in (g.away_line_scores or [])),
                    "away_pregame_elo": g.away_pregame_elo,
                    "away_postgame_elo": g.away_postgame_elo,
                    "away_postgame_wp": g.away_postgame_win_probability,
                }
            ]
        )

    return cached_dataframe(f"postgame_summary_{game_id}", fetch)


def get_game_team_box(game_id: int, year: int, week: int, season_type: str = "regular") -> pd.DataFrame:
    """The traditional box score, two rows (one per team), compound stats
    unpacked into numeric columns and possession time converted to seconds."""

    def fetch() -> pd.DataFrame:
        with get_client() as client:
            raw = cfbd.GamesApi(client).get_game_team_stats(
                year=year, week=week, season_type=season_type, id=game_id
            )
        rows = []
        for team in raw[0].teams:
            row = {
                "team": team.team,
                "team_id": team.team_id,
                "conference": team.conference,
                "home_away": str(getattr(team.home_away, "value", team.home_away)),
                "points": team.points,
            }
            for stat in team.stats:
                value = stat.stat
                if stat.category in _PAIR_STATS:
                    left, right = _PAIR_STATS[stat.category]
                    made, _, attempted = value.partition("-")
                    row[left] = pd.to_numeric(made, errors="coerce")
                    row[right] = pd.to_numeric(attempted, errors="coerce")
                elif stat.category == "possessionTime":
                    minutes, _, seconds = value.partition(":")
                    row["possession_seconds"] = int(minutes) * 60 + int(seconds)
                elif stat.category in _SIMPLE_STATS:
                    row[_SIMPLE_STATS[stat.category]] = pd.to_numeric(value, errors="coerce")
            rows.append(row)
        return pd.DataFrame(rows)

    return cached_dataframe(f"postgame_team_box_{game_id}", fetch)


def get_game_advanced_box(game_id: int) -> pd.DataFrame:
    """Advanced team metrics, two rows: efficiency (success rate, explosiveness,
    PPA overall and by down type), havoc, rushing detail, average starting field
    position, and points per scoring opportunity."""

    def fetch() -> pd.DataFrame:
        box = _fetch_advanced_box(game_id)
        teams = box["teams"]
        rows: dict[str, dict] = {}

        for entry in teams["fieldPosition"]:
            rows.setdefault(entry["team"], {"team": entry["team"]}).update(
                avg_start=entry["averageStart"],
                avg_start_pp=entry["averageStartingPredictedPoints"],
            )
        for entry in teams["scoringOpportunities"]:
            rows.setdefault(entry["team"], {"team": entry["team"]}).update(
                scoring_opps=entry["opportunities"],
                opp_points=entry["points"],
                points_per_opp=entry["pointsPerOpportunity"],
            )
        for entry in teams["havoc"]:
            rows.setdefault(entry["team"], {"team": entry["team"]}).update(
                havoc=entry["total"],
                havoc_front_seven=entry["frontSeven"],
                havoc_db=entry["db"],
            )
        for entry in teams["rushing"]:
            rows.setdefault(entry["team"], {"team": entry["team"]}).update(
                power_success=entry["powerSuccess"],
                stuff_rate=entry["stuffRate"],
                line_yards=entry["lineYardsAverage"],
                second_level_yards=entry["secondLevelYardsAverage"],
                open_field_yards=entry["openFieldYardsAverage"],
            )
        for entry in teams["explosiveness"]:
            rows.setdefault(entry["team"], {"team": entry["team"]}).update(
                explosiveness=entry["overall"]["total"],
            )
        for entry in teams["successRates"]:
            rows.setdefault(entry["team"], {"team": entry["team"]}).update(
                success_rate=entry["overall"]["total"],
                standard_downs_sr=entry["standardDowns"]["total"],
                passing_downs_sr=entry["passingDowns"]["total"],
            )
        for entry in teams["ppa"]:
            rows.setdefault(entry["team"], {"team": entry["team"]}).update(
                plays=entry["plays"],
                ppa=entry["overall"]["total"],
                ppa_passing=entry["passing"]["total"],
                ppa_rushing=entry["rushing"]["total"],
            )
        for entry in teams["cumulativePpa"]:
            rows.setdefault(entry["team"], {"team": entry["team"]}).update(
                total_ppa=entry["overall"]["total"],
            )
        return pd.DataFrame(list(rows.values()))

    return cached_dataframe(f"postgame_advanced_box_{game_id}", fetch)


def get_game_quarter_splits(game_id: int) -> pd.DataFrame:
    """Long frame of team x quarter x (success rate, explosiveness, PPA/play) —
    the per-quarter breakdown the advanced box score carries alongside its
    totals, which is what makes momentum swings visible."""

    def fetch() -> pd.DataFrame:
        teams = _fetch_advanced_box(game_id)["teams"]
        by_metric = {
            "success_rate": {e["team"]: e["overall"] for e in teams["successRates"]},
            "explosiveness": {e["team"]: e["overall"] for e in teams["explosiveness"]},
            "ppa": {e["team"]: e["overall"] for e in teams["ppa"]},
        }
        rows = []
        for metric, per_team in by_metric.items():
            for team, values in per_team.items():
                for quarter in (1, 2, 3, 4):
                    rows.append(
                        {
                            "team": team,
                            "quarter": quarter,
                            "metric": metric,
                            "value": values.get(f"quarter{quarter}"),
                        }
                    )
        return pd.DataFrame(rows)

    return cached_dataframe(f"postgame_quarter_splits_{game_id}", fetch)


# Play types that score points off a turnover/special-teams return rather
# than an offensive snap — the scoring team's *defense* gets credit, not its
# offense, so these need pulling back out of a half's raw point total to get
# an offense-only figure. (Safeties are deliberately excluded: those are 2
# points *against* the team whose offense got tackled in its own end zone,
# not a defensive score for the team in question, and don't show up in this
# module as a play row keyed to that team as `defense` the same way.)
_RETURN_TD_TYPES = {
    "Interception Return Touchdown",
    "Fumble Return Touchdown",
    "Blocked Punt Touchdown",
    "Blocked Field Goal Touchdown",
    "Punt Return Touchdown",
    "Kickoff Return Touchdown",
    "Missed Field Goal Return Touchdown",
}

_RUSH_PLAY_TYPES = {"Rush", "Rushing Touchdown"}
_PASS_PLAY_TYPES = {
    "Pass Reception", "Pass Incompletion", "Passing Touchdown", "Sack",
    "Interception Return", "Interception Return Touchdown",
}

_SUCCESS_THRESHOLD_BY_DOWN = {1: 0.5, 2: 0.7, 3: 1.0, 4: 1.0}


def _fetch_game_plays(game_id: int, year: int, week: int, team: str, season_type: str = "regular") -> pd.DataFrame:
    """Every play of `team`'s game (both snaps on offense and on defense),
    with the fields `get_game_win_probability` doesn't carry through (down,
    distance, play type, which side had the ball, starting field position,
    and the play's own text description) — needed to classify plays as
    rushes/passes and compute success rate ourselves (CFBD has no per-play
    success flag), to place a play on a field diagram, and to attribute a
    play to a player. `get_explosive_plays_by_player` and
    `get_offensive_plays_with_field_position` both reuse this same cached
    fetch rather than hitting `PlaysApi.get_plays` a second time for the
    same game.

    `start_yard` is `yardline` renamed for clarity: 0-100, the offense's own
    goal line at 0 and the opponent's at 100 regardless of which real end of
    the field the snap was on (confirmed empirically: `start_yard +
    yards_gained` matches the play's own text description of where it
    ended, e.g. a play into the end zone for a touchdown ends at exactly
    100)."""

    def fetch() -> pd.DataFrame:
        with get_client() as client:
            plays = cfbd.PlaysApi(client).get_plays(year=year, week=week, season_type=season_type, team=team)
        return pd.DataFrame(
            [
                {
                    "period": p.period,
                    "down": p.down,
                    "distance": p.distance,
                    "yards_gained": p.yards_gained,
                    "play_type": p.play_type,
                    "ppa": p.ppa,
                    "offense": p.offense,
                    "defense": p.defense,
                    "scoring": p.scoring,
                    "play_text": p.play_text,
                    "start_yard": p.yardline,
                }
                for p in plays
                if p.game_id == game_id
            ]
        )

    return cached_dataframe(f"postgame_plays_{game_id}_{team}", fetch)


def _is_successful_play(down, distance, yards_gained) -> bool | None:
    """The standard college-football success-rate rule: a play "succeeds" if
    it gains 50% of the yards needed on 1st down, 70% on 2nd, or the whole
    distance on 3rd/4th. `None` (not True or False) for plays that can't be
    judged this way (no down/distance recorded — timeouts, penalties,
    kickoffs) rather than silently counting them as failures."""
    if down is None or distance is None or distance <= 0 or yards_gained is None:
        return None
    threshold = _SUCCESS_THRESHOLD_BY_DOWN.get(int(down))
    return None if threshold is None else yards_gained >= threshold * distance


def _half_for_period(period: float | None) -> int | None:
    if period is None or period > 4:  # overtime belongs to neither regulation half
        return None
    return 1 if period <= 2 else 2


def get_game_half_splits(
    game_id: int, year: int, week: int, team: str, season_type: str = "regular"
) -> pd.DataFrame:
    """One team's offense, split into 1st/2nd half: overall production and
    efficiency, plus the same broken out by rush/pass, and each half's total
    points split into offense vs. a defensive/return score.

    Points come from the official line score (`get_game_summary`), not
    reconstructed from drive results — a drive's result string ("TD", "FG")
    doesn't say whether the extra point or 2-point try was good, so summing
    line-score quarters is the only exact source for the *team's* total.
    `defensive_points` (a pick-six, a scoop-and-score, ...) is pulled back out
    of that total via play-by-play (see `_RETURN_TD_TYPES`) rather than
    assumed away, since it's real points on the scoreboard that didn't come
    from this offense; `offensive_points` is what's left. Overtime periods
    (5+) are excluded from both halves rather than folded into "2nd half",
    since they aren't part of either regulation half.

    Columns: half (1 or 2), points, defensive_points, offensive_points,
    total_yards, plays, yards_per_play, success_rate, explosiveness,
    ppa_per_play, and rush_/pass_ prefixed versions of yards, attempts,
    yards_per_att, success_rate, ppa_per_att.
    """
    summary = get_game_summary(game_id).iloc[0]
    is_home = summary["home_team"] == team
    line_scores_str = summary["home_line_scores"] if is_home else summary["away_line_scores"]
    quarters = [int(q) for q in line_scores_str.split(",") if q][:4]
    quarters += [0] * (4 - len(quarters))  # a shortened/incomplete record shouldn't raise
    half_points = {1: quarters[0] + quarters[1], 2: quarters[2] + quarters[3]}

    drives = get_game_drives(game_id, year, week, team, season_type)
    offense_drives = drives[(drives["offense"] == team) & (drives["start_period"] <= 4)].copy()
    offense_drives["half"] = offense_drives["start_period"].apply(lambda p: 1 if p <= 2 else 2)

    quarter_splits = get_game_quarter_splits(game_id)
    team_splits = quarter_splits[quarter_splits["team"] == team]

    def half_mean(metric: str, periods: tuple[int, int]) -> float | None:
        values = team_splits[(team_splits["metric"] == metric) & (team_splits["quarter"].isin(periods))]["value"]
        values = values.dropna()
        return float(values.mean()) if not values.empty else None

    plays = _fetch_game_plays(game_id, year, week, team, season_type)
    plays = plays.assign(half=plays["period"].apply(_half_for_period))

    defensive_scores = plays[
        (plays["defense"] == team) & plays["scoring"] & plays["play_type"].isin(_RETURN_TD_TYPES)
    ]
    # Touchdown + assumed-good extra point — CFBD's play log doesn't carry a
    # separate PAT/2-point result tied back to which score it followed, so 7
    # is the correct value for the overwhelming majority of cases and there's
    # no cleaner source to do better than that assumption from.
    defensive_points_by_half = defensive_scores.groupby("half").size() * 7

    offense_plays = plays[(plays["offense"] == team) & plays["half"].notna()].copy()
    offense_plays["success"] = offense_plays.apply(
        lambda r: _is_successful_play(r["down"], r["distance"], r["yards_gained"]), axis=1
    )

    def play_type_splits(half_plays: pd.DataFrame, play_types: set[str]) -> dict:
        sub = half_plays[half_plays["play_type"].isin(play_types)]
        attempts = len(sub)
        yards = sub["yards_gained"].sum()
        successes = sub["success"].dropna()
        ppa = sub["ppa"].dropna()
        return {
            "yards": yards,
            "attempts": attempts,
            "yards_per_att": yards / attempts if attempts else None,
            "success_rate": float(successes.mean()) if not successes.empty else None,
            "ppa_per_att": float(ppa.mean()) if not ppa.empty else None,
        }

    rows = []
    for half, periods in ((1, (1, 2)), (2, (3, 4))):
        half_drives = offense_drives[offense_drives["half"] == half]
        total_plays, total_yards = half_drives["plays"].sum(), half_drives["yards"].sum()
        defensive_points = int(defensive_points_by_half.get(half, 0))

        half_offense_plays = offense_plays[offense_plays["half"] == half]
        rush = play_type_splits(half_offense_plays, _RUSH_PLAY_TYPES)
        pas = play_type_splits(half_offense_plays, _PASS_PLAY_TYPES)

        rows.append(
            {
                "half": half,
                "points": half_points[half],
                "defensive_points": defensive_points,
                "offensive_points": half_points[half] - defensive_points,
                "total_yards": total_yards,
                "plays": total_plays,
                "yards_per_play": total_yards / total_plays if total_plays else None,
                "success_rate": half_mean("success_rate", periods),
                "explosiveness": half_mean("explosiveness", periods),
                "ppa_per_play": half_mean("ppa", periods),
                "rush_yards": rush["yards"],
                "rush_attempts": rush["attempts"],
                "rush_yards_per_att": rush["yards_per_att"],
                "rush_success_rate": rush["success_rate"],
                "rush_ppa_per_att": rush["ppa_per_att"],
                "pass_yards": pas["yards"],
                "pass_attempts": pas["attempts"],
                "pass_yards_per_att": pas["yards_per_att"],
                "pass_success_rate": pas["success_rate"],
                "pass_ppa_per_att": pas["ppa_per_att"],
            }
        )
    return pd.DataFrame(rows)


# The common threshold-based "explosive play" convention (a bigger cushion
# for a catch than a run) — distinct from `get_game_advanced_box`'s
# "explosiveness" (average PPA on successful plays), which is a magnitude
# average, not a per-play yes/no call, and can't be attributed to one player.
EXPLOSIVE_RUSH_YARDS = 15
EXPLOSIVE_RECEPTION_YARDS = 20

# CFBD's play-by-play carries no structured player field (that only exists
# on its box-score endpoints, which report season/game totals, not
# individual plays) — so the ball-carrier/receiver has to come out of the
# play's own text description, which does consistently include jersey
# number + an abbreviated name right before "rush" or after "to " and
# before "caught".
_RUSH_PLAYER_RE = re.compile(r"#(\d+)\s+([A-Z][\w'.]+(?:\s+[A-Z][\w'.]+)*)\s+rush")
_RECEPTION_PLAYER_RE = re.compile(r"to #(\d+)\s+([A-Z][\w'.]+(?:\s+[A-Z][\w'.]+)*)\s+caught")


def _ball_carrier_plays(game_id: int, year: int, week: int, team: str, season_type: str) -> pd.DataFrame:
    """Every rush/reception by `team`'s offense in one game, attributed to
    the ball-carrier/receiver by jersey number (parsed from the play's text
    — see the module-level comment above) — the shared basis for both
    `get_explosive_plays_by_player` (filtered to a yardage threshold) and
    `get_offensive_plays_with_field_position` (kept in full, with field
    position, for plotting).

    A play whose text doesn't match the expected format is silently skipped
    (undercounting) rather than raising, since broadcast-style text
    descriptions aren't a guaranteed-stable schema the way CFBD's structured
    fields are — this is a best-effort attribution, not an official stat.
    The count of skipped plays is attached to the result as
    `.attrs["unparsed_count"]`, so a caller building a report on top of this
    can sanity-check it before publishing rather than trusting a silent
    undercount.

    Columns: period, play_type, yards_gained, start_yard, end_yard,
    jersey_number, player_text (CFBD's abbreviated name, e.g. "J.Faison" —
    join on jersey_number to your own roster source for a full name/
    position/photo; neither this endpoint nor CFBD has those), ppa.
    """
    plays = _fetch_game_plays(game_id, year, week, team, season_type)
    offense = plays[plays["offense"] == team]

    is_rush = offense["play_type"].isin(("Rush", "Rushing Touchdown"))
    is_reception = offense["play_type"].isin(("Pass Reception", "Passing Touchdown"))
    candidates = offense[is_rush | is_reception]

    rows = []
    unparsed_count = 0
    for p in candidates.itertuples():
        pattern = _RUSH_PLAYER_RE if p.play_type in ("Rush", "Rushing Touchdown") else _RECEPTION_PLAYER_RE
        match = pattern.search(p.play_text or "")
        if not match:
            unparsed_count += 1
            continue
        rows.append(
            {
                "period": int(p.period),
                "play_type": p.play_type,
                "yards_gained": p.yards_gained,
                "start_yard": p.start_yard,
                "end_yard": p.start_yard + p.yards_gained,
                "jersey_number": int(match.group(1)),
                "player_text": match.group(2),
                "ppa": p.ppa,
            }
        )

    result = pd.DataFrame(rows)
    result.attrs["unparsed_count"] = unparsed_count
    return result


def get_offensive_plays_with_field_position(
    game_id: int, year: int, week: int, team: str, season_type: str = "regular",
    rush_yards: int = EXPLOSIVE_RUSH_YARDS, reception_yards: int = EXPLOSIVE_RECEPTION_YARDS,
) -> pd.DataFrame:
    """Every rush/reception by `team`'s offense in one game, with its
    start/end field position (0 = own goal line, 100 = opponent's) for
    plotting on a field diagram — see `_ball_carrier_plays` for the
    attribution/caveats this builds on.

    Columns: period, play_type, yards_gained, start_yard, end_yard,
    jersey_number, player_text, ppa, is_explosive (a rush of `rush_yards`+ or
    reception of `reception_yards`+ — the same threshold
    `get_explosive_plays_by_player` uses, so the two stay consistent).
    """
    plays = _ball_carrier_plays(game_id, year, week, team, season_type)
    is_rush = plays["play_type"].isin(("Rush", "Rushing Touchdown"))
    unparsed_count = plays.attrs.get("unparsed_count", 0)
    plays = plays.assign(
        is_explosive=(is_rush & (plays["yards_gained"] >= rush_yards)) | (~is_rush & (plays["yards_gained"] >= reception_yards))
    )
    # `.assign()` doesn't reliably propagate `.attrs` (pandas attrs propagation
    # is still experimental), so re-set it explicitly rather than trust it
    # survived — this isn't dead code even though `_ball_carrier_plays` always
    # sets the attr on its own return value.
    plays.attrs["unparsed_count"] = unparsed_count
    return plays


def get_explosive_plays_by_player(
    game_id: int, year: int, week: int, team: str, season_type: str = "regular",
    rush_yards: int = EXPLOSIVE_RUSH_YARDS, reception_yards: int = EXPLOSIVE_RECEPTION_YARDS,
) -> pd.DataFrame:
    """Every individual explosive play (a rush of `rush_yards`+, or a
    reception of `reception_yards`+) by `team`'s offense in one game — a
    filtered view of `get_offensive_plays_with_field_position`, reshaped to
    the half/jersey_number/player_text/play_type/yards_gained columns the
    per-player explosive-play tables use.

    Not cached itself (`get_offensive_plays_with_field_position` underneath
    it isn't either): filtering an already-fetched frame by threshold is
    cheap, and skipping a cache here avoids a stale entry if `rush_yards`/
    `reception_yards` changes between calls for the same game.
    """
    plays = get_offensive_plays_with_field_position(game_id, year, week, team, season_type, rush_yards, reception_yards)
    result = plays[plays["is_explosive"]].copy()
    result["half"] = result["period"].apply(lambda p: 1 if p <= 2 else 2)
    result = result[["half", "jersey_number", "player_text", "play_type", "yards_gained"]].reset_index(drop=True)
    result.attrs["unparsed_count"] = plays.attrs["unparsed_count"]
    return result


def get_game_player_impact(
    game_id: int, year: int, week: int, season_type: str = "regular"
) -> pd.DataFrame:
    """Per-player PPA and usage from the advanced box score, joined to a
    readable stat line assembled from the traditional player box score."""

    def fetch() -> pd.DataFrame:
        players = _fetch_advanced_box(game_id)["players"]
        ppa = pd.DataFrame(
            [
                {
                    "player": p["player"],
                    "team": p["team"],
                    "position": p["position"],
                    "ppa_per_play": p["average"]["total"],
                    "total_ppa": p["cumulative"]["total"],
                }
                for p in players["ppa"]
            ]
        )
        usage = pd.DataFrame(
            [{"player": u["player"], "team": u["team"], "usage": u["total"]} for u in players["usage"]]
        )
        stat_lines = _player_stat_lines(game_id, year, week, season_type)
        return (
            ppa.merge(usage, on=["player", "team"], how="left")
            .merge(stat_lines, on=["player", "team"], how="left")
            .sort_values("total_ppa", ascending=False)
            .reset_index(drop=True)
        )

    return cached_dataframe(f"postgame_player_impact_{game_id}", fetch)


def get_game_win_probability(
    game_id: int, year: int, week: int, team: str, season_type: str = "regular"
) -> pd.DataFrame:
    """Play-by-play win probability with a real game-clock axis.

    The win-probability endpoint carries no period or clock, so each row is
    joined to the play-by-play on play id to recover them, then converted to
    seconds elapsed. Occasional WP rows have no matching play (a scoring play
    logged only in the WP feed); their period/clock is filled forward so the
    series stays monotonic in time.
    """

    def fetch() -> pd.DataFrame:
        with get_client() as client:
            wp = cfbd.MetricsApi(client).get_win_probability(game_id=game_id)
            plays = cfbd.PlaysApi(client).get_plays(
                year=year, week=week, season_type=season_type, team=team
            )
        wp_df = pd.DataFrame(
            [
                {
                    "play_id": str(w.play_id),
                    "play_number": w.play_number,
                    "home_win_prob": w.home_win_probability,
                    "home_score": w.home_score,
                    "away_score": w.away_score,
                    "home_ball": w.home_ball,
                    "play_text": w.play_text,
                }
                for w in wp
            ]
        ).sort_values("play_number")

        plays_df = pd.DataFrame(
            [
                {
                    "play_id": str(p.id),
                    "period": p.period,
                    "clock_seconds": (p.clock.minutes or 0) * 60 + (p.clock.seconds or 0),
                    "scoring": p.scoring,
                    "play_ppa": p.ppa,
                }
                for p in plays
                if p.game_id == game_id
            ]
        )

        df = wp_df.merge(plays_df, on="play_id", how="left")
        df["period"] = df["period"].ffill().bfill()
        df["clock_seconds"] = df["clock_seconds"].ffill().bfill()
        df["scoring"] = df["scoring"].fillna(False).astype(bool)
        # Elapsed game seconds; the same formula extends past regulation, so
        # overtime periods simply continue off the end of the 3600s axis.
        df["elapsed_seconds"] = (df["period"] - 1) * 900 + (900 - df["clock_seconds"])
        df["wp_swing"] = df["home_win_prob"].diff().fillna(0)
        return df.reset_index(drop=True)

    return cached_dataframe(f"postgame_win_prob_{game_id}", fetch)


def get_game_drives(
    game_id: int, year: int, week: int, team: str, season_type: str = "regular"
) -> pd.DataFrame:
    """Drive-by-drive results in chronological order."""

    def fetch() -> pd.DataFrame:
        with get_client() as client:
            drives = cfbd.DrivesApi(client).get_drives(
                year=year, week=week, season_type=season_type, team=team
            )
        return pd.DataFrame(
            [
                {
                    "drive_number": d.drive_number,
                    "offense": d.offense,
                    "defense": d.defense,
                    "start_period": d.start_period,
                    "start_yards_to_goal": d.start_yards_to_goal,
                    "plays": d.plays,
                    "yards": d.yards,
                    "result": d.drive_result,
                    "scoring": d.scoring,
                    "is_home_offense": d.is_home_offense,
                    "elapsed_seconds": (d.elapsed.minutes or 0) * 60 + (d.elapsed.seconds or 0),
                }
                for d in drives
                if d.game_id == game_id
            ]
        ).sort_values("drive_number").reset_index(drop=True)

    return cached_dataframe(f"postgame_drives_{game_id}", fetch)


def get_game_context(
    game_id: int, year: int, week: int, team: str, season_type: str = "regular"
) -> pd.DataFrame:
    """One row of pre-game and environmental context: the consensus closing
    line, pregame win probability, weather, and the polls each team entered the
    game ranked in. All of it is optional — a game with no betting market, no
    weather record or two unranked teams still returns a row."""

    def fetch() -> pd.DataFrame:
        summary = get_game_summary(game_id).iloc[0]
        with get_client() as client:
            betting = cfbd.BettingApi(client).get_lines(game_id=game_id)
            weather = cfbd.GamesApi(client).get_weather(
                year=year, week=week, season_type=season_type, game_id=game_id
            )
            pregame = cfbd.MetricsApi(client).get_pregame_win_probabilities(
                year=year, week=week, season_type=season_type, team=team
            )
            rankings = cfbd.RankingsApi(client).get_rankings(
                year=year, week=week, season_type=season_type
            )

        row: dict = {"game_id": game_id}

        lines = [line for game in betting if game.id == game_id for line in game.lines]
        spreads = [line.spread for line in lines if line.spread is not None]
        totals = [line.over_under for line in lines if line.over_under is not None]
        if spreads:
            # Median across books rather than one provider's number, so a single
            # outlier book doesn't define the game's framing.
            row["spread"] = float(pd.Series(spreads).median())
            row["over_under"] = float(pd.Series(totals).median()) if totals else None
            row["spread_providers"] = len(spreads)

        for w in weather:
            if w.id == game_id:
                row.update(
                    temperature=w.temperature,
                    wind_speed=w.wind_speed,
                    humidity=w.humidity,
                    precipitation=w.precipitation,
                    weather_condition=w.weather_condition,
                    indoors=w.game_indoors,
                )

        for p in pregame:
            if p.game_id == game_id:
                row["home_pregame_wp"] = p.home_win_probability

        ranks = {}
        for poll_week in rankings:
            for poll in poll_week.polls:
                if poll.poll != "AP Top 25":
                    continue
                for entry in poll.ranks:
                    ranks[entry.school] = entry.rank
        row["home_rank"] = ranks.get(summary["home_team"])
        row["away_rank"] = ranks.get(summary["away_team"])
        return pd.DataFrame([row])

    return cached_dataframe(f"postgame_context_{game_id}", fetch)


def get_team_abbreviations(year: int) -> pd.DataFrame:
    """School -> the official short code ("CLEM", "LSU") CFBD carries on the
    teams endpoint. Cached separately from `get_teams` so adding it doesn't
    invalidate that function's existing cached schema."""

    def fetch() -> pd.DataFrame:
        with get_client() as client:
            teams = cfbd.TeamsApi(client).get_teams(year=year)
        return pd.DataFrame([{"school": t.school, "abbreviation": t.abbreviation} for t in teams])

    return cached_dataframe(f"team_abbreviations_{year}", fetch)


def get_team_identity(year: int, schools: list[str]) -> pd.DataFrame:
    """Brand colors, short code, and a base64 data URI of each school's logo.

    The logo is embedded rather than linked so the report page is fully
    self-contained — a headless-Chrome screenshot can't race a CDN fetch that
    hasn't finished, and the HTML stays viewable offline.
    """
    teams = get_teams(year)
    abbreviations = get_team_abbreviations(year).set_index("school")["abbreviation"].to_dict()
    rows = []
    for school in schools:
        match = teams[teams["school"] == school]
        if match.empty:
            rows.append({"school": school, "color": "#666666", "alt_color": "#999999", "logo_data_uri": None})
            continue
        team = match.iloc[0]
        logo_uri = None
        if team["logo"]:
            try:
                logo_uri = _data_uri(_legible_logo(int(team["id"]), team["logo"]))
            except Exception:  # noqa: BLE001 - a missing logo must not sink the report
                logo_uri = None
        rows.append(
            {
                "school": school,
                "team_id": int(team["id"]),
                "abbreviation": abbreviations.get(school) or school[:4].upper(),
                "conference": team["conference"],
                "color": team["color"] or "#666666",
                "alt_color": team["alt_color"] or "#999999",
                "logo_data_uri": logo_uri,
            }
        )
    return pd.DataFrame(rows)


def get_postgame_bundle(game_id: int) -> dict:
    """Every frame the post-game report needs, keyed by section.

    Only `game_id` is required — year, week, season type and the team name the
    play-level endpoints need are all read off the game summary first.
    """
    summary = get_game_summary(game_id)
    meta = summary.iloc[0]
    year, week = int(meta["season"]), int(meta["week"])
    season_type, team = meta["season_type"], meta["home_team"]

    return {
        "summary": summary,
        "team_box": get_game_team_box(game_id, year, week, season_type),
        "advanced_box": get_game_advanced_box(game_id),
        "quarter_splits": get_game_quarter_splits(game_id),
        "player_impact": get_game_player_impact(game_id, year, week, season_type),
        "win_prob": get_game_win_probability(game_id, year, week, team, season_type),
        "drives": get_game_drives(game_id, year, week, team, season_type),
        "context": get_game_context(game_id, year, week, team, season_type),
        "identity": get_team_identity(year, [meta["away_team"], meta["home_team"]]),
    }


def _fetch_advanced_box(game_id: int) -> dict:
    """The raw advanced box score as a plain dict. Three of the frames above are
    different slices of this one response, so it's fetched through the module's
    own cache rather than re-hit once per slice."""
    cache_key = f"postgame_advanced_raw_{game_id}"

    def fetch() -> pd.DataFrame:
        with get_client() as client:
            box = cfbd.GamesApi(client).get_advanced_box_score(id=game_id)
        return pd.DataFrame([{"json": _to_json(box.to_dict())}])

    return _from_json(cached_dataframe(cache_key, fetch).iloc[0]["json"])


def _player_stat_lines(game_id: int, year: int, week: int, season_type: str) -> pd.DataFrame:
    """A one-line "28/38, 232 YDS, 1 TD" summary per player, built from whichever
    of passing/rushing/receiving they actually recorded."""
    with get_client() as client:
        raw = cfbd.GamesApi(client).get_game_player_stats(
            year=year, week=week, season_type=season_type, id=game_id
        )

    # team -> player -> category -> {stat type: value}
    collected: dict[tuple[str, str], dict[str, dict[str, str]]] = {}
    for team in raw[0].teams:
        for category in team.categories:
            if category.name not in ("passing", "rushing", "receiving"):
                continue
            for stat_type in category.types:
                for athlete in stat_type.athletes:
                    key = (team.team, athlete.name.strip())
                    collected.setdefault(key, {}).setdefault(category.name, {})[stat_type.name] = athlete.stat

    rows = []
    for (team, player), categories in collected.items():
        parts = []
        if "passing" in categories:
            p = categories["passing"]
            line = f"{p.get('C/ATT', '')} {p.get('YDS', '')} YDS"
            if _positive(p.get("TD")):
                line += f", {p['TD']} TD"
            if _positive(p.get("INT")):
                line += f", {p['INT']} INT"
            parts.append(line.strip())
        if "rushing" in categories:
            r = categories["rushing"]
            line = f"{r.get('CAR', '')} CAR {r.get('YDS', '')} YDS"
            if _positive(r.get("TD")):
                line += f", {r['TD']} TD"
            parts.append(line.strip())
        if "receiving" in categories:
            c = categories["receiving"]
            line = f"{c.get('REC', '')} REC {c.get('YDS', '')} YDS"
            if _positive(c.get("TD")):
                line += f", {c['TD']} TD"
            parts.append(line.strip())
        rows.append({"team": team, "player": player, "stat_line": "  ·  ".join(parts)})
    return pd.DataFrame(rows)


def _positive(value: str | None) -> bool:
    return bool(value) and pd.to_numeric(value, errors="coerce") > 0


# A team's standard mark is often near-black (Iowa's is literally black), which
# vanishes on a dark background. CFBD serves a `logos-dark` variant lightened for
# exactly that case; below this mean-brightness floor the dark variant is used.
_LOGO_BRIGHTNESS_FLOOR = 105


def _legible_logo(team_id: int, logo_url: str) -> Path:
    """The local path to whichever of a team's two marks reads on a dark card:
    the standard one unless it's too dark, in which case CFBD's `logos-dark`
    variant. Falls back to the standard mark if the variant can't be fetched."""
    standard = download_logo(team_id, logo_url)
    if _mean_brightness(standard) >= _LOGO_BRIGHTNESS_FLOOR:
        return standard
    dark_url = logo_url.replace("/logos/", "/logos-dark/")
    if dark_url == logo_url:
        return standard
    try:
        dark = download_logo(team_id, dark_url, variant="_dark")
    except Exception:  # noqa: BLE001 - the variant is a nicety, not a requirement
        return standard
    return dark if _mean_brightness(dark) > _mean_brightness(standard) else standard


def _mean_brightness(path: Path) -> float:
    """Average brightness of a logo's non-transparent pixels — transparency has
    to be excluded or every logo scores as its background."""
    from PIL import Image

    image = Image.open(path).convert("RGBA")
    opaque = [p for p in image.get_flattened_data() if p[3] > 40]
    if not opaque:
        return 0.0
    return sum(sum(p[:3]) / 3 for p in opaque) / len(opaque)


def _data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def _to_json(payload: dict) -> str:
    return json.dumps(payload, default=str)


def _from_json(payload: str) -> dict:
    return json.loads(payload)
