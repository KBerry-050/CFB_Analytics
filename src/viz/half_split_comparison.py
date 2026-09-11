"""First half vs. second half offense — one team's production and efficiency
(overall, and split into rushing/passing) across the two halves of a single
game, plus the team's prior-season average for reference, as a GT comparison
table (same visual grammar as `offense_profile_comparison.py`'s two-season
comparison: section groups, a colored delta column, the team's logo in the
header).

Pairs with `src/data/postgame.py`'s `get_game_half_splits()`. Deliberately
not part of `postgame_report.py`'s broadcast card, which keeps its own dark,
hand-built style (see that module's docstring) — this is a standalone
house-styled (`viz-style`) table meant to sit alongside that card, not
inside it.
"""

import pandas as pd
from great_tables import GT, html, loc, style

from src.data.postgame import get_game_half_splits, get_game_summary, resolve_game_id
from src.data.team_profile import get_team_advanced_season_stats, get_team_season_totals
from src.data.teams import get_teams
from src.viz.style import LOSS_COLOR, PERCENT_COL_WIDTH, WIN_COLOR, base_table, team_header_title

# (section, label, half-splits key, value formatter, delta formatter, color the
# delta, prior-season key). A `None` prior-season key means that metric is a
# raw half-total ("Total Yards", "Plays", ...) with no sensible season-average
# equivalent, per the request this table was built for — those show "-" in
# the prior-season column rather than a number that isn't really comparable.
#
# Every colored metric is "more is better", so unlike
# offense_profile_comparison.py's rank/stuff-rate/havoc rows, none needs an
# invert flag. "Plays"/"Rush Attempts"/"Pass Attempts" are left uncolored:
# running fewer of them isn't good or bad on its own (this game, ND ran
# *fewer* 2nd-half plays while scoring *more* — a sign of efficiency, not a
# decline), so red/green would imply a direction that isn't really there.
METRICS = [
    ("PRODUCTION", "Points", "points", lambda v: f"{v:.0f}", lambda d: f"{d:+.0f}", True, None),
    ("PRODUCTION", "Offensive Points", "offensive_points", lambda v: f"{v:.0f}", lambda d: f"{d:+.0f}", True, None),
    ("PRODUCTION", "Total Yards", "total_yards", lambda v: f"{v:.0f}", lambda d: f"{d:+.0f}", True, None),
    ("PRODUCTION", "Plays", "plays", lambda v: f"{v:.0f}", lambda d: f"{d:+.0f}", False, None),
    ("PRODUCTION", "Yards / Play", "yards_per_play", lambda v: f"{v:.1f}", lambda d: f"{d:+.1f}", True, "yards_per_play"),
    ("RUSHING", "Rush Yards", "rush_yards", lambda v: f"{v:.0f}", lambda d: f"{d:+.0f}", True, None),
    ("RUSHING", "Rush Attempts", "rush_attempts", lambda v: f"{v:.0f}", lambda d: f"{d:+.0f}", False, None),
    ("RUSHING", "Yards / Rush", "rush_yards_per_att", lambda v: f"{v:.1f}", lambda d: f"{d:+.1f}", True, "rush_yards_per_att"),
    ("RUSHING", "Rush Success Rate", "rush_success_rate", lambda v: f"{v:.1%}", lambda d: f"{d * 100:+.1f} pts", True, "rush_success_rate"),
    ("RUSHING", "Rush PPA / Att", "rush_ppa_per_att", lambda v: f"{v:.2f}", lambda d: f"{d:+.2f}", True, "rush_ppa_per_att"),
    ("PASSING", "Pass Yards", "pass_yards", lambda v: f"{v:.0f}", lambda d: f"{d:+.0f}", True, None),
    ("PASSING", "Pass Attempts", "pass_attempts", lambda v: f"{v:.0f}", lambda d: f"{d:+.0f}", False, None),
    ("PASSING", "Yards / Att", "pass_yards_per_att", lambda v: f"{v:.1f}", lambda d: f"{d:+.1f}", True, "pass_yards_per_att"),
    ("PASSING", "Pass Success Rate", "pass_success_rate", lambda v: f"{v:.1%}", lambda d: f"{d * 100:+.1f} pts", True, "pass_success_rate"),
    ("PASSING", "Pass PPA / Att", "pass_ppa_per_att", lambda v: f"{v:.2f}", lambda d: f"{d:+.2f}", True, "pass_ppa_per_att"),
    ("EFFICIENCY", "Success Rate", "success_rate", lambda v: f"{v:.1%}", lambda d: f"{d * 100:+.1f} pts", True, "success_rate"),
    ("EFFICIENCY", "Explosiveness", "explosiveness", lambda v: f"{v:.2f}", lambda d: f"{d:+.2f}", True, "explosiveness"),
    ("EFFICIENCY", "PPA / Play", "ppa_per_play", lambda v: f"{v:.3f}", lambda d: f"{d:+.3f}", True, "ppa_per_play"),
]


def _prior_season_offense_stats(team: str, prior_year: int) -> dict[str, float | None]:
    """The subset of `team`'s `prior_year` season averages that a game-half
    rate stat can actually be measured against — only keys that appear here
    get a prior-season value in the table; everything else shows "-"."""
    totals = get_team_season_totals(team, prior_year).iloc[0]
    advanced = get_team_advanced_season_stats(team, prior_year).iloc[0]
    plays = advanced["offense.plays"]
    return {
        "yards_per_play": totals["totalYards"] / plays if plays else None,
        "rush_yards_per_att": totals["rushingYards"] / totals["rushingAttempts"] if totals["rushingAttempts"] else None,
        "rush_success_rate": advanced["offense.rushingPlays.successRate"],
        "rush_ppa_per_att": advanced["offense.rushingPlays.ppa"],
        "pass_yards_per_att": totals["netPassingYards"] / totals["passAttempts"] if totals["passAttempts"] else None,
        "pass_success_rate": advanced["offense.passingPlays.successRate"],
        "pass_ppa_per_att": advanced["offense.passingPlays.ppa"],
        "success_rate": advanced["offense.successRate"],
        "explosiveness": advanced["offense.explosiveness"],
        "ppa_per_play": advanced["offense.ppa"],
    }


def build_half_comparison(team: str, year: int, week: int, season_type: str = "regular") -> pd.DataFrame:
    """One row per metric: section, label, formatted 1st/2nd-half values, a
    formatted delta (which way, if any, to color it), and the prior-season
    average for metrics where that comparison makes sense."""
    game_id = resolve_game_id(year, week, team, season_type=season_type)
    splits = get_game_half_splits(game_id, year, week, team, season_type=season_type).set_index("half")
    prior_stats = _prior_season_offense_stats(team, year - 1)

    rows = []
    for section, label, key, fmt, delta_fmt, color_delta, prior_key in METRICS:
        v1, v2 = splits.loc[1, key], splits.loc[2, key]
        has_delta = pd.notna(v1) and pd.notna(v2)
        delta = (v2 - v1) if has_delta else None
        raw_sign = 0 if not has_delta or delta == 0 else (1 if delta > 0 else -1)
        delta_sign = raw_sign if color_delta else 0

        prior_value = prior_stats.get(prior_key) if prior_key else None
        rows.append(
            {
                "section": section,
                "metric": label,
                "first_half_display": "N/A" if pd.isna(v1) else fmt(v1),
                "second_half_display": "N/A" if pd.isna(v2) else fmt(v2),
                "delta_display": "N/A" if delta is None else delta_fmt(delta),
                "delta_sign": delta_sign,
                "prior_year_display": "-" if prior_value is None else fmt(prior_value),
            }
        )
    return pd.DataFrame(rows)


def half_comparison_table(team: str, year: int, week: int, season_type: str = "regular") -> GT:
    """The 1st-half-vs-2nd-half offense table (see module docstring) for any
    team/game: production (overall, rushing, passing) and efficiency, with a
    colored delta column, a prior-season reference column, and the team's
    logo in the header."""
    df = build_half_comparison(team, year, week, season_type=season_type)
    prior_year = year - 1

    game_id = resolve_game_id(year, week, team, season_type=season_type)
    summary = get_game_summary(game_id).iloc[0]
    is_home = summary["home_team"] == team
    opponent = summary["away_team"] if is_home else summary["home_team"]
    team_points = summary["home_points"] if is_home else summary["away_points"]
    opp_points = summary["away_points"] if is_home else summary["home_points"]

    teams = get_teams(year)
    logo_url = teams.loc[teams["school"] == team, "logo"].iloc[0]

    gt = (
        GT(
            df[["section", "metric", "first_half_display", "second_half_display", "delta_display", "prior_year_display"]],
            groupname_col="section",
        )
        .tab_header(
            title=team_header_title(f"{team} Offense: 1st Half vs. 2nd Half", logo_url),
            subtitle=html(f"CFB {year} Week {week} vs. {opponent} ({team_points:.0f}-{opp_points:.0f})"),
        )
        .cols_label(
            metric=html(""),
            first_half_display=html("1st Half"),
            second_half_display=html("2nd Half"),
            delta_display=html("&Delta;"),
            prior_year_display=html(str(prior_year)),
        )
        .cols_align(align="center", columns=["first_half_display", "second_half_display", "delta_display", "prior_year_display"])
        .cols_width(
            {
                "metric": "180px",
                "first_half_display": PERCENT_COL_WIDTH,
                "second_half_display": PERCENT_COL_WIDTH,
                "delta_display": PERCENT_COL_WIDTH,
                "prior_year_display": PERCENT_COL_WIDTH,
            }
        )
    )
    gt = base_table(gt)
    gt = gt.tab_style(style=style.text(weight="bold"), locations=loc.row_groups())
    gt = gt.tab_style(style=style.text(color="#999999"), locations=loc.body(columns="prior_year_display"))
    gt = gt.tab_source_note(
        source_note=html(
            "Points includes a Notre Dame defensive touchdown (DJ McKinney 55-yd interception return, "
            "3rd quarter); Offensive Points excludes it. The listed year is Notre Dame's full-season average "
            "for that stat, shown only where a half's total is meaningfully comparable to a season rate."
        )
    )

    for i, sign in enumerate(df["delta_sign"]):
        if sign != 0:
            gt = gt.tab_style(
                style=style.text(color=WIN_COLOR if sign == 1 else LOSS_COLOR, weight="bold"),
                locations=loc.body(columns="delta_display", rows=[i]),
            )
    return gt


if __name__ == "__main__":
    from src.viz.render import render_html_to_png
    from src.viz.style import frame_png_with_turf

    table = half_comparison_table("Notre Dame", 2026, 1)
    out_html = "src/viz/output/nd_wisconsin_2026_wk1_half_comparison.html"
    with open(out_html, "w") as f:
        f.write(table.as_raw_html())
    print(f"wrote {out_html}")

    png_path = render_html_to_png(table.as_raw_html(), "src/viz/output/nd_wisconsin_2026_wk1_half_comparison.png")
    framed = frame_png_with_turf(png_path.read_bytes())
    png_path.write_bytes(framed)
    print(f"wrote {png_path}")
