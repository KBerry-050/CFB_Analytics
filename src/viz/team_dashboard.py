import pandas as pd
from great_tables import GT, html, loc, style

from src.data.team_profile import (
    get_team_advanced_game_stats,
    get_team_advanced_season_stats,
    get_team_game_stats,
    get_team_pregame_win_probabilities,
    get_team_ratings,
    get_team_recruiting_ranking,
    get_team_records,
    get_team_schedule,
    get_team_talent,
)
from src.data.teams import get_teams
from src.viz.render import combine_gt_tables, render_html_to_png
from src.viz.style import (
    LOSS_COLOR,
    NARROW_COL_WIDTH,
    PERCENT_COL_WIDTH,
    RATING_COL_WIDTH,
    WIN_COLOR,
    base_table,
    style_team_text_by_color,
    team_header_title,
)


def _team_logo_url(team: str, year: int) -> str | None:
    teams = get_teams(year)
    match = teams.loc[teams["school"] == team, "logo"]
    return match.iloc[0] if not match.empty else None


def team_season_summary_table(team: str, year: int) -> GT:
    """Single-row scorecard of season-level context: record, ratings, efficiency."""
    records = get_team_records(team, year).iloc[0]
    ratings = get_team_ratings(team, year).iloc[0]
    advanced = get_team_advanced_season_stats(team, year).iloc[0]
    talent = get_team_talent(team, year)
    recruiting = get_team_recruiting_ranking(team, year)

    row = {
        "team": team,
        "record": f"{int(records['total.wins'])}-{int(records['total.losses'])}",
        "home_record": f"{int(records['homeGames.wins'])}-{int(records['homeGames.losses'])}",
        "away_record": f"{int(records['awayGames.wins'])}-{int(records['awayGames.losses'])}",
        "conference": records["conference"],
        "sp_plus": f"{ratings['sp.rating']:.1f} (No. {int(ratings['sp.ranking'])})",
        "srs": f"{ratings['srs.rating']:.1f} (No. {int(ratings['srs.ranking'])})",
        "fpi": f"{ratings['fpi.fpi']:.1f}",
        "elo": f"{int(ratings['elo.elo'])}",
        "off_ppa": advanced["offense.ppa"],
        "def_ppa": advanced["defense.ppa"],
        "off_success_rate": advanced["offense.successRate"],
        "def_success_rate": advanced["defense.successRate"],
        "talent": talent["talent"].iloc[0] if not talent.empty else None,
        "recruiting_rank": f"No. {int(recruiting['rank'].iloc[0])}" if not recruiting.empty else None,
    }
    df = pd.DataFrame([row])

    gt = (
        GT(df)
        .tab_header(
            title=team_header_title(f"{team} — {year} Season Summary", _team_logo_url(team, year)),
            subtitle=f"{row['conference']}",
        )
        .fmt_number(columns=["off_ppa", "def_ppa"], decimals=2)
        .fmt_percent(columns=["off_success_rate", "def_success_rate"], decimals=1)
        .fmt_number(columns="talent", decimals=1)
        .cols_hide(columns="team")
        .cols_label(
            record=html("Record"),
            home_record=html("Home"),
            away_record=html("Away"),
            conference=html("Conference"),
            sp_plus=html("SP+"),
            srs=html("SRS"),
            fpi=html("FPI"),
            elo=html("Elo"),
            off_ppa=html("Off PPA"),
            def_ppa=html("Def PPA"),
            off_success_rate=html("Off Success%"),
            def_success_rate=html("Def Success%"),
            talent=html("Talent"),
            recruiting_rank=html("Recruiting"),
        )
        .cols_align(align="center", columns=list(df.columns.drop("team")))
        .cols_width(
            {
                "record": NARROW_COL_WIDTH,
                "home_record": NARROW_COL_WIDTH,
                "away_record": NARROW_COL_WIDTH,
                "conference": "160px",
                "sp_plus": RATING_COL_WIDTH,
                "srs": RATING_COL_WIDTH,
                "fpi": NARROW_COL_WIDTH,
                "elo": NARROW_COL_WIDTH,
                "off_ppa": "80px",
                "def_ppa": "80px",
                "off_success_rate": PERCENT_COL_WIDTH,
                "def_success_rate": PERCENT_COL_WIDTH,
                "talent": "80px",
                "recruiting_rank": "95px",
            }
        )
    )
    return base_table(gt)


def team_game_log_table(team: str, year: int) -> GT:
    """One row per game: opponent, location, result, score, and per-game efficiency."""
    schedule = get_team_schedule(team, year)
    advanced = get_team_advanced_game_stats(team, year)
    box_scores = get_team_game_stats(team, year)
    box_scores = box_scores[box_scores["team"] == team]
    teams = get_teams(year)[["school", "logo", "color"]].rename(columns={"school": "opponent"})

    is_home = schedule["homeTeam"] == team
    df = pd.DataFrame(
        {
            "id": schedule["id"],
            "week": schedule["week"],
            "date": schedule["startDate"].dt.tz_localize(None).dt.strftime("%b %-d"),
            "opponent": schedule["awayTeam"].where(is_home, schedule["homeTeam"]),
            "location": schedule["neutralSite"].map({True: "Neutral"}).fillna(is_home.map({True: "Home", False: "Away"})),
            "team_points": schedule["homePoints"].where(is_home, schedule["awayPoints"]),
            "opp_points": schedule["awayPoints"].where(is_home, schedule["homePoints"]),
        }
    ).sort_values("week")
    df["result"] = df.apply(
        lambda r: "W" if r["team_points"] > r["opp_points"] else ("L" if r["team_points"] < r["opp_points"] else "T"),
        axis=1,
    )
    df["score"] = df["team_points"].astype(int).astype(str) + "-" + df["opp_points"].astype(int).astype(str)

    df = df.merge(
        advanced[["week", "offense.ppa", "offense.successRate", "defense.ppa", "defense.successRate"]],
        on="week",
        how="left",
    )
    df = df.merge(box_scores[["game_id", "totalYards"]], left_on="id", right_on="game_id", how="left")
    df["totalYards"] = pd.to_numeric(df["totalYards"], errors="coerce")

    win_prob = get_team_pregame_win_probabilities(team, year)
    win_prob["win_prob"] = win_prob["homeWinProbability"].where(
        win_prob["homeTeam"] == team, 1 - win_prob["homeWinProbability"]
    )
    df = df.merge(win_prob[["gameId", "win_prob"]], left_on="id", right_on="gameId", how="left")

    df = df.merge(teams, on="opponent", how="left")
    df["color"] = df["color"].fillna("#333333")
    df = df.reset_index(drop=True)

    is_upset = (df["result"] == "W") & (df["win_prob"] < 0.5) | (df["result"] == "L") & (df["win_prob"] > 0.5)

    gt = (
        GT(
            df[
                [
                    "week",
                    "date",
                    "logo",
                    "opponent",
                    "location",
                    "result",
                    "score",
                    "win_prob",
                    "totalYards",
                    "offense.ppa",
                    "offense.successRate",
                    "defense.ppa",
                ]
            ],
            rowname_col="week",
        )
        .tab_header(title=team_header_title(f"{team} — {year} Game Log", _team_logo_url(team, year)))
        .fmt_image(columns="logo")
        .fmt_integer(columns="totalYards")
        .fmt_number(columns=["offense.ppa", "defense.ppa"], decimals=2)
        .fmt_percent(columns=["offense.successRate", "win_prob"], decimals=1)
        .cols_label(
            date=html("Date"),
            logo=html(""),
            opponent=html("Opponent"),
            location=html("Location"),
            result=html("Result"),
            score=html("Score"),
            win_prob=html("Win Prob"),
            totalYards=html("Total Yards"),
            **{
                "offense.ppa": html("Off PPA"),
                "offense.successRate": html("Off Success%"),
                "defense.ppa": html("Def PPA"),
            },
        )
        .cols_align(align="center", columns=["location", "result", "score", "win_prob", "totalYards"])
        .cols_width(
            {
                "date": NARROW_COL_WIDTH,
                "logo": "50px",
                "opponent": "150px",
                "location": "85px",
                "result": NARROW_COL_WIDTH,
                "score": "80px",
                "win_prob": PERCENT_COL_WIDTH,
                "totalYards": "100px",
                "offense.ppa": "80px",
                "offense.successRate": PERCENT_COL_WIDTH,
                "defense.ppa": "80px",
            }
        )
    )
    gt = base_table(gt)
    gt = style_team_text_by_color(gt, df["color"].tolist(), "opponent")
    gt = style_team_text_by_color(
        gt, [WIN_COLOR if r == "W" else LOSS_COLOR for r in df["result"]], "result"
    )
    gt = style_team_text_by_color(
        gt,
        [(WIN_COLOR if r == "W" else LOSS_COLOR) if upset else "#333333" for r, upset in zip(df["result"], is_upset)],
        "win_prob",
    )
    return gt


def write_team_dashboard(team: str, year: int, out_path: str) -> str:
    """Combine the season summary and game log into a single standalone HTML page.
    For emailing, render to PNG instead (`render_team_dashboard_png` /
    `send_gt_report`) — see the viz-style skill on why raw GT HTML must not be
    emailed directly.
    """
    html_body = combine_gt_tables(team_season_summary_table(team, year), team_game_log_table(team, year))

    import os

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(html_body)
    return out_path


def render_team_dashboard_png(team: str, year: int, out_path: str) -> str:
    """Same content as `write_team_dashboard`, rendered to a cropped PNG."""
    html_body = combine_gt_tables(team_season_summary_table(team, year), team_game_log_table(team, year))
    return str(render_html_to_png(html_body, out_path))


if __name__ == "__main__":
    path = write_team_dashboard("Notre Dame", 2025, "src/viz/output/notre_dame_2025_dashboard.html")
    print(f"wrote {path}")
    png_path = render_team_dashboard_png("Notre Dame", 2025, "src/viz/output/notre_dame_2025_dashboard.png")
    print(f"wrote {png_path}")
