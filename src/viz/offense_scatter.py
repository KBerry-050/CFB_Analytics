from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.offsetbox import AnnotationBbox, OffsetImage

from src.data.stats import get_offense_season_stats
from src.data.teams import download_logo, get_teams
from src.viz.style import add_chart_source_note, apply_matplotlib_style

LOGO_ZOOM = 0.05


def _add_logo(ax: plt.Axes, x: float, y: float, image_path: Path, zoom: float = LOGO_ZOOM) -> AnnotationBbox:
    img = plt.imread(image_path)
    imagebox = OffsetImage(img, zoom=zoom)
    ab = AnnotationBbox(imagebox, (x, y), frameon=False, pad=0)
    ax.add_artist(ab)
    return ab


def offense_tds_vs_yards_scatter(year: int) -> plt.Figure:
    """Scatter of total TDs vs. total yards for every FBS offense in a season,
    with each point rendered as the team's logo instead of a marker."""
    offense = get_offense_season_stats(year)
    teams = get_teams(year)[["id", "school", "logo"]].rename(columns={"school": "team"})

    df = offense.merge(teams, on="team", how="inner").dropna(subset=["logo"]).reset_index(drop=True)
    df["logo_path"] = [download_logo(int(team_id), logo_url) for team_id, logo_url in zip(df["id"], df["logo"])]

    apply_matplotlib_style()
    fig, ax = plt.subplots(figsize=(14, 10))

    mean_tds = df["total_tds"].mean()
    mean_yards = df["total_yards"].mean()
    ax.axvline(mean_yards, color="#bbbbbb", linewidth=1, linestyle="--", zorder=0)
    ax.axhline(mean_tds, color="#bbbbbb", linewidth=1, linestyle="--", zorder=0)

    for _, row in df.iterrows():
        _add_logo(ax, row["total_yards"], row["total_tds"], row["logo_path"])

    x_pad = (df["total_yards"].max() - df["total_yards"].min()) * 0.05
    y_pad = (df["total_tds"].max() - df["total_tds"].min()) * 0.05
    ax.set_xlim(df["total_yards"].min() - x_pad, df["total_yards"].max() + x_pad)
    ax.set_ylim(df["total_tds"].min() - y_pad, df["total_tds"].max() + y_pad)

    ax.set_xlabel("Total Yards")
    ax.set_ylabel("Total Touchdowns")
    ax.set_title(f"FBS Offenses — Total TDs vs. Total Yards ({year})")
    ax.spines[["top", "right"]].set_visible(False)

    fig.tight_layout()
    add_chart_source_note(fig)
    return fig


if __name__ == "__main__":
    fig = offense_tds_vs_yards_scatter(2025)
    out_path = "src/viz/output/offense_tds_vs_yards_2025.png"
    import os

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.savefig(out_path, dpi=150, facecolor="white")
    print(f"wrote {out_path}")
