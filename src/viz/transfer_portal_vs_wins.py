from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.offsetbox import AnnotationBbox, OffsetImage

from src.data.team_profile import get_all_teams_records, get_all_transfers
from src.data.teams import download_logo, get_teams
from src.viz.style import add_chart_source_note, apply_matplotlib_style

LOGO_ZOOM = 0.05


def _add_logo(ax: plt.Axes, x: float, y: float, image_path: Path, zoom: float = LOGO_ZOOM) -> AnnotationBbox:
    img = plt.imread(image_path)
    imagebox = OffsetImage(img, zoom=zoom)
    ab = AnnotationBbox(imagebox, (x, y), frameon=False, pad=0)
    ax.add_artist(ab)
    return ab


def build_transfer_portal_vs_wins_data(year: int) -> pd.DataFrame:
    """Total transfer-portal movement (departures + arrivals) vs. win
    percentage for every FBS team in a season. Columns: team, departures,
    arrivals, total_transfers, win_pct, logo_path."""
    records = get_all_teams_records(year)
    fbs = records[records["classification"] == "fbs"].copy()
    fbs["win_pct"] = fbs["total.wins"] / fbs["total.games"]
    fbs = fbs[["team", "total.wins", "total.games", "win_pct"]]

    transfers = get_all_transfers(year)
    departures = transfers.groupby("origin").size().rename("departures")
    arrivals = transfers.groupby("destination").size().rename("arrivals")
    churn = pd.concat([departures, arrivals], axis=1).fillna(0).reset_index().rename(columns={"index": "team"})
    churn["total_transfers"] = churn["departures"] + churn["arrivals"]

    df = fbs.merge(churn, on="team", how="left")
    df[["departures", "arrivals", "total_transfers"]] = df[["departures", "arrivals", "total_transfers"]].fillna(0)

    teams = get_teams(year)[["id", "school", "logo"]].rename(columns={"school": "team"})
    df = df.merge(teams, on="team", how="left").dropna(subset=["logo"]).reset_index(drop=True)
    df["logo_path"] = [download_logo(int(team_id), logo_url) for team_id, logo_url in zip(df["id"], df["logo"])]
    return df


def transfer_portal_vs_wins_scatter(year: int) -> plt.Figure:
    """Roster turnover (total transfer-portal moves) vs. win percentage —
    tests whether heavier portal reliance correlates with on-field success."""
    df = build_transfer_portal_vs_wins_data(year)
    corr = df["total_transfers"].corr(df["win_pct"])

    apply_matplotlib_style()
    fig, ax = plt.subplots(figsize=(14, 10))

    slope, intercept = np.polyfit(df["total_transfers"], df["win_pct"], 1)
    x_line = np.array([df["total_transfers"].min(), df["total_transfers"].max()])
    ax.plot(x_line, slope * x_line + intercept, color="#bbbbbb", linewidth=1.5, linestyle="--", zorder=0)

    for _, row in df.iterrows():
        _add_logo(ax, row["total_transfers"], row["win_pct"], row["logo_path"])

    x_pad = (df["total_transfers"].max() - df["total_transfers"].min()) * 0.05
    y_pad = (df["win_pct"].max() - df["win_pct"].min()) * 0.06
    ax.set_xlim(df["total_transfers"].min() - x_pad, df["total_transfers"].max() + x_pad)
    ax.set_ylim(df["win_pct"].min() - y_pad, df["win_pct"].max() + y_pad)
    ax.yaxis.set_major_formatter(lambda y, _: f"{y:.0%}")

    ax.set_xlabel("Total Transfer Portal Moves (Departures + Arrivals)")
    ax.set_ylabel("Win Percentage")
    ax.set_title(f"Roster Turnover vs. Win Percentage — {year}")
    ax.spines[["top", "right"]].set_visible(False)

    direction = "negative" if corr < 0 else "positive"
    ax.text(
        0.02,
        0.02,
        f"r = {corr:.2f} (weak {direction} correlation)",
        transform=ax.transAxes,
        fontsize=12,
        color="#555555",
    )

    fig.tight_layout()
    add_chart_source_note(fig)
    return fig


if __name__ == "__main__":
    fig = transfer_portal_vs_wins_scatter(2025)
    out_path = "src/viz/output/transfer_portal_vs_wins_2025.png"
    import os

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.savefig(out_path, dpi=150, facecolor="white")
    print(f"wrote {out_path}")
