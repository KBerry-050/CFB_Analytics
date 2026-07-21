"""Game film ↔ play-by-play synchronization.

Local video/photos live in the gitignored `game_film/` directory (never in
git — see the storage-location discussion in project history; large binaries
don't belong in version control). This module handles the other half: once
you know roughly what the game clock read at a given video timestamp, these
functions find the matching play(s) in data we already have.

Suggested layout:
    game_film/
      {team}_{year}/
        wk{week}_{opponent}/
          film.mp4
          photos/
      sync_anchors.csv   <- see SYNC_ANCHOR_COLUMNS below

Sync workflow this is built for:
1. Mark a handful of anchor points per video (one per quarter, or at each
   score) where you know both the video timestamp and the game clock —
   easiest if the film shows an on-screen scoreboard. Record them in
   sync_anchors.csv.
2. `estimate_game_clock()` linearly interpolates between the two nearest
   anchors to estimate the game clock at any other video timestamp (a
   single start-of-game anchor won't hold linearly through stoppages/
   replays/halftime, hence multiple anchors).
3. `find_plays_by_clock()` looks up the actual play(s) at that game clock
   from CFBD play-by-play data already fetched via `get_team_play_stats`.

Not yet built (needs the actual film + a decision on CV tooling before it's
worth scaffolding): scoreboard OCR to generate anchors automatically, and
anything player-tracking related.
"""

import pandas as pd

from src.data.team_profile import get_team_play_stats

SYNC_ANCHOR_COLUMNS = [
    "team",
    "year",
    "week",
    "video_file",
    "video_timestamp_seconds",
    "period",
    "clock_minutes",
    "clock_seconds",
    "note",
]


def game_clock_to_seconds(period: int, clock_minutes: int, clock_seconds: int) -> int:
    """A single increasing number for a (period, clock) pair, so anchors and
    plays can be compared/interpolated regardless of quarter. Game clock
    counts down within a period, so seconds-elapsed = period_length - clock."""
    quarter_length = 15 * 60
    elapsed_in_period = quarter_length - (clock_minutes * 60 + clock_seconds)
    return (period - 1) * quarter_length + elapsed_in_period


def estimate_game_clock(video_timestamp_seconds: float, anchors: pd.DataFrame) -> dict | None:
    """Estimate (period, clock_minutes, clock_seconds) at a video timestamp by
    linearly interpolating between the two nearest sync anchors (by video
    time) that bracket it. `anchors` must have the SYNC_ANCHOR_COLUMNS shape,
    already filtered to one team/year/week/video_file. Returns None if the
    timestamp falls outside the anchors' range (can't safely extrapolate
    across a stoppage/replay/halftime you have no anchor for)."""
    anchors = anchors.sort_values("video_timestamp_seconds")
    if len(anchors) < 2:
        raise ValueError("Need at least 2 sync anchors to interpolate — add more to sync_anchors.csv.")

    before = anchors[anchors["video_timestamp_seconds"] <= video_timestamp_seconds].tail(1)
    after = anchors[anchors["video_timestamp_seconds"] >= video_timestamp_seconds].head(1)
    if before.empty or after.empty:
        return None

    b, a = before.iloc[0], after.iloc[0]
    b_game_secs = game_clock_to_seconds(int(b["period"]), int(b["clock_minutes"]), int(b["clock_seconds"]))
    a_game_secs = game_clock_to_seconds(int(a["period"]), int(a["clock_minutes"]), int(a["clock_seconds"]))

    if a["video_timestamp_seconds"] == b["video_timestamp_seconds"]:
        game_secs = b_game_secs
    else:
        frac = (video_timestamp_seconds - b["video_timestamp_seconds"]) / (
            a["video_timestamp_seconds"] - b["video_timestamp_seconds"]
        )
        game_secs = b_game_secs + frac * (a_game_secs - b_game_secs)

    quarter_length = 15 * 60
    period = int(game_secs // quarter_length) + 1
    remaining_in_period = quarter_length - (game_secs % quarter_length)
    return {
        "period": period,
        "clock_minutes": int(remaining_in_period // 60),
        "clock_seconds": int(remaining_in_period % 60),
    }


def find_plays_by_clock(
    team: str,
    year: int,
    week: int,
    period: int,
    clock_minutes: int,
    clock_seconds: int,
    tolerance_seconds: int = 8,
) -> pd.DataFrame:
    """Every play-stat row within `tolerance_seconds` of game time (period,
    clock) in one specific game (`week`) — game clock resets every game, so
    without scoping to a week this would match plays from every game the
    team played that season, not just the one the film is from. A game-clock
    estimate from film is rarely exact to the second, hence the tolerance
    window instead of a single exact match."""
    target = game_clock_to_seconds(period, clock_minutes, clock_seconds)

    stats = get_team_play_stats(team, year)
    stats = stats[stats["week"] == week]
    game_secs = stats.apply(
        lambda r: game_clock_to_seconds(int(r["period"]), int(r["clock.minutes"]), int(r["clock.seconds"])), axis=1
    )
    return stats[(game_secs - target).abs() <= tolerance_seconds].copy()
