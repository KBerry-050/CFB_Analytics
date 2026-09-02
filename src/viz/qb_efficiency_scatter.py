from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.offsetbox import AnnotationBbox, OffsetImage

from src.data.stats import get_qb_season_efficiency
from src.data.teams import download_logo, get_teams
from src.viz.style import add_chart_source_note, apply_matplotlib_style

LOGO_ZOOM = 0.09
MIN_PLAYS = 100


def _add_logo(ax: plt.Axes, x: float, y: float, image_path: Path, zoom: float = LOGO_ZOOM) -> AnnotationBbox:
    img = plt.imread(image_path)
    imagebox = OffsetImage(img, zoom=zoom)
    ab = AnnotationBbox(imagebox, (x, y), frameon=False, pad=0)
    ax.add_artist(ab)
    return ab


def qb_efficiency_scatter(year: int, spotlight: list[tuple[str, str]]) -> plt.Figure:
    """Scatter of completion % vs. passing PPA/play for every FBS QB with at
    least `MIN_PLAYS` plays that season, with `spotlight` players (a list of
    (player_name, team) pairs) called out by team logo + name label instead
    of the plain gray dot every other QB gets.
    """
    df = get_qb_season_efficiency(year, min_plays=MIN_PLAYS)
    teams = get_teams(year)[["id", "school", "logo", "color"]].rename(columns={"school": "team"})
    df = df.merge(teams, on="team", how="left")

    is_spotlight = df.apply(lambda r: (r["player"], r["team"]) in spotlight, axis=1)
    background = df[~is_spotlight]
    highlighted = df[is_spotlight]

    apply_matplotlib_style()
    fig, ax = plt.subplots(figsize=(12, 9))

    mean_pct = df["completion_pct"].mean()
    mean_ppa = df["passing_ppa_per_play"].mean()
    ax.axvline(mean_pct, color="#bbbbbb", linewidth=1, linestyle="--", zorder=0)
    ax.axhline(mean_ppa, color="#bbbbbb", linewidth=1, linestyle="--", zorder=0)

    ax.scatter(
        background["completion_pct"],
        background["passing_ppa_per_play"],
        s=35,
        color="#b0b0b8",
        alpha=0.55,
        linewidths=0,
        zorder=1,
    )

    # Alternate label placement above/below each spotlighted point so two
    # nearby QBs' name labels don't collide with each other or the logo.
    label_offsets = [(0, 34, "bottom"), (0, -34, "top")]
    for i, (player_name, team_name) in enumerate(spotlight):
        row = highlighted[(highlighted["player"] == player_name) & (highlighted["team"] == team_name)]
        if row.empty:
            continue
        row = row.iloc[0]
        color = row["color"] or "#333333"
        if row["logo"]:
            logo_path = download_logo(int(row["id"]), row["logo"])
            _add_logo(ax, row["completion_pct"], row["passing_ppa_per_play"], logo_path)
        else:
            ax.scatter(row["completion_pct"], row["passing_ppa_per_play"], s=180, color=color, zorder=2)
        dx, dy, va = label_offsets[i % len(label_offsets)]
        ax.annotate(
            f"{row['player']} ({row['team']})",
            (row["completion_pct"], row["passing_ppa_per_play"]),
            xytext=(dx, dy),
            textcoords="offset points",
            ha="center",
            va=va,
            fontsize=12,
            fontweight="bold",
            color=color,
        )

    ax.xaxis.set_major_formatter(mticker.PercentFormatter(xmax=1, decimals=0))
    ax.set_xlabel("Completion %")
    ax.set_ylabel("Passing PPA / Play")
    ax.set_title(f"QB Passing Efficiency — {year}")
    ax.spines[["top", "right"]].set_visible(False)

    fig.text(
        0.01,
        0.01,
        f"Min. {MIN_PLAYS} plays. Dashed lines mark FBS QB averages.",
        fontsize=9,
        color="#888888",
    )

    fig.tight_layout()
    add_chart_source_note(fig)
    return fig


if __name__ == "__main__":
    import os

    fig = qb_efficiency_scatter(2025, spotlight=[("C.J. Carr", "Notre Dame"), ("Colton Joseph", "Old Dominion")])
    out_path = "src/viz/output/qb_efficiency_2025_carr_joseph.png"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.savefig(out_path, dpi=150, facecolor="white")
    print(f"wrote {out_path}")
