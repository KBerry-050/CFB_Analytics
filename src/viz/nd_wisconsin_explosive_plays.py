"""Explosive plays for one game, two angles: a team's 1st-half-vs-2nd-half
production/efficiency (reusing `get_game_half_splits`, same shape as
`explosive_play_comparison.py`'s cross-game table but rows are halves instead
of different team-seasons), and a per-player count of individual explosive
plays (`get_explosive_plays_by_player`) — a rush of 15+ yards or reception of
20+, the common threshold definition, distinct from (and not attributable to
one player the way) CFBD's own PPA-based "explosiveness" metric.

Both halves of this are fully general (any team/year/week). The one
game-specific piece is `roster_lookup` — CFBD's play-by-play only carries a
jersey number and an abbreviated name ("J.Faison"), not a full name,
position, or photo, so a presentable player table needs those sourced
externally (a team's own roster page) and passed in explicitly rather than
guessed at or scraped automatically here.
"""

import pandas as pd
from great_tables import GT, html, loc, style

from src.data.postgame import (
    EXPLOSIVE_RECEPTION_YARDS,
    EXPLOSIVE_RUSH_YARDS,
    get_explosive_plays_by_player,
    get_game_half_splits,
    get_game_result,
    resolve_game_id,
)
from src.data.teams import download_player_photo, get_teams
from src.viz.explosive_play_comparison import EXPLOSIVENESS_SUBTITLE, apply_explosiveness_metric_columns
from src.viz.style import NARROW_COL_WIDTH, PERCENT_COL_WIDTH, base_table, team_header_title


def half_explosiveness_table(team: str, year: int, week: int, season_type: str = "regular") -> GT:
    """`team`'s production and efficiency by half for one game — the same
    columns as `explosive_play_comparison.py`'s cross-game table (and
    sharing its column formatting via `apply_explosiveness_metric_columns`),
    but rows are "1st Half"/"2nd Half" instead of different team-seasons."""
    game_id = resolve_game_id(year, week, team, season_type=season_type)
    result = get_game_result(team, game_id)

    splits = get_game_half_splits(game_id, year, week, team, season_type=season_type)
    splits["half_label"] = splits["half"].map({1: "1st Half", 2: "2nd Half"})

    teams = get_teams(year)
    logo_url = teams.loc[teams["school"] == team, "logo"].iloc[0]

    gt = (
        GT(splits[["half_label", "plays", "success_rate", "explosiveness", "ppa_per_play"]])
        .tab_header(
            title=team_header_title(f"{team} vs. {result['opponent']}: 1st Half vs. 2nd Half", logo_url),
            subtitle=html(f"CFB {year} Week {week}  ({result['team_points']:.0f}-{result['opp_points']:.0f})  &bull;  {EXPLOSIVENESS_SUBTITLE}"),
        )
        .cols_label(half_label=html(""))
        .cols_width({"half_label": "110px"})
    )
    gt = apply_explosiveness_metric_columns(gt)
    gt = base_table(gt)
    gt = gt.tab_style(style=style.text(weight="bold"), locations=loc.body(columns="half_label"))
    return gt


def explosive_plays_by_player_table(
    team: str, year: int, week: int, roster_lookup: dict[int, dict], season_type: str = "regular",
    rush_yards: int = EXPLOSIVE_RUSH_YARDS, reception_yards: int = EXPLOSIVE_RECEPTION_YARDS,
) -> GT:
    """Per-player count of individual explosive plays (a `rush_yards`+ rush
    or `reception_yards`+ reception) for `team` in one game, split by half.

    `roster_lookup` maps jersey number -> {"name", "position", "photo_path"}
    for every player who shows up in the play-by-play — build this from the
    team's own roster page (CFBD has neither full names nor headshots on its
    play-by-play). A jersey number missing from `roster_lookup` falls back to
    CFBD's own abbreviated name/no position/no photo rather than raising, so
    a roster lookup that's slightly incomplete doesn't break the table.
    """
    game_id = resolve_game_id(year, week, team, season_type=season_type)
    plays = get_explosive_plays_by_player(game_id, year, week, team, season_type=season_type, rush_yards=rush_yards, reception_yards=reception_yards)

    counts = (
        plays.groupby("jersey_number")
        .agg(
            first_half=("half", lambda s: int((s == 1).sum())),
            second_half=("half", lambda s: int((s == 2).sum())),
            player_text=("player_text", "first"),
        )
        .assign(total=lambda d: d["first_half"] + d["second_half"])
        .sort_values(["total", "jersey_number"], ascending=[False, True])
        .reset_index()
    )

    rows = []
    for row in counts.itertuples():
        info = roster_lookup.get(row.jersey_number, {})
        photo_path = info.get("photo_path")
        rows.append(
            {
                "photo": str(photo_path) if photo_path else None,
                "jersey_number": row.jersey_number,
                "player": info.get("name", row.player_text),
                "position": info.get("position", ""),
                "first_half": row.first_half,
                "second_half": row.second_half,
                "total": row.total,
            }
        )
    df = pd.DataFrame(rows)

    gt = (
        GT(df)
        .tab_header(
            title=html("Explosive Plays by Player"),
            subtitle=html(f"A {rush_yards}+ yard rush or {reception_yards}+ yard reception"),
        )
        .fmt_image(columns="photo")
        .fmt_integer(columns=["jersey_number", "first_half", "second_half", "total"])
        .cols_label(
            photo=html(""),
            jersey_number=html("#"),
            player=html("Player"),
            position=html("Pos"),
            first_half=html("1st Half"),
            second_half=html("2nd Half"),
            total=html("Total"),
        )
        .cols_align(align="center", columns=["jersey_number", "position", "first_half", "second_half", "total"])
        .cols_width(
            {
                "photo": "60px",
                "jersey_number": "45px",
                "player": "160px",
                "position": "55px",
                "first_half": PERCENT_COL_WIDTH,
                "second_half": PERCENT_COL_WIDTH,
                "total": NARROW_COL_WIDTH,
            }
        )
    )
    gt = base_table(gt)
    gt = gt.tab_style(style=style.text(weight="bold"), locations=loc.body(columns="player"))
    if not df.empty:
        gt = gt.tab_style(style=style.text(weight="bold"), locations=loc.body(columns="total", rows=[0]))
    return gt


if __name__ == "__main__":
    from src.viz.render import combine_gt_tables, render_html_to_png

    # Sourced by hand from Notre Dame's ESPN roster page
    # (espn.com/college-football/team/roster/_/id/87/notredame-fighting-irish)
    # for the three jersey numbers this game's play-by-play actually surfaced
    # — see the module docstring for why this can't be pulled automatically.
    roster = {
        2: {"name": "Nolan James Jr.", "position": "RB", "photo_url": "https://a.espncdn.com/i/headshots/college-football/players/full/5189515.png"},
        6: {"name": "Jordan Faison", "position": "WR", "photo_url": "https://a.espncdn.com/i/headshots/college-football/players/full/5150424.png"},
        22: {"name": "Aneyas Williams", "position": "RB", "photo_url": "https://a.espncdn.com/i/headshots/college-football/players/full/5079742.png"},
    }
    roster_lookup = {
        number: {**info, "photo_path": download_player_photo(info["photo_url"])} for number, info in roster.items()
    }

    half_table = half_explosiveness_table("Notre Dame", 2026, 1)
    player_table = explosive_plays_by_player_table("Notre Dame", 2026, 1, roster_lookup)

    # Sanity-check the play-text parse before publishing a table built on it —
    # see get_explosive_plays_by_player's docstring on why this can't just
    # raise instead.
    game_id = resolve_game_id(2026, 1, "Notre Dame")
    unparsed = get_explosive_plays_by_player(game_id, 2026, 1, "Notre Dame").attrs["unparsed_count"]
    if unparsed:
        print(f"WARNING: {unparsed} explosive play(s) had unparseable play_text and were left out of the count.")

    html_body = combine_gt_tables(half_table, player_table)
    out_html = "src/viz/output/nd_wisconsin_explosive_plays.html"
    with open(out_html, "w") as f:
        f.write(html_body)
    print(f"wrote {out_html}")

    out_png = render_html_to_png(html_body, "src/viz/output/nd_wisconsin_explosive_plays.png")
    print(f"wrote {out_png}")
