"""AP poll movement between two weeks — a slope chart, one line per team,
connecting its rank in the earlier week to its rank in the later week. Logos
mark both endpoints instead of team names, per house convention (the mark is
the label). Teams that dropped out of the poll (or newly entered it) plot
against a dedicated "Unranked" row rather than being dropped from the chart —
that disappearance/appearance is itself the story for those teams.

Works for any year/week-pair/poll (`ap_poll_trend_chart(year, week_a, week_b)`);
2026 weeks 1-2 was the pilot case.
"""

import matplotlib.colors as mcolors
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from src.data.rankings import get_poll_rankings
from src.data.teams import download_logo, get_teams
from src.viz.style import LOSS_COLOR, WIN_COLOR, add_chart_source_note, add_logo_marker, apply_matplotlib_style

LOGO_ZOOM = 0.024
BAR_LOGO_ZOOM = 0.1
NEUTRAL_COLOR = "#999999"
UNRANKED_COLOR = "#bbbbbb"


def _spread_ties(ranks: pd.Series, teams: pd.Series) -> dict:
    """Plot position for each (non-null) rank, spreading a tie across the
    slot(s) the poll leaves open for it (see ats_vs_ap_rank.py's identical
    reasoning) — alphabetical by team for a deterministic pick. Returns
    {row_index: plot_position}, omitting rows with no rank to place."""
    order = sorted((i for i in ranks.index if pd.notna(ranks[i])), key=lambda i: (ranks[i], teams[i]))
    seen: dict[int, int] = {}
    plot = {}
    for i in order:
        rank = int(ranks[i])
        offset = seen.get(rank, 0)
        plot[i] = rank + offset
        seen[rank] = offset + 1
    return plot


def build_ap_poll_trend(year: int, week_a: int, week_b: int, poll: str = "AP Top 25", season_type: str = "regular"):
    """Every team ranked in `poll` in either week, with its rank (or None) in
    each, a logo, and a plotting position on a shared 1-to-unranked axis
    (ties spread across their skipped slot(s); unranked sits on its own row
    just past the poll's real bottom rank).

    Columns: team, rank_a, rank_b, logo_path, plot_a, plot_b, trend
    ("up"/"down"/"same"/"entered"/"dropped").
    """
    a = get_poll_rankings(year, week_a, poll=poll, season_type=season_type)[["rank", "school"]].rename(columns={"rank": "rank_a"})
    b = get_poll_rankings(year, week_b, poll=poll, season_type=season_type)[["rank", "school"]].rename(columns={"rank": "rank_b"})
    df = a.merge(b, on="school", how="outer").rename(columns={"school": "team"}).reset_index(drop=True)

    teams = get_teams(year)[["id", "school", "logo"]]
    df = df.merge(teams.rename(columns={"school": "team"}), on="team", how="left").dropna(subset=["logo"]).reset_index(drop=True)
    df["logo_path"] = [download_logo(int(i), url) for i, url in zip(df["id"], df["logo"])]

    unranked_row = int(max(df["rank_a"].max(skipna=True) or 0, df["rank_b"].max(skipna=True) or 0)) + 2

    plot_a = _spread_ties(df["rank_a"], df["team"])
    plot_b = _spread_ties(df["rank_b"], df["team"])
    df["plot_a"] = [plot_a.get(i, unranked_row) for i in df.index]
    df["plot_b"] = [plot_b.get(i, unranked_row) for i in df.index]

    def trend(row) -> str:
        if pd.isna(row["rank_a"]):
            return "entered"
        if pd.isna(row["rank_b"]):
            return "dropped"
        if row["rank_b"] < row["rank_a"]:
            return "up"
        if row["rank_b"] > row["rank_a"]:
            return "down"
        return "same"

    df["trend"] = df.apply(trend, axis=1)
    return df, unranked_row


def ap_poll_trend_chart(year: int, week_a: int, week_b: int, poll: str = "AP Top 25", season_type: str = "regular") -> plt.Figure:
    """Slope chart of `poll` movement from `week_a` to `week_b`: one line per
    team from its earlier rank to its later one, logos at both ends, green
    for a rise, red for a fall, gray unchanged — teams that entered or
    dropped out of the poll plot against a dedicated "Unranked" row instead
    of being omitted."""
    df, unranked_row = build_ap_poll_trend(year, week_a, week_b, poll=poll, season_type=season_type)

    trend_color = {"up": WIN_COLOR, "down": LOSS_COLOR, "same": NEUTRAL_COLOR, "entered": WIN_COLOR, "dropped": LOSS_COLOR}

    apply_matplotlib_style()
    fig, ax = plt.subplots(figsize=(12, 22))

    for row in df.itertuples():
        ax.plot(
            [0, 1], [row.plot_a, row.plot_b], color=trend_color[row.trend],
            linewidth=2, alpha=0.5 if row.trend in ("entered", "dropped") else 0.85,
            linestyle="--" if row.trend in ("entered", "dropped") else "-", zorder=2,
        )
        add_logo_marker(ax, 0, row.plot_a, row.logo_path, zoom=LOGO_ZOOM)
        add_logo_marker(ax, 1, row.plot_b, row.logo_path, zoom=LOGO_ZOOM)
        rank_a_label = "NR" if pd.isna(row.rank_a) else f"{int(row.rank_a)}"
        rank_b_label = "NR" if pd.isna(row.rank_b) else f"{int(row.rank_b)}"
        ax.annotate(rank_a_label, (0, row.plot_a), xytext=(-22, 0), textcoords="offset points", ha="right", va="center", fontsize=10, fontweight="bold")
        ax.annotate(rank_b_label, (1, row.plot_b), xytext=(22, 0), textcoords="offset points", ha="left", va="center", fontsize=10, fontweight="bold")

    ax.axhline(unranked_row - 1, color="#cccccc", linewidth=1, linestyle=":", zorder=1)
    ax.text(0.5, unranked_row, "UNRANKED", ha="center", va="center", fontsize=11, fontweight="bold", color=UNRANKED_COLOR, transform=ax.transData)

    ax.set_xlim(-0.35, 1.35)
    ax.set_ylim(unranked_row + 1, 0.3)
    ax.set_xticks([0, 1])
    ax.set_xticklabels([f"Week {week_a}", f"Week {week_b}"], fontsize=16, fontweight="bold")
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.grid(False)
    ax.tick_params(axis="x", length=0, pad=15)

    ax.legend(
        handles=[
            Line2D([], [], color=WIN_COLOR, linewidth=2, label="Moved up"),
            Line2D([], [], color=LOSS_COLOR, linewidth=2, label="Moved down"),
            Line2D([], [], color=NEUTRAL_COLOR, linewidth=2, label="Unchanged"),
            Line2D([], [], color=WIN_COLOR, linewidth=2, linestyle="--", alpha=0.6, label="Entered poll"),
            Line2D([], [], color=LOSS_COLOR, linewidth=2, linestyle="--", alpha=0.6, label="Dropped out"),
        ],
        loc="upper center", bbox_to_anchor=(0.5, 1.0), ncol=5, fontsize=11, frameon=False,
    )

    # Helvetica has no arrow glyph, so the direction is spelled out.
    fig.suptitle(f"{poll} Movement: Week {week_a} to Week {week_b}", fontsize=22, fontweight="bold", y=0.998)
    fig.text(0.5, 0.975, f"CFB {year}", fontsize=14, color="#555555", ha="center")
    fig.subplots_adjust(top=0.94, bottom=0.06, left=0.08, right=0.92)

    add_chart_source_note(fig)
    return fig


def ap_poll_dot_plot(year: int, week_a: int, week_b: int, poll: str = "AP Top 25", season_type: str = "regular") -> plt.Figure:
    """Dumbbell/dot-plot alternative to `ap_poll_trend_chart`: one *row* per
    team (not one shared column per week), an open dot at its `week_a` rank,
    a filled dot at `week_b`, and a thin connecting line — on a single shared
    numeric rank axis (1 at left) rather than two parallel categorical
    columns.

    Built to fix two real problems in the slope-chart version: team logos
    shrink to illegible smudges once ~25 of them share a narrow column (text
    names don't have that problem at any row count), and a tie has to be
    visually spread across two positions to avoid overlapping marks, which
    quietly asserts one team out-ranked the other when the poll itself has
    them level — here a tie is just two teams' dots landing on the exact
    same x, which is what a tie actually is.
    """
    df, unranked_row = build_ap_poll_trend(year, week_a, week_b, poll=poll, season_type=season_type)
    df = df.sort_values(["rank_b", "rank_a", "team"], na_position="last").reset_index(drop=True)

    trend_color = {"up": WIN_COLOR, "down": LOSS_COLOR, "same": NEUTRAL_COLOR, "entered": WIN_COLOR, "dropped": LOSS_COLOR}

    apply_matplotlib_style()
    fig, ax = plt.subplots(figsize=(11, 0.5 * len(df) + 2))

    for i, row in enumerate(df.itertuples()):
        x_a = unranked_row if pd.isna(row.rank_a) else row.rank_a
        x_b = unranked_row if pd.isna(row.rank_b) else row.rank_b
        color = trend_color[row.trend]

        if pd.notna(row.rank_a) and pd.notna(row.rank_b):
            ax.plot([x_a, x_b], [i, i], color=color, linewidth=2, alpha=0.7, zorder=2)
        else:
            ax.plot([x_a, x_b], [i, i], color=color, linewidth=2, alpha=0.4, linestyle="--", zorder=2)

        ax.scatter([x_a], [i], s=70, facecolors="white", edgecolors=color, linewidths=1.8, zorder=3)
        ax.scatter([x_b], [i], s=70, facecolors=color, edgecolors=color, linewidths=1.8, zorder=3)

    ax.set_yticks(range(len(df)))
    ax.set_yticklabels(df["team"], fontsize=11)
    ax.invert_yaxis()

    ax.axvline(unranked_row - 1, color="#cccccc", linewidth=1, linestyle=":", zorder=1)
    ax.set_xlim(0, unranked_row + 1)
    ax.set_xticks([1, 5, 10, 15, 20, 25, unranked_row])
    ax.set_xticklabels(["1", "5", "10", "15", "20", "25", "NR"], fontsize=12, fontweight="bold")
    ax.xaxis.set_ticks_position("top")
    ax.tick_params(axis="x", length=0, pad=10)
    ax.tick_params(axis="y", length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.grid(axis="x", color="#eeeeee", linewidth=0.8, zorder=0)

    ax.legend(
        handles=[
            Line2D([], [], marker="o", markersize=9, markerfacecolor="white", markeredgecolor="#555555", linestyle="none", label=f"Week {week_a}"),
            Line2D([], [], marker="o", markersize=9, markerfacecolor="#555555", markeredgecolor="#555555", linestyle="none", label=f"Week {week_b}"),
            Line2D([], [], color=WIN_COLOR, linewidth=2, label="Moved up"),
            Line2D([], [], color=LOSS_COLOR, linewidth=2, label="Moved down"),
            Line2D([], [], color=NEUTRAL_COLOR, linewidth=2, label="Unchanged"),
        ],
        loc="lower center", bbox_to_anchor=(0.5, 1.02), ncol=5, fontsize=10.5, frameon=False,
    )

    fig.suptitle(f"{poll} Movement: Week {week_a} to Week {week_b}", fontsize=20, fontweight="bold", y=0.998)
    fig.text(0.5, 0.965, f"CFB {year}", fontsize=13, color="#555555", ha="center")
    fig.subplots_adjust(top=0.89, bottom=0.06, left=0.14, right=0.97)

    add_chart_source_note(fig)
    return fig


def _shaded(hex_color: str, weight: float) -> tuple[float, float, float]:
    """Blend `hex_color` toward white by `weight` (0 = white, 1 = full color)
    — same house trick as ats_vs_ap_rank.py's identical helper, so a small
    move and a big one are visually distinguishable at a glance, not just by
    bar height."""
    r, g, b = mcolors.to_rgb(hex_color)
    return (1 - weight) + weight * r, (1 - weight) + weight * g, (1 - weight) + weight * b


def ap_poll_movement_bar_chart(year: int, week_a: int, week_b: int, poll: str = "AP Top 25", season_type: str = "regular") -> plt.Figure:
    """Diverging-bar alternative to `ap_poll_trend_chart`: one bar per team,
    height = spots gained (positive, green) or lost (negative, red) between
    `week_a` and `week_b`, sorted worst-to-best left-to-right — same grammar
    as `ats_vs_ap_rank.py`'s performance-ranked chart, trading "see the whole
    ladder at once" for "see who actually moved," which is arguably the more
    interesting question and reuses logos at a size where they're actually
    legible (a wide categorical axis, not a cramped shared column).

    A team that entered or dropped out of the poll is scored against the
    first unranked slot (`unranked_row`) rather than left out — e.g.
    entering at No. 1 would show as a very large gain. For a poll with a
    genuinely dramatic debut this could dwarf every other bar; that hasn't
    happened in this function's pilot weeks, so it's a known edge rather
    than something worked around here.
    """
    df, unranked_row = build_ap_poll_trend(year, week_a, week_b, poll=poll, season_type=season_type)
    df = df.copy()
    df["delta"] = df["rank_a"].fillna(unranked_row) - df["rank_b"].fillna(unranked_row)
    df = df.sort_values(["delta", "team"]).reset_index(drop=True)

    vmax = df["delta"].abs().max() or 1.0
    colors = [_shaded(WIN_COLOR if d >= 0 else LOSS_COLOR, 0.3 + 0.7 * min(abs(d) / vmax, 1.0)) for d in df["delta"]]

    apply_matplotlib_style()
    fig, ax = plt.subplots(figsize=(22, 10))

    for x, row, color in zip(range(len(df)), df.itertuples(), colors):
        ax.bar(x, row.delta, width=0.62, color=color, edgecolor="white", linewidth=0.7, zorder=2)
        direction = 1 if row.delta >= 0 else -1
        add_logo_marker(ax, x, row.delta, row.logo_path, zoom=BAR_LOGO_ZOOM, offset_points=(0, direction * 14))
        a_label = "NR" if pd.isna(row.rank_a) else f"{int(row.rank_a)}"
        b_label = "NR" if pd.isna(row.rank_b) else f"{int(row.rank_b)}"
        ax.annotate(
            f"{row.delta:+.0f}\n{a_label} to {b_label}",
            xy=(x, row.delta), xytext=(0, direction * 50), textcoords="offset points",
            ha="center", va="center", fontsize=8.5, fontweight="bold", color="#333333",
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#cfcfcf", lw=0.8),
        )
    ax.axhline(0, color="#333333", linewidth=1.3, zorder=3)

    ax.set_xlim(-1, len(df))
    y_pad = vmax * 0.55
    ax.set_ylim(-vmax - y_pad, vmax + y_pad)
    ax.get_xaxis().set_visible(False)
    ax.spines[["top", "right", "bottom"]].set_visible(False)
    ax.set_ylabel("Spots Gained / Lost", fontsize=18, fontweight="bold", labelpad=16)
    ax.tick_params(axis="y", labelsize=15)
    ax.grid(axis="y", color="#eeeeee", linewidth=0.8, zorder=0)

    fig.suptitle(f"{poll} Movement: Week {week_a} to Week {week_b}", fontsize=24, fontweight="bold", y=0.975)
    fig.text(0.5, 0.925, f"CFB {year} — sorted by spots gained/lost", fontsize=15, color="#555555", ha="center")
    fig.subplots_adjust(top=0.86, bottom=0.05, left=0.055, right=0.97)

    add_chart_source_note(fig)
    return fig


if __name__ == "__main__":
    fig = ap_poll_trend_chart(2026, 1, 2)
    fig.savefig("src/viz/output/ap_poll_trend_2026_wk1_wk2.png", dpi=150, facecolor="white")
    print("wrote src/viz/output/ap_poll_trend_2026_wk1_wk2.png")

    fig = ap_poll_dot_plot(2026, 1, 2)
    fig.savefig("src/viz/output/ap_poll_dot_plot_2026_wk1_wk2.png", dpi=150, facecolor="white")
    print("wrote src/viz/output/ap_poll_dot_plot_2026_wk1_wk2.png")

    fig = ap_poll_movement_bar_chart(2026, 1, 2)
    fig.savefig("src/viz/output/ap_poll_movement_bar_2026_wk1_wk2.png", dpi=150, facecolor="white")
    print("wrote src/viz/output/ap_poll_movement_bar_2026_wk1_wk2.png")
