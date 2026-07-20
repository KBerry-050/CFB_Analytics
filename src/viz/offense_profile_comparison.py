import pandas as pd
from great_tables import GT, html, loc, style

from src.data.team_profile import (
    get_all_teams_schedule,
    get_team_advanced_season_stats,
    get_team_game_stats,
    get_team_returning_production,
    get_team_roster,
    get_team_season_totals,
)
from src.data.teams import get_teams
from src.viz.style import LOSS_COLOR, WIN_COLOR, base_table, dual_logo_header

# Position-group breakdown for the roster-continuity section. Usage/PPA-based
# returning-production splits (what CFBD's `returning_production` endpoint
# reports) don't cover offensive linemen at all — they never accrue
# individual PPA or recorded-play usage — so this uses plain roster-headcount
# continuity instead, which is comparable across every offensive position
# group, OL included.
POSITION_GROUPS = ["QB", "RB", "WR", "TE", "OL"]

# (section, label, data key, value formatter, delta formatter, invert-for-color, color-the-delta)
METRICS = [
    ("PRODUCTION", "Yards / Game", "yards_per_game", lambda v: f"{v:.1f}", lambda d: f"{d:+.1f}", False, True),
    ("PRODUCTION", "Passing Yards / Game", "passing_yards_per_game", lambda v: f"{v:.1f}", lambda d: f"{d:+.1f}", False, True),
    ("PRODUCTION", "Rushing Yards / Game", "rushing_yards_per_game", lambda v: f"{v:.1f}", lambda d: f"{d:+.1f}", False, True),
    ("PRODUCTION", "TDs / Game", "tds_per_game", lambda v: f"{v:.2f}", lambda d: f"{d:+.2f}", False, True),
    ("PRODUCTION", "Points / Game", "points_per_game", lambda v: f"{v:.1f}", lambda d: f"{d:+.1f}", False, True),
    ("PRODUCTION", "PPG - Natl. Rank", "points_per_game_rank", lambda v: f"No. {v:.0f}", lambda d: f"{-d:+.0f} spots", True, True),
    ("EFFICIENCY", "PPA / Play", "off_ppa", lambda v: f"{v:.2f}", lambda d: f"{d:+.2f}", False, True),
    ("EFFICIENCY", "Success Rate", "off_success_rate", lambda v: f"{v:.1%}", lambda d: f"{d * 100:+.1f} pts", False, True),
    ("EFFICIENCY", "Explosiveness", "explosiveness", lambda v: f"{v:.2f}", lambda d: f"{d:+.2f}", False, True),
    ("EFFICIENCY", "Points / Opportunity", "points_per_opportunity", lambda v: f"{v:.2f}", lambda d: f"{d:+.2f}", False, True),
    ("EFFICIENCY", "Stuff Rate", "stuff_rate", lambda v: f"{v:.1%}", lambda d: f"{d * 100:+.1f} pts", True, True),
    ("EFFICIENCY", "Havoc Rate Allowed", "havoc_allowed", lambda v: f"{v:.1%}", lambda d: f"{d * 100:+.1f} pts", True, True),
    ("ROSTER CONTINUITY", "Returning Production", "returning_production_pct", lambda v: f"{v:.1%}", lambda d: f"{d * 100:+.1f} pts", False, True),
    *[
        (
            "ROSTER CONTINUITY",
            f"{pos} Returning",
            f"returning_{pos.lower()}",
            lambda v: f"{v:.0%}",
            lambda d: f"{d * 100:+.0f} pts",
            False,
            True,
        )
        for pos in POSITION_GROUPS
    ],
]


def _returning_by_position(team: str, prior_year: int, year: int) -> dict[str, float | None]:
    """Share of each position group's roster (by headcount) still on the
    team a year later."""
    roster_prior = get_team_roster(team, prior_year)
    roster_this_ids = set(get_team_roster(team, year)["id"])

    result = {}
    for pos in POSITION_GROUPS:
        group_ids = set(roster_prior.loc[roster_prior["position"] == pos, "id"])
        result[pos] = (len(group_ids & roster_this_ids) / len(group_ids)) if group_ids else None
    return result


def _ppg_national_rank(team: str, year: int) -> int | None:
    """`team`'s rank in points per game among all FBS teams that season
    (1 = highest PPG in the country)."""
    schedule = get_all_teams_schedule(year)
    home = schedule[["homeTeam", "homePoints"]].rename(columns={"homeTeam": "team", "homePoints": "points"})
    away = schedule[["awayTeam", "awayPoints"]].rename(columns={"awayTeam": "team", "awayPoints": "points"})
    long_scores = pd.concat([home, away], ignore_index=True).dropna(subset=["points"])
    ppg = long_scores.groupby("team")["points"].mean()

    fbs_teams = set(get_teams(year)["school"])
    ppg = ppg[ppg.index.isin(fbs_teams)]

    ranked = ppg.rank(ascending=False, method="min")
    return int(ranked[team]) if team in ranked.index else None


def _season_offense_data(team: str, year: int) -> dict:
    """Pull and derive every value the comparison table needs for one
    team-season: per-game production, advanced efficiency splits, and
    roster-continuity signals (overall returning production % from the prior
    year, plus a position-group roster-continuity breakdown)."""
    totals = get_team_season_totals(team, year).iloc[0]
    advanced = get_team_advanced_season_stats(team, year).iloc[0]
    games = totals["games"]

    box_scores = get_team_game_stats(team, year)
    box_scores = box_scores[box_scores["team"] == team]
    points = pd.to_numeric(box_scores["points"], errors="coerce").sum()

    returning = get_team_returning_production(team, year)
    returning_pct = returning["percentPPA"].iloc[0] if not returning.empty else None

    by_position = _returning_by_position(team, year - 1, year)

    return {
        "games": games,
        "yards_per_game": totals["totalYards"] / games,
        "passing_yards_per_game": totals["netPassingYards"] / games,
        "rushing_yards_per_game": totals["rushingYards"] / games,
        "tds_per_game": (totals["rushingTDs"] + totals["passingTDs"]) / games,
        "points_per_game": points / games,
        "points_per_game_rank": _ppg_national_rank(team, year),
        "off_ppa": advanced["offense.ppa"],
        "off_success_rate": advanced["offense.successRate"],
        "explosiveness": advanced["offense.explosiveness"],
        "points_per_opportunity": advanced["offense.pointsPerOpportunity"],
        "stuff_rate": advanced["offense.stuffRate"],
        "havoc_allowed": advanced["offense.havoc.total"],
        "returning_production_pct": returning_pct,
        **{f"returning_{pos.lower()}": by_position[pos] for pos in POSITION_GROUPS},
    }



# ONE-OFF MANUAL OVERRIDE — do not extend this pattern to other team/year
# analyses without checking with the user first; ask how they want it
# handled instead of hardcoding silently.
#
# Notre Dame's "QB Returning" headcount says 67%/60%, but that's counting
# backups who stuck on the roster — the actual *starter* was new both years
# (Riley Leonard arrived via transfer for 2024, CJ Carr took over for 2025),
# which the roster-continuity metric can't distinguish. Per explicit
# instruction, this replaces that one row's display for this exact
# team/year pair only; the underlying computed value is untouched for any
# other query.
QB_STARTER_OVERRIDES = {
    ("Notre Dame", 2024, 2025): ("New -<br>Riley Leonard", "New -<br>CJ Carr"),
}


def build_offense_profile_comparison(team: str, year_a: int, year_b: int) -> pd.DataFrame:
    """One row per metric: section, label, formatted year_a/year_b values,
    a formatted delta, and whether/which way to color that delta."""
    data_a = _season_offense_data(team, year_a)
    data_b = _season_offense_data(team, year_b)

    rows = []
    for section, label, key, fmt, delta_fmt, invert, color_delta in METRICS:
        va, vb = data_a[key], data_b[key]
        has_delta = va is not None and vb is not None
        delta = (vb - va) if has_delta else None
        raw_sign = 0 if not has_delta or delta == 0 else (1 if delta > 0 else -1)
        delta_sign = raw_sign * (-1 if invert else 1)
        rows.append(
            {
                "section": section,
                "metric": label,
                "year_a_display": "N/A" if va is None else fmt(va),
                "year_b_display": "N/A" if vb is None else fmt(vb),
                "delta_display": "N/A" if delta is None else delta_fmt(delta),
                "delta_sign": delta_sign if color_delta else 0,
            }
        )

    override = QB_STARTER_OVERRIDES.get((team, year_a, year_b))
    if override:
        qb_row = next(r for r in rows if r["metric"] == "QB Returning")
        qb_row["year_a_display"], qb_row["year_b_display"] = override
        qb_row["delta_display"] = ""
        qb_row["delta_sign"] = 0

    return pd.DataFrame(rows)


def offense_profile_comparison_table(team: str, year_a: int, year_b: int) -> GT:
    """Notre Dame-style (any team works) offensive profile comparison across
    two seasons: per-game production, efficiency, and roster continuity
    (overall + by position group), with a colored delta column and the
    team's logo in both top corners."""
    df = build_offense_profile_comparison(team, year_a, year_b)

    teams = get_teams(year_b)
    logo_match = teams.loc[teams["school"] == team, "logo"]
    logo_url = logo_match.iloc[0] if not logo_match.empty else None
    logo_html = f'<img src="{logo_url}" style="height:40px;">' if logo_url else None

    games_a = get_team_season_totals(team, year_a)["games"].iloc[0]
    games_b = get_team_season_totals(team, year_b)["games"].iloc[0]
    subtitle = f"{year_a}: {games_a:.0f} games&nbsp;&nbsp;&bull;&nbsp;&nbsp;{year_b}: {games_b:.0f} games"

    gt = (
        GT(
            df[["section", "metric", "year_a_display", "year_b_display", "delta_display"]],
            groupname_col="section",
        )
        .tab_header(
            title=dual_logo_header(f"{team} Offense: {year_a} vs. {year_b}", logo_url, logo_html),
            subtitle=html(subtitle),
        )
        .cols_label(
            metric=html(""),
            year_a_display=html(str(year_a)),
            year_b_display=html(str(year_b)),
            delta_display=html("&Delta;"),
        )
        .cols_align(align="center", columns=["year_a_display", "year_b_display", "delta_display"])
        .cols_width(
            {
                "metric": "220px",
                "year_a_display": "130px",
                "year_b_display": "130px",
                "delta_display": "130px",
            }
        )
        .fmt_markdown(columns=["year_a_display", "year_b_display"])
    )
    gt = base_table(gt)
    gt = gt.tab_style(
        style=style.text(weight="bold"),
        locations=loc.row_groups(),
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

    table = offense_profile_comparison_table("Notre Dame", 2024, 2025)
    out_html = "src/viz/output/notre_dame_offense_2024_vs_2025.html"
    with open(out_html, "w") as f:
        f.write(table.as_raw_html())
    print(f"wrote {out_html}")

    out_png = render_html_to_png(table.as_raw_html(), "src/viz/output/notre_dame_offense_2024_vs_2025.png")
    print(f"wrote {out_png}")
