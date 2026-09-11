"""Matchup Preview — pre-game comparison of two teams' team-level metrics
and roster continuity (headcount, by position group). Built for a
not-yet-played game, so it deliberately avoids anything results-dependent
(SRS/Elo, box scores, advanced game stats) — only season-entering signals:
preseason SP+/FPI, recruiting/talent, returning production, and prior-year
record for context. Works for any two teams/year
(`matchup_preview_table(team_a, team_b, year)`); Notre Dame vs. Wisconsin,
2026 week 1, was the pilot case.
"""

import pandas as pd
from great_tables import GT, html, loc, style

from src.data.team_profile import (
    get_all_teams_fpi_ratings,
    get_all_teams_sp_ratings,
    get_team_recruiting_ranking,
    get_team_records,
    get_team_returning_production,
    get_team_roster,
    get_team_talent,
)
from src.data.teams import get_teams
from src.viz.style import WIN_COLOR, base_table, dual_logo_header

# Position-group breakdown for the roster-continuity section, by roster
# headcount (matched on CFBD player id across seasons) rather than
# usage/PPA-based returning production — that split doesn't cover offensive
# or defensive linemen at all, so headcount is what's actually comparable
# across every group. LS/P/PK are folded into a single "ST" group.
POSITION_GROUPS = ["QB", "RB", "WR", "TE", "OL", "DL", "LB", "CB", "S", "ST"]
_ST_POSITIONS = {"LS", "P", "PK"}

# (section, label, data key, value formatter, higher_is_better)
METRICS = [
    ("TEAM METRICS", "SP+ Rating", "sp_rating", lambda v: f"{v:.1f}", True),
    ("TEAM METRICS", "SP+ Rank", "sp_rank", lambda v: f"No. {v:.0f}", False),
    ("TEAM METRICS", "FPI", "fpi", lambda v: f"{v:.1f}", True),
    ("TEAM METRICS", "FPI Rank", "fpi_rank", lambda v: f"No. {v:.0f}", False),
    ("TEAM METRICS", "Recruiting Rank", "recruiting_rank", lambda v: f"No. {v:.0f}", False),
    ("TEAM METRICS", "Talent Composite", "talent", lambda v: f"{v:.1f}", True),
    ("TEAM METRICS", "Returning Production (Off. PPA)", "returning_prod_pct", lambda v: f"{v:.0%}", True),
    *[
        ("ROSTER CONTINUITY", f"{pos} Returning", f"returning_{pos.lower()}", lambda v: f"{v:.0%}", True)
        for pos in POSITION_GROUPS
    ],
    ("ROSTER CONTINUITY", "Overall Returning", "returning_overall", lambda v: f"{v:.0%}", True),
]


def _returning_by_position(team: str, prior_year: int, year: int) -> dict[str, float | None]:
    """Share of each position group's `prior_year` roster (by headcount)
    still on the team's `year` roster, matched by CFBD player id."""
    roster_prior = get_team_roster(team, prior_year).copy()
    roster_prior["group"] = roster_prior["position"].where(~roster_prior["position"].isin(_ST_POSITIONS), "ST")
    roster_this_ids = set(get_team_roster(team, year)["id"])

    result = {}
    for pos in POSITION_GROUPS:
        group_ids = set(roster_prior.loc[roster_prior["group"] == pos, "id"])
        result[pos] = (len(group_ids & roster_this_ids) / len(group_ids)) if group_ids else None

    all_ids = set(roster_prior["id"])
    result["overall"] = (len(all_ids & roster_this_ids) / len(all_ids)) if all_ids else None
    return result


def team_entering_season_metrics(team: str, year: int) -> dict:
    """Season-entering signals for `team` going into `year`: preseason
    SP+/FPI, recruiting/talent for the incoming class, returning production,
    and prior-year record for context — nothing that depends on `year`'s
    games having been played."""
    sp_row = get_all_teams_sp_ratings(year).pipe(lambda df: df[df["team"] == team])
    fpi_row = get_all_teams_fpi_ratings(year).pipe(lambda df: df[df["team"] == team])

    records = get_team_records(team, year - 1)
    talent = get_team_talent(team, year)
    recruiting = get_team_recruiting_ranking(team, year)
    returning = get_team_returning_production(team, year)

    by_position = _returning_by_position(team, year - 1, year)

    return {
        "record": (
            f"{int(records['total.wins'].iloc[0])}-{int(records['total.losses'].iloc[0])}"
            if not records.empty
            else None
        ),
        "sp_rating": sp_row["rating"].iloc[0] if not sp_row.empty else None,
        "sp_rank": sp_row["ranking"].iloc[0] if not sp_row.empty else None,
        "fpi": fpi_row["fpi"].iloc[0] if not fpi_row.empty else None,
        "fpi_rank": fpi_row["resumeRanks.fpi"].iloc[0] if not fpi_row.empty else None,
        "recruiting_rank": recruiting["rank"].iloc[0] if not recruiting.empty else None,
        "talent": talent["talent"].iloc[0] if not talent.empty else None,
        "returning_prod_pct": returning["percentPPA"].iloc[0] if not returning.empty else None,
        **{f"returning_{pos.lower()}": by_position[pos] for pos in POSITION_GROUPS},
        "returning_overall": by_position["overall"],
    }


def build_matchup_preview(team_a: str, team_b: str, year: int) -> pd.DataFrame:
    """One row per metric: section, label, formatted team_a/team_b values,
    and which side (if either) gets "edge" styling."""
    data_a = team_entering_season_metrics(team_a, year)
    data_b = team_entering_season_metrics(team_b, year)

    rows = [
        {
            # Context only — there's no single "higher is better" reading
            # across two different teams' opponent-adjusted schedules, so
            # this row is never edge-colored.
            "section": "TEAM METRICS",
            "metric": f"{year - 1} Record",
            "a_display": data_a["record"] or "N/A",
            "b_display": data_b["record"] or "N/A",
            "edge": 0,
        }
    ]

    for section, label, key, fmt, higher_is_better in METRICS:
        va, vb = data_a[key], data_b[key]
        edge = 0
        if va is not None and vb is not None and va != vb:
            a_wins = (va > vb) if higher_is_better else (va < vb)
            edge = 1 if a_wins else -1
        rows.append(
            {
                "section": section,
                "metric": label,
                "a_display": "N/A" if va is None else fmt(va),
                "b_display": "N/A" if vb is None else fmt(vb),
                "edge": edge,
            }
        )
    return pd.DataFrame(rows)


def matchup_preview_table(team_a: str, team_b: str, year: int) -> GT:
    """Pre-game comparison table for `team_a` vs. `team_b` in `year`: team
    metrics (preseason SP+/FPI, recruiting/talent, returning production,
    prior-year record) and roster continuity by position group. The team
    with the better reading on each well-defined row is bolded/colored."""
    df = build_matchup_preview(team_a, team_b, year)

    teams = get_teams(year)
    logo_a = teams.loc[teams["school"] == team_a, "logo"]
    logo_b = teams.loc[teams["school"] == team_b, "logo"]
    logo_a_url = logo_a.iloc[0] if not logo_a.empty else None
    logo_b_html = f'<img src="{logo_b.iloc[0]}" style="height:40px;">' if not logo_b.empty else None

    gt = (
        GT(
            df[["section", "metric", "a_display", "b_display"]],
            groupname_col="section",
        )
        .tab_header(title=dual_logo_header(f"{team_a} vs. {team_b} — {year} Preview", logo_a_url, logo_b_html))
        .cols_label(metric=html(""), a_display=html(team_a), b_display=html(team_b))
        .cols_align(align="center", columns=["a_display", "b_display"])
        .cols_width({"metric": "260px", "a_display": "170px", "b_display": "170px"})
    )
    gt = base_table(gt)
    gt = gt.tab_style(style=style.text(weight="bold"), locations=loc.row_groups())

    for i, edge in enumerate(df["edge"]):
        if edge != 0:
            col = "a_display" if edge == 1 else "b_display"
            gt = gt.tab_style(
                style=style.text(color=WIN_COLOR, weight="bold"),
                locations=loc.body(columns=col, rows=[i]),
            )
    return gt


if __name__ == "__main__":
    from src.viz.render import render_html_to_png

    table = matchup_preview_table("Notre Dame", "Wisconsin", 2026)
    out_html = "src/viz/output/notre_dame_vs_wisconsin_2026_preview.html"
    with open(out_html, "w") as f:
        f.write(table.as_raw_html())
    print(f"wrote {out_html}")

    out_png = render_html_to_png(table.as_raw_html(), "src/viz/output/notre_dame_vs_wisconsin_2026_preview.png")
    print(f"wrote {out_png}")
