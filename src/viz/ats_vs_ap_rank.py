"""AP Rank vs. Margin Against the Spread — a diverging bar per ranked team
showing how far it finished from what the closing line expected.

X is the AP rank with No. 1 on the *right*, so the field reads the way a poll
does: the best teams at the strong end of the axis. That axis is a plain
ordinal ranking, though — there's no meaningful split at "top half of the
poll" the way there is at zero on the Y axis. So unlike
`transfer_portal_vs_wins.py`'s quadrant grammar (two genuinely continuous
axes, a real split on both), color here tracks only Y: each bar is the
team's margin against the closing spread (actual minus expected), shaded
green above zero and red below, deeper as the margin grows. A bar's tip
carries the team's logo, a smaller opponent-logo badge, and the final score,
so the number that matters reads at a glance without a legend to decode
quadrants.

`ats_vs_ap_rank_scatter(year, week)` puts AP rank on the x axis. Same data,
reordered by the margin itself instead: `ats_margin_ranked_chart(year, week)`
drops the x axis entirely (position no longer means AP rank, so there's
nothing meaningful to tick) and sorts bars best-to-worst, right-to-left, same
"best at the right" convention as the rank version.

Both work for any week that has both a poll and closing lines; 2026 week 1
was the pilot case.
"""

import matplotlib.colors as mcolors
import pandas as pd
from matplotlib import pyplot as plt
from matplotlib.offsetbox import AnnotationBbox, HPacker, OffsetImage, TextArea, VPacker
from matplotlib.patches import Patch

from src.data.games import get_games, get_week_betting_lines
from src.data.rankings import get_poll_rankings
from src.data.teams import download_logo, get_teams
from src.viz.style import LOSS_COLOR, WIN_COLOR, add_chart_source_note, add_logo_marker, add_turf_frame, apply_matplotlib_style

TEAM_LOGO_ZOOM = 0.09
OPPONENT_LOGO_ZOOM = 0.045
BAR_WIDTH = 0.62
# Fixed rather than padded to the data's own range — a data-driven pad left a
# lot of dead space above/below the actual bars on a week like this one where
# nothing approached +/-60. Every observed ats_margin (real weeks and the
# Michigan disputed-outcome bar alike) has stayed well inside +/-40; if a
# future week's blowout pushes past it, the logo/badge stack past that bar's
# tip is the first thing that'll visibly crowd the frame — a sign to revisit
# this rather than a silent failure.
Y_AXIS_LIMIT = 40


def build_ats_vs_rank_data(
    year: int, week: int, poll: str = "AP Top 25", season_type: str = "regular"
) -> pd.DataFrame:
    """Every team in `poll` that week, with the result of its game and how that
    result compared to the closing spread.

    Columns: rank, team, opponent, is_home, points, opponent_points, margin,
    spread, ats_margin, result, lost, logo_path, opponent_logo_path.

    `ats_margin` is the team's actual margin minus the margin the market
    expected of it. CFBD reports the spread home-relative and negative when the
    home team is favored, so the home team's expected margin is `-spread` and
    the away team's is `+spread`.
    """
    ranked = get_poll_rankings(year, week, poll=poll, season_type=season_type)
    games = get_games(year, week, season_type=season_type)
    lines = get_week_betting_lines(year, week, season_type=season_type)

    played = games[games["completed"] & games["home_points"].notna()].merge(
        lines[["id", "spread"]], on="id", how="left"
    )

    rows = []
    for entry in ranked.itertuples():
        team = entry.school
        team_games = played[(played["home_team"] == team) | (played["away_team"] == team)]
        if team_games.empty:
            continue
        # CFBD files the "week 0" slate under week 1, so a handful of teams have
        # two week-1 games. The later one is the game everyone means by "week 1".
        game = team_games.sort_values("start_date").iloc[-1]

        is_home = game["home_team"] == team
        points = int(game["home_points"] if is_home else game["away_points"])
        opponent_points = int(game["away_points"] if is_home else game["home_points"])
        margin = points - opponent_points

        spread = game["spread"]
        expected_margin = None if pd.isna(spread) else (-spread if is_home else spread)
        rows.append(
            {
                "rank": int(entry.rank),
                "team": team,
                "opponent": game["away_team"] if is_home else game["home_team"],
                "is_home": bool(is_home),
                "points": points,
                "opponent_points": opponent_points,
                "margin": margin,
                "spread": None if pd.isna(spread) else float(spread),
                "ats_margin": None if expected_margin is None else margin - expected_margin,
                "result": f"{'W' if margin > 0 else 'L'} {points}-{opponent_points}",
                "lost": margin < 0,
            }
        )

    df = pd.DataFrame(rows).dropna(subset=["ats_margin"]).reset_index(drop=True)

    teams = get_teams(year)[["id", "school", "logo"]]
    df = df.merge(teams.rename(columns={"school": "team"}), on="team", how="left").dropna(subset=["logo"])
    df = df.reset_index(drop=True)
    df["logo_path"] = _download_logos(df["id"], df["logo"])

    # Left join, not dropped on missing — an unranked or FCS opponent without
    # logo data shouldn't erase an otherwise-valid ranked team's bar, just its
    # opponent badge (handled at draw time).
    df = df.merge(
        teams.rename(columns={"school": "opponent", "id": "opponent_id", "logo": "opponent_logo"}),
        on="opponent",
        how="left",
    )
    df["opponent_logo_path"] = _download_logos(df["opponent_id"], df["opponent_logo"])
    return _spread_ranked_ties(df.sort_values("rank").reset_index(drop=True))


def _spread_ranked_ties(df: pd.DataFrame) -> pd.DataFrame:
    """The AP poll gives tied teams the same rank and skips the next slot(s)
    accordingly (e.g. two teams tied at No. 14 means nobody is No. 15) — real,
    but two bars sharing one x position would sit on top of each other. Spread
    a tie across the skipped slot(s) instead, alphabetically by team name for
    a deterministic pick, purely to give each bar its own x — this changes
    where a tied team's bar is *drawn*, not its actual poll rank."""
    df = df.sort_values(["rank", "team"]).reset_index(drop=True)
    seen: dict[int, int] = {}
    for i, rank in enumerate(df["rank"]):
        df.loc[i, "rank"] = rank + seen.get(rank, 0)
        seen[rank] = seen.get(rank, 0) + 1
    return df


def _download_logos(ids: pd.Series, urls: pd.Series) -> list:
    """`download_logo` for each (id, url) pair, or None where either is
    missing — safe to call whether or not the caller already dropped rows
    with a missing logo."""
    return [download_logo(int(i), url) if pd.notna(i) and pd.notna(url) else None for i, url in zip(ids, urls)]


def _shaded(hex_color: str, weight: float) -> tuple[float, float, float]:
    """Blend `hex_color` toward white by `weight` (0 = white, 1 = full color)
    — color tracks the Y value itself (how far from expected), not which
    side of an arbitrary quadrant split a point falls on."""
    r, g, b = mcolors.to_rgb(hex_color)
    return (1 - weight) + weight * r, (1 - weight) + weight * g, (1 - weight) + weight * b


def _bar_colors(ats_margin: pd.Series) -> list[tuple[float, float, float]]:
    vmax = ats_margin.abs().max() or 1.0
    return [_shaded(WIN_COLOR if v >= 0 else LOSS_COLOR, 0.3 + 0.7 * min(abs(v) / vmax, 1.0)) for v in ats_margin]


def _cached_image(path, image_cache: dict):
    if path not in image_cache:
        image_cache[path] = plt.imread(path)
    return image_cache[path]


def _format_spread(spread: float, is_home: bool) -> str:
    """The team's own closing line, not CFBD's home-relative one — negative
    means this team was favored, positive means underdog, "PK" for a
    pick'em."""
    team_spread = spread if is_home else -spread
    return "PK" if team_spread == 0 else f"{team_spread:+.1f}"


def _matchup_badge(ax: plt.Axes, x: float, y: float, row, offset_points: tuple[float, float], image_cache: dict) -> None:
    """A three-line badge: "vs [opponent logo]" (home) or "@ [opponent logo]"
    (away), the closing spread, then the final score — one boxed unit via
    matplotlib's offsetbox packers, rather than separate floating pieces
    competing for the same space."""
    matchup_row = [TextArea("vs" if row.is_home else "@", textprops=dict(size=9, weight="bold", color="#333333"))]
    if pd.notna(row.opponent_logo_path):
        matchup_row.append(OffsetImage(_cached_image(row.opponent_logo_path, image_cache), zoom=OPPONENT_LOGO_ZOOM))
    else:
        matchup_row.append(TextArea(row.opponent, textprops=dict(size=9, weight="bold", color="#333333")))

    spread = TextArea(_format_spread(row.spread, row.is_home), textprops=dict(size=8.5, color="#666666"))
    # `disputed_note`, when present (see ats_margin_ranked_chart), marks a row
    # as an illustrative alternate outcome rather than the real result.
    asterisk = "*" if getattr(row, "disputed_note", None) else ""
    result_prefix = "L" if row.lost else "W"
    score = TextArea(f"{result_prefix} {row.points}-{row.opponent_points}{asterisk}", textprops=dict(size=9, weight="bold", color="#333333"))
    box = VPacker(
        # Generous sep on the matchup row specifically — that's the line whose
        # logo previously sat close enough to the box edge to look clipped.
        children=[HPacker(children=matchup_row, align="center", pad=0, sep=7), spread, score],
        align="center", pad=5, sep=3,
    )
    ax.add_artist(
        AnnotationBbox(
            box, (x, y), xybox=offset_points, boxcoords="offset points", box_alignment=(0.5, 0.5),
            frameon=True, pad=0.5, bboxprops=dict(boxstyle="round,pad=0.35", fc="white", ec="#cfcfcf", lw=0.8),
        )
    )


def _annotate_bar(ax: plt.Axes, x: float, row, image_cache: dict) -> None:
    """Place the team logo, then the opponent/score matchup badge, past each
    bar's tip via fixed pixel offsets so the stack holds its shape
    regardless of bar height or axis scale.

    The offsets below were tuned by eye against one week's render (25 teams,
    CFBD's typical logo proportions) — a week with unusually wide logos or
    many adjacent tall bars could need them re-checked."""
    direction = 1 if row.ats_margin >= 0 else -1
    tip = (x, row.ats_margin)

    add_logo_marker(ax, *tip, row.logo_path, zoom=TEAM_LOGO_ZOOM, offset_points=(0, direction * 10), image_cache=image_cache)
    _matchup_badge(ax, *tip, row, offset_points=(0, direction * 65), image_cache=image_cache)


def _draw_diverging_bars(ax: plt.Axes, df: pd.DataFrame, x_values) -> None:
    """One shaded, hatched-if-lost bar per row at the given x positions, each
    topped with its team-logo + matchup badge — shared by every layout of
    this chart, since the bar/badge drawing doesn't care what the x axis
    means (AP rank, or teams reordered by performance)."""
    image_cache: dict = {}
    for x, row, color in zip(x_values, df.itertuples(), _bar_colors(df["ats_margin"])):
        ax.bar(
            x, row.ats_margin, width=BAR_WIDTH, color=color, edgecolor="white", linewidth=0.7,
            hatch="///" if row.lost else None, zorder=2,
        )
        _annotate_bar(ax, x, row, image_cache)
    ax.axhline(0.0, color="#333333", linewidth=1.3, zorder=3)


def ats_vs_ap_rank_scatter(
    year: int, week: int, poll: str = "AP Top 25", season_type: str = "regular"
) -> plt.Figure:
    """AP rank (No. 1 at the right) vs. margin against the closing spread, one
    diverging bar per ranked team."""
    df = build_ats_vs_rank_data(year, week, poll=poll, season_type=season_type)
    if df.empty:
        raise ValueError(f"No ranked teams with both a result and a closing line for {year} week {week}.")

    apply_matplotlib_style()
    # Extra-wide: with one bar per rank slot, more figure width is the only
    # thing that actually buys more room between neighboring teams' badges —
    # the data range (rank 1-25) doesn't change, so a wider figure just
    # spreads the same 25 positions over more pixels.
    fig, ax = plt.subplots(figsize=(23, 10))

    ax.set_xlim(26.5, -1.4)
    ax.set_ylim(-Y_AXIS_LIMIT, Y_AXIS_LIMIT)

    _draw_diverging_bars(ax, df, df["rank"])

    ax.set_axisbelow(True)
    ax.set_xticks([25, 20, 15, 10, 5, 1])
    ax.set_xticklabels([f"No. {t}" for t in (25, 20, 15, 10, 5, 1)])
    ax.yaxis.set_major_formatter(lambda y, _: "0" if abs(y) < 1e-9 else f"{y:+.0f}")
    # Helvetica has no arrow glyph, so the axis direction is spelled out.
    ax.set_xlabel(f"{poll} Rank Entering the Week   (No. 1 at right)", fontsize=18, fontweight="bold", labelpad=16)
    ax.set_ylabel("Margin vs. Closing Spread (Points)", fontsize=18, fontweight="bold", labelpad=16)
    ax.tick_params(axis="both", labelsize=15)
    ax.spines[["top", "right"]].set_visible(False)

    if df["lost"].any():
        ax.legend(
            handles=[Patch(facecolor="white", edgecolor="#555555", hatch="///", label="Lost outright")],
            loc="upper left", fontsize=12, frameon=True, framealpha=0.92, borderpad=0.8,
        )

    fig.suptitle(f"AP Rank vs. Performance Against the Spread - CFB {year} Week {week}", fontsize=24, fontweight="bold", y=0.97)
    fig.subplots_adjust(top=0.90, right=0.97, left=0.055, bottom=0.10)

    add_chart_source_note(fig)
    return fig


def ats_margin_ranked_chart(
    year: int, week: int, poll: str = "AP Top 25", season_type: str = "regular",
    disputed_results: list[dict] | None = None,
) -> plt.Figure:
    """The same bars as `ats_vs_ap_rank_scatter`, reordered by performance
    against the spread instead of AP rank — best margin at the right, worst
    at the left, same reading direction as the rank version's "No. 1 at
    right". There's no x axis to draw: once position means "how this team
    ranked by margin" rather than a real quantity (AP rank, a date, ...),
    tick labels would just be relisting each bar's own rank-by-margin, which
    the bar order already shows.

    `disputed_results`, if given, adds one extra, asterisked bar per entry
    for a team whose game had a well-documented alternate/disputed outcome
    (e.g. a game-ending ruling that got overturned) — each dict needs
    `team`, `points`, `opponent_points`, and `note` (a short caption
    explaining what the alternate score represents). These are illustrative
    variants of a real game (same opponent, same spread), not a second real
    result, so the real row for that team is kept as-is alongside them."""
    df = build_ats_vs_rank_data(year, week, poll=poll, season_type=season_type)
    if df.empty:
        raise ValueError(f"No ranked teams with both a result and a closing line for {year} week {week}.")
    df["disputed_note"] = None

    for d in disputed_results or []:
        base = df[df["team"] == d["team"]].iloc[0].to_dict()
        base["points"], base["opponent_points"] = d["points"], d["opponent_points"]
        base["margin"] = base["points"] - base["opponent_points"]
        base["lost"] = base["margin"] < 0
        expected_margin = -base["spread"] if base["is_home"] else base["spread"]
        base["ats_margin"] = base["margin"] - expected_margin
        base["disputed_note"] = d["note"]
        df = pd.concat([df, pd.DataFrame([base])], ignore_index=True)

    df = df.sort_values("ats_margin").reset_index(drop=True)  # worst first -> left, best last -> right

    apply_matplotlib_style()
    fig, ax = plt.subplots(figsize=(23, 10))

    ax.set_xlim(-1, len(df))
    ax.set_ylim(-Y_AXIS_LIMIT, Y_AXIS_LIMIT)

    _draw_diverging_bars(ax, df, range(len(df)))

    ax.set_axisbelow(True)
    ax.get_xaxis().set_visible(False)
    ax.spines[["top", "right", "bottom"]].set_visible(False)
    ax.yaxis.set_major_formatter(lambda y, _: "0" if abs(y) < 1e-9 else f"{y:+.0f}")
    ax.set_ylabel("Margin vs. Closing Spread (Points)", fontsize=18, fontweight="bold", labelpad=16)
    ax.tick_params(axis="y", labelsize=15)

    if df["lost"].any():
        ax.legend(
            handles=[Patch(facecolor="white", edgecolor="#555555", hatch="///", label="Lost outright")],
            loc="upper left", fontsize=12, frameon=True, framealpha=0.92, borderpad=0.8,
        )

    fig.suptitle(f"Performance Against the Spread - CFB {year} Week {week}", fontsize=24, fontweight="bold", y=0.975)
    fig.text(0.5, 0.895, "AP Top 25 Teams", fontsize=24, color="#444444", ha="center")
    fig.subplots_adjust(top=0.84, right=0.97, left=0.055, bottom=0.05)

    add_chart_source_note(fig)
    return fig


if __name__ == "__main__":
    import os

    os.makedirs("src/viz/output", exist_ok=True)

    fig = ats_vs_ap_rank_scatter(2026, 1)
    out_path = "src/viz/output/ats_vs_ap_rank_2026_wk1.png"
    with open(out_path, "wb") as f:
        f.write(add_turf_frame(fig))
    print(f"wrote {out_path}")

    fig = ats_margin_ranked_chart(
        2026, 1,
        disputed_results=[
            {
                "team": "Michigan",
                "points": 7,
                "opponent_points": 12,
                "note": "score with 0:00 on the broadcast clock, before the Big Ten's replay "
                        "review put 1 second back on and Michigan won 13-12 on the ensuing Hail Mary.",
            }
        ],
    )
    out_path = "src/viz/output/ats_margin_ranked_2026_wk1.png"
    with open(out_path, "wb") as f:
        f.write(add_turf_frame(fig))
    print(f"wrote {out_path}")
