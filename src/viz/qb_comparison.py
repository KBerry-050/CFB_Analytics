"""QB Comparison Report — compares two quarterback seasons (production,
efficiency, attempts) using CFBD's per-player season overview. Works for any
two players/years/team (`qb_comparison_table(team, player_a, year_a,
player_b, year_b)`); Notre Dame's Riley Leonard (2024) vs. C.J. Carr (2025)
was the pilot case.

Note: pass-depth-of-target splits (0-10/10-20/20+ yards) were requested but
aren't available anywhere in CFBD's data — checked season stat categories,
the player overview endpoint, and raw play-by-play (only `yardsGained`
exists, which is total yards after the catch, not throw depth). Omitted for
now per explicit instruction; a v2 can revisit if another data source shows up.
"""

import pandas as pd
from great_tables import GT, html, loc, style

from src.data.team_profile import get_player_season_overview
from src.data.teams import get_teams
from src.viz.style import LOSS_COLOR, WIN_COLOR, base_table, dual_logo_header

# (section, label, data key, value formatter, delta formatter, invert-for-color)
METRICS = [
    ("PRODUCTION", "Total Yards", "total_yards", lambda v: f"{v:,.0f}", lambda d: f"{d:+,.0f}", False),
    ("PRODUCTION", "Yards / Game", "yards_per_game", lambda v: f"{v:.1f}", lambda d: f"{d:+.1f}", False),
    ("PRODUCTION", "Passing Yards", "passing_yards", lambda v: f"{v:,.0f}", lambda d: f"{d:+,.0f}", False),
    ("PRODUCTION", "Passing Yards / Game", "passing_yards_per_game", lambda v: f"{v:.1f}", lambda d: f"{d:+.1f}", False),
    ("PRODUCTION", "Rushing Yards", "rushing_yards", lambda v: f"{v:,.0f}", lambda d: f"{d:+,.0f}", False),
    ("PRODUCTION", "Rushing Yards / Game", "rushing_yards_per_game", lambda v: f"{v:.1f}", lambda d: f"{d:+.1f}", False),
    ("PRODUCTION", "Passing TDs", "passing_tds", lambda v: f"{v:.0f}", lambda d: f"{d:+.0f}", False),
    ("PRODUCTION", "Passing TDs / Game", "passing_tds_per_game", lambda v: f"{v:.2f}", lambda d: f"{d:+.2f}", False),
    ("PRODUCTION", "Rushing TDs", "rushing_tds", lambda v: f"{v:.0f}", lambda d: f"{d:+.0f}", False),
    ("PRODUCTION", "Rushing TDs / Game", "rushing_tds_per_game", lambda v: f"{v:.2f}", lambda d: f"{d:+.2f}", False),
    ("PRODUCTION", "Interceptions", "interceptions", lambda v: f"{v:.0f}", lambda d: f"{d:+.0f}", True),
    ("PRODUCTION", "Interceptions / Game", "interceptions_per_game", lambda v: f"{v:.2f}", lambda d: f"{d:+.2f}", True),
    ("EFFICIENCY", "PPA / Play", "ppa_all", lambda v: f"{v:.2f}", lambda d: f"{d:+.2f}", False),
    ("EFFICIENCY", "Completion %", "completion_pct", lambda v: f"{v:.1%}", lambda d: f"{d * 100:+.1f} pts", False),
    ("EFFICIENCY", "Passing PPA / Play", "ppa_pass", lambda v: f"{v:.2f}", lambda d: f"{d:+.2f}", False),
    ("EFFICIENCY", "Rushing PPA / Play", "ppa_rush", lambda v: f"{v:.2f}", lambda d: f"{d:+.2f}", False),
    ("EFFICIENCY", "Standard Downs PPA", "ppa_standard_downs", lambda v: f"{v:.2f}", lambda d: f"{d:+.2f}", False),
    ("EFFICIENCY", "Passing Downs PPA", "ppa_passing_downs", lambda v: f"{v:.2f}", lambda d: f"{d:+.2f}", False),
    ("ATTEMPTS", "Attempts", "attempts", lambda v: f"{v:.0f}", lambda d: f"{d:+.0f}", False),
    ("ATTEMPTS", "Completions", "completions", lambda v: f"{v:.0f}", lambda d: f"{d:+.0f}", False),
    ("ATTEMPTS", "Yards / Attempt", "yards_per_attempt", lambda v: f"{v:.1f}", lambda d: f"{d:+.1f}", False),
]


def _qb_season_data(team: str, player: str, year: int) -> dict:
    """Pull and derive every value the comparison table needs for one QB
    season: production totals, efficiency (PPA splits, completion %), and
    attempt volume."""
    overview = get_player_season_overview(player, team, year).iloc[0]
    games = overview["games"]
    passing_yards = float(overview["passing.YDS"])
    rushing_yards = float(overview.get("rushing.YDS", 0) or 0)

    passing_tds = float(overview["passing.TD"])
    rushing_tds = float(overview.get("rushing.TD", 0) or 0)
    interceptions = float(overview["passing.INT"])

    return {
        "total_yards": passing_yards + rushing_yards,
        "yards_per_game": (passing_yards + rushing_yards) / games,
        "passing_yards": passing_yards,
        "passing_yards_per_game": passing_yards / games,
        "rushing_yards": rushing_yards,
        "rushing_yards_per_game": rushing_yards / games,
        "passing_tds": passing_tds,
        "passing_tds_per_game": passing_tds / games,
        "rushing_tds": rushing_tds,
        "rushing_tds_per_game": rushing_tds / games,
        "interceptions": interceptions,
        "interceptions_per_game": interceptions / games,
        "ppa_all": overview["ppa.average.all"],
        "completion_pct": float(overview["passing.PCT"]),
        "ppa_pass": overview["ppa.average.pass"],
        "ppa_rush": overview["ppa.average.rush"],
        "ppa_standard_downs": overview["ppa.average.standardDowns"],
        "ppa_passing_downs": overview["ppa.average.passingDowns"],
        "attempts": float(overview["passing.ATT"]),
        "completions": float(overview["passing.COMPLETIONS"]),
        "yards_per_attempt": float(overview["passing.YPA"]),
    }


def build_qb_comparison(team: str, player_a: str, year_a: int, player_b: str, year_b: int) -> pd.DataFrame:
    """One row per metric: section, label, formatted player_a/player_b
    values, a formatted delta, and which way to color that delta."""
    data_a = _qb_season_data(team, player_a, year_a)
    data_b = _qb_season_data(team, player_b, year_b)

    rows = []
    for section, label, key, fmt, delta_fmt, invert in METRICS:
        va, vb = data_a[key], data_b[key]
        delta = vb - va
        raw_sign = 0 if delta == 0 else (1 if delta > 0 else -1)
        delta_sign = raw_sign * (-1 if invert else 1)
        rows.append(
            {
                "section": section,
                "metric": label,
                "player_a_display": fmt(va),
                "player_b_display": fmt(vb),
                "delta_display": delta_fmt(delta),
                "delta_sign": delta_sign,
            }
        )
    return pd.DataFrame(rows)


def qb_comparison_table(team: str, player_a: str, year_a: int, player_b: str, year_b: int) -> GT:
    """QB Comparison Report (see module docstring) for any two players:
    production, efficiency, and attempt volume, with a colored delta column
    and the team's logo in both top corners."""
    df = build_qb_comparison(team, player_a, year_a, player_b, year_b)

    teams = get_teams(year_b)
    logo_match = teams.loc[teams["school"] == team, "logo"]
    logo_url = logo_match.iloc[0] if not logo_match.empty else None
    logo_html = f'<img src="{logo_url}" style="height:40px;">' if logo_url else None

    games_a = get_player_season_overview(player_a, team, year_a)["games"].iloc[0]
    games_b = get_player_season_overview(player_b, team, year_b)["games"].iloc[0]
    subtitle = (
        f"{player_a}: {games_a:.0f} games&nbsp;&nbsp;&bull;&nbsp;&nbsp;{player_b}: {games_b:.0f} games"
    )

    col_a, col_b = "player_a_display", "player_b_display"
    gt = (
        GT(
            df[["section", "metric", col_a, col_b, "delta_display"]],
            groupname_col="section",
        )
        .tab_header(
            title=dual_logo_header(f"{team} QBs: {player_a} ({year_a}) vs. {player_b} ({year_b})", logo_url, logo_html),
            subtitle=html(subtitle),
        )
        .cols_label(
            metric=html(""),
            **{col_a: html(f"{player_a}<br>{year_a}"), col_b: html(f"{player_b}<br>{year_b}")},
            delta_display=html("&Delta;"),
        )
        .cols_align(align="center", columns=[col_a, col_b, "delta_display"])
        .cols_width(
            {
                "metric": "200px",
                col_a: "140px",
                col_b: "140px",
                "delta_display": "130px",
            }
        )
        .fmt_markdown(columns=[col_a, col_b])
    )
    gt = base_table(gt)
    gt = gt.tab_style(style=style.text(weight="bold"), locations=loc.row_groups())

    for i, sign in enumerate(df["delta_sign"]):
        if sign != 0:
            gt = gt.tab_style(
                style=style.text(color=WIN_COLOR if sign == 1 else LOSS_COLOR, weight="bold"),
                locations=loc.body(columns="delta_display", rows=[i]),
            )
    return gt


if __name__ == "__main__":
    from src.viz.render import render_html_to_png

    table = qb_comparison_table("Notre Dame", "Riley Leonard", 2024, "C.J. Carr", 2025)
    out_html = "src/viz/output/notre_dame_qb_leonard_vs_carr.html"
    with open(out_html, "w") as f:
        f.write(table.as_raw_html())
    print(f"wrote {out_html}")

    out_png = render_html_to_png(table.as_raw_html(), "src/viz/output/notre_dame_qb_leonard_vs_carr.png")
    print(f"wrote {out_png}")
