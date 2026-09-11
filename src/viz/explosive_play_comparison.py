"""Explosive-play comparison — one offense's explosiveness (CFBD's own
"explosiveness" metric: average predicted points added, PPA, on successful
plays only — how big the gains are once a play already succeeds, as opposed
to success rate's "how often a play succeeds at all") in one specific game,
compared across any list of (team, year, week) games.

Built for Notre Dame's 2026 week 1 vs. Wisconsin against Indiana's 2025 week
1 and Michigan's 2023 week 1 — three unrelated team-seasons, not one team
tracked over time, so unlike `offense_profile_comparison.py`'s two-season
view this puts a logo in each row rather than the header.
"""

import pandas as pd
from great_tables import GT, html, loc, style

from src.data.postgame import get_game_advanced_box, get_game_result, resolve_game_id
from src.data.teams import get_teams
from src.viz.style import NARROW_COL_WIDTH, PERCENT_COL_WIDTH, RATING_COL_WIDTH, WIN_COLOR, base_table

EXPLOSIVENESS_SUBTITLE = "Explosiveness = average PPA (predicted points added) on successful plays only"


def apply_explosiveness_metric_columns(gt: GT) -> GT:
    """Shared formatting for the plays/success_rate/explosiveness/ppa_per_play
    columns every "explosive play" table built on `get_game_advanced_box` or
    `get_game_half_splits` carries (see also `nd_wisconsin_explosive_plays.py`'s
    `half_explosiveness_table`, which applies this to per-half rows instead of
    per-game ones) — call this after any table-specific columns (a logo, a
    team/half label, ...) are already set up."""
    return (
        gt.fmt_integer(columns="plays")
        .fmt_percent(columns="success_rate", decimals=1)
        .fmt_number(columns=["explosiveness", "ppa_per_play"], decimals=2)
        .cols_label(
            plays=html("Plays"),
            success_rate=html("Success Rate"),
            explosiveness=html("Explosiveness"),
            ppa_per_play=html("PPA / Play"),
        )
        .cols_align(align="center", columns=["plays", "success_rate", "explosiveness", "ppa_per_play"])
        .cols_width(
            {
                "plays": NARROW_COL_WIDTH,
                "success_rate": PERCENT_COL_WIDTH,
                "explosiveness": RATING_COL_WIDTH,
                "ppa_per_play": RATING_COL_WIDTH,
            }
        )
    )


def build_explosive_play_comparison(games: list[tuple[str, int, int]], season_type: str = "regular") -> pd.DataFrame:
    """One row per (team, year, week): its logo, opponent, result, plays,
    success rate, explosiveness, and PPA/play for that offense in that
    single game — in the order `games` was given, not re-sorted."""
    rows = []
    for team, year, week in games:
        game_id = resolve_game_id(year, week, team, season_type=season_type)
        result = get_game_result(team, game_id)

        stats = get_game_advanced_box(game_id).set_index("team").loc[team]
        logo = get_teams(year).set_index("school")["logo"].get(team)

        rows.append(
            {
                "logo": logo,
                "team": team,
                "game": f"{year} Wk {week}",
                "opponent": result["opponent"],
                "result": f"{'W' if result['team_points'] > result['opp_points'] else 'L'} {result['team_points']:.0f}-{result['opp_points']:.0f}",
                "plays": stats["plays"],
                "success_rate": stats["success_rate"],
                "explosiveness": stats["explosiveness"],
                "ppa_per_play": stats["ppa"],
            }
        )
    return pd.DataFrame(rows)


def explosive_play_comparison_table(games: list[tuple[str, int, int]], season_type: str = "regular") -> GT:
    """The comparison table (see module docstring) for any list of
    (team, year, week) games — bolds the highest explosiveness value among
    the rows given, since "which offense hit the biggest plays" is the
    question this table exists to answer."""
    df = build_explosive_play_comparison(games, season_type=season_type)
    top_explosiveness_row = int(df["explosiveness"].idxmax())

    gt = (
        GT(df)
        .tab_header(title=html("Explosive Play Comparison"), subtitle=html(EXPLOSIVENESS_SUBTITLE))
        .fmt_image(columns="logo")
        .cols_label(logo=html(""), team=html("Team"), game=html("Game"), opponent=html("Opponent"), result=html("Result"))
        .cols_align(align="center", columns=["game", "opponent", "result"])
        .cols_width({"logo": "50px", "team": "130px", "game": "90px", "opponent": "130px", "result": "100px"})
    )
    gt = apply_explosiveness_metric_columns(gt)
    gt = base_table(gt)
    gt = gt.tab_style(style=style.text(weight="bold"), locations=loc.body(columns="team"))
    gt = gt.tab_style(
        style=style.text(weight="bold", color=WIN_COLOR),
        locations=loc.body(columns="explosiveness", rows=[top_explosiveness_row]),
    )
    return gt


if __name__ == "__main__":
    from src.viz.render import render_html_to_png

    games = [("Notre Dame", 2026, 1), ("Indiana", 2025, 1), ("Michigan", 2023, 1)]
    table = explosive_play_comparison_table(games)

    out_html = "src/viz/output/explosive_play_comparison.html"
    with open(out_html, "w") as f:
        f.write(table.as_raw_html())
    print(f"wrote {out_html}")

    out_png = render_html_to_png(table.as_raw_html(), "src/viz/output/explosive_play_comparison.png")
    print(f"wrote {out_png}")
