from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.offsetbox import AnnotationBbox, OffsetImage

from src.data.rankings import get_final_poll
from src.data.team_profile import get_all_teams_talent
from src.data.teams import download_logo, get_teams
from src.viz.style import add_chart_source_note, apply_matplotlib_style

LOGO_ZOOM = 0.09


def _add_logo(ax: plt.Axes, x: float, y: float, image_path: Path, zoom: float = LOGO_ZOOM) -> AnnotationBbox:
    img = plt.imread(image_path)
    imagebox = OffsetImage(img, zoom=zoom)
    ab = AnnotationBbox(imagebox, (x, y), frameon=False, pad=0)
    ax.add_artist(ab)
    return ab


def talent_vs_ap_rank_scatter(year: int) -> plt.Figure:
    """Final AP Top 25 rank vs. talent rank (recruiting talent composite,
    ranked among all FBS teams) for that season — how each team's final poll
    finish compares to its roster talent. Both axes are inverted so rank 1
    (best) sits at the top right."""
    ap = get_final_poll(year, poll="AP Top 25")[["rank", "school"]].rename(
        columns={"school": "team", "rank": "ap_rank"}
    )
    talent = get_all_teams_talent(year)[["team", "talent"]].sort_values("talent", ascending=False)
    talent["talent_rank"] = range(1, len(talent) + 1)

    teams = get_teams(year)[["id", "school", "logo"]].rename(columns={"school": "team"})
    merged = ap.merge(talent, on="team", how="left").merge(teams, on="team", how="left")
    df = merged.dropna(subset=["talent_rank", "logo"]).reset_index(drop=True)
    df["logo_path"] = [download_logo(int(team_id), logo_url) for team_id, logo_url in zip(df["id"], df["logo"])]

    dropped = merged[merged["talent_rank"].isna()]["team"].tolist()

    apply_matplotlib_style()
    fig, ax = plt.subplots(figsize=(12, 10))

    max_rank = max(df["talent_rank"].max(), df["ap_rank"].max())
    ax.plot([1, max_rank], [1, max_rank], color="#bbbbbb", linewidth=1, linestyle="--", zorder=0)

    for _, row in df.iterrows():
        _add_logo(ax, row["talent_rank"], row["ap_rank"], row["logo_path"])

    x_pad = (df["talent_rank"].max() - df["talent_rank"].min()) * 0.08 + 2
    y_pad = (df["ap_rank"].max() - df["ap_rank"].min()) * 0.08 + 1
    ax.set_xlim(df["talent_rank"].max() + x_pad, df["talent_rank"].min() - x_pad)
    ax.set_ylim(df["ap_rank"].max() + y_pad, df["ap_rank"].min() - y_pad)

    ax.set_xlabel("Talent Rank (1 = most talented roster)")
    ax.set_ylabel("Final AP Poll Rank (1 = No. 1 team)")
    ax.set_title(f"Final AP Top 25 vs. Roster Talent — {year}")
    ax.spines[["top", "right"]].set_visible(False)

    if dropped:
        fig.text(
            0.01,
            0.01,
            f"Excluded (no talent composite data available): {', '.join(dropped)}",
            fontsize=8,
            color="#888888",
        )

    fig.tight_layout()
    add_chart_source_note(fig)
    return fig


if __name__ == "__main__":
    fig = talent_vs_ap_rank_scatter(2025)
    out_path = "src/viz/output/talent_vs_ap_rank_2025.png"
    import os

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.savefig(out_path, dpi=150, facecolor="white")
    print(f"wrote {out_path}")
