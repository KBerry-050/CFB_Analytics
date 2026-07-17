import pandas as pd
from great_tables import GT, html

from src.data.stats import get_offense_season_stats
from src.data.teams import get_teams
from src.viz.style import base_table, style_team_text_by_color


def top_offenses_table(year: int, top_n: int = 25) -> GT:
    """Top FBS offenses for a season, ranked by offensive PPA/play (efficiency),
    with total touchdowns, total yards, and efficiency columns."""
    offense = get_offense_season_stats(year)
    teams = get_teams(year)[["school", "logo", "color"]].rename(columns={"school": "team"})

    df = (
        offense.merge(teams, on="team", how="left")
        .sort_values("ppa", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )
    df.insert(0, "rank", range(1, len(df) + 1))
    df["color"] = df["color"].fillna("#333333")

    gt = (
        GT(
            df[
                [
                    "rank",
                    "logo",
                    "team",
                    "conference",
                    "total_tds",
                    "total_yards",
                    "yards_per_game",
                    "ppa",
                    "success_rate",
                ]
            ],
            rowname_col="rank",
        )
        .tab_header(
            title=f"Top {top_n} FBS Offenses — {year}",
            subtitle="Ranked by offensive predicted points added (PPA) per play",
        )
        .fmt_image(columns="logo")
        .fmt_integer(columns=["total_tds", "total_yards"])
        .fmt_number(columns="yards_per_game", decimals=1)
        .fmt_number(columns="ppa", decimals=2)
        .fmt_percent(columns="success_rate", decimals=1)
        .cols_label(
            logo=html(""),
            team="Team",
            conference="Conference",
            total_tds="Total TDs",
            total_yards="Total Yards",
            yards_per_game="Yards / Game",
            ppa="PPA / Play",
            success_rate="Success Rate",
        )
        .cols_align(align="center", columns=["total_tds", "total_yards", "yards_per_game", "ppa", "success_rate"])
    )
    gt = base_table(gt)
    gt = style_team_text_by_color(gt, df["color"].tolist(), "team")
    return gt


if __name__ == "__main__":
    table = top_offenses_table(2025)
    out_path = "src/viz/output/top_offenses_2025.html"
    import os

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    table.write_raw_html(out_path)
    print(f"wrote {out_path}")
