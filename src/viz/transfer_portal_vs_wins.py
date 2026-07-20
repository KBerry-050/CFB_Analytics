from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.offsetbox import AnnotationBbox, OffsetImage
from matplotlib.patches import Rectangle

from src.data.team_profile import get_all_teams_records, get_all_transfers
from src.data.teams import download_logo, get_teams
from src.viz.style import add_chart_source_note, apply_matplotlib_style

LOGO_ZOOM = 0.05
INDIANA_HIGHLIGHT_COLOR = "#d4af37"

QUADRANT_COLORS = {
    (False, True): "#e8f5e9",
    (False, False): "#fff8e1",
    (True, True): "#e3f2fd",
    (True, False): "#ffebee",
}

# Per-metric chart config: which column to plot, its axis label/tick format,
# how to split the quadrants on that axis, and the good/bad quadrant wording.
Y_METRICS = {
    "win_pct": {
        "column": "win_pct",
        "axis_label": "Win Percentage",
        "title_label": "Win Percentage",
        "formatter": lambda y, _: f"{y:.0%}",
        "split": "median",
        "good_term": "GOOD TEAM",
        "bad_term": "BAD TEAM",
    },
    "wins_above_expected": {
        "column": "wins_above_expected",
        "axis_label": "Wins Above Expected",
        "title_label": "Wins Above Expected",
        "formatter": lambda y, _: f"{y:+.1f}",
        "split": "zero",
        "good_term": "OVERPERFORMED",
        "bad_term": "UNDERPERFORMED",
    },
}


def _add_logo(ax: plt.Axes, x: float, y: float, image_path: Path, zoom: float = LOGO_ZOOM) -> AnnotationBbox:
    img = plt.imread(image_path)
    imagebox = OffsetImage(img, zoom=zoom)
    ab = AnnotationBbox(imagebox, (x, y), frameon=False, pad=0)
    ax.add_artist(ab)
    return ab


def build_transfer_portal_vs_wins_data(year: int, conference: str | None = None) -> pd.DataFrame:
    """Total transfer-portal movement (departures + arrivals) vs. win
    percentage / wins above expected for every FBS team in a season,
    optionally restricted to one conference (exact CFBD name, e.g.
    "Big Ten"). Columns: team, conference, departures, arrivals,
    total_transfers, win_pct, wins_above_expected, logo_path."""
    records = get_all_teams_records(year)
    fbs = records[records["classification"] == "fbs"].copy()
    if conference is not None:
        fbs = fbs[fbs["conference"] == conference]
    fbs["win_pct"] = fbs["total.wins"] / fbs["total.games"]
    fbs["wins_above_expected"] = fbs["total.wins"] - fbs["expectedWins"]
    fbs = fbs[["team", "conference", "total.wins", "total.games", "win_pct", "wins_above_expected"]]

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


def _draw_quadrants(ax: plt.Axes, x_split: float, y_split: float, good_term: str, bad_term: str) -> None:
    """Shade the four turnover/performance quadrants and label each in its
    outer corner — behind gridlines and data (low zorder)."""
    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()

    labels = {
        (False, True): f"STABLE ROSTER, {good_term}",
        (False, False): f"STABLE ROSTER, {bad_term}",
        (True, True): f"NEW ROSTER, {good_term}",
        (True, False): f"NEW ROSTER, {bad_term}",
    }
    bounds = {
        (False, False): (x_min, y_min, x_split, y_split),  # stable, bad
        (False, True): (x_min, y_split, x_split, y_max),  # stable, good
        (True, False): (x_split, y_min, x_max, y_split),  # new, bad
        (True, True): (x_split, y_split, x_max, y_max),  # new, good
    }
    label_pos = {
        (False, True): (0.015, 0.97, "left", "top"),
        (False, False): (0.015, 0.03, "left", "bottom"),
        (True, True): (0.985, 0.97, "right", "top"),
        (True, False): (0.985, 0.03, "right", "bottom"),
    }
    for key, (x0, y0, x1, y1) in bounds.items():
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor=QUADRANT_COLORS[key], edgecolor="none", zorder=-10))
        lx, ly, ha, va = label_pos[key]
        ax.text(
            lx, ly, labels[key], transform=ax.transAxes, fontsize=16, fontweight="bold",
            color="#666666", ha=ha, va=va, alpha=0.85,
        )

    ax.axvline(x_split, color="#999999", linewidth=1, linestyle="--", zorder=-5)
    ax.axhline(y_split, color="#999999", linewidth=1, linestyle="--", zorder=-5)


def _highlight_indiana(ax: plt.Axes, df: pd.DataFrame, y_col: str) -> None:
    """A 5th, standalone category: Indiana isn't grouped into a quadrant at
    all — an undefeated season is its own story regardless of roster churn."""
    rows = df[df["team"] == "Indiana"]
    if rows.empty:
        return
    indiana = rows.iloc[0]
    x, y = indiana["total_transfers"], indiana[y_col]
    ax.scatter(
        [x], [y], s=2000, facecolors="none", edgecolors=INDIANA_HIGHLIGHT_COLOR, linewidths=3, zorder=5,
    )
    y_offset = (ax.get_ylim()[1] - ax.get_ylim()[0]) * 0.045
    ax.annotate(
        "Curt Cignetti",
        xy=(x, y),
        xytext=(x, y + y_offset),
        fontsize=12,
        fontweight="bold",
        color="#8a6d00",
        ha="center",
        va="bottom",
    )


def transfer_portal_vs_wins_scatter(year: int, conference: str | None = None, y_metric: str = "win_pct") -> plt.Figure:
    """Roster turnover (total transfer-portal moves) vs. `y_metric`
    ("win_pct" or "wins_above_expected"), grouped into four quadrants — plus
    a standalone callout for Indiana, whose undefeated season doesn't fit
    neatly into any cluster. Pass `conference` (exact CFBD name, e.g.
    "Big Ten") to restrict to one conference; quadrant splits are recomputed
    on that subset so teams are grouped relative to their own conference,
    not the whole FBS field."""
    if y_metric not in Y_METRICS:
        raise ValueError(f"y_metric must be one of {list(Y_METRICS)}, got {y_metric!r}")
    metric = Y_METRICS[y_metric]
    y_col = metric["column"]

    df = build_transfer_portal_vs_wins_data(year, conference=conference)
    if df.empty:
        raise ValueError(f"No FBS teams found for conference={conference!r} in {year} — check the exact CFBD name.")
    x_split = df["total_transfers"].median()
    y_split = 0.0 if metric["split"] == "zero" else df[y_col].median()

    apply_matplotlib_style()
    fig, ax = plt.subplots(figsize=(16, 9))

    x_pad = (df["total_transfers"].max() - df["total_transfers"].min()) * 0.05
    y_pad = (df[y_col].max() - df[y_col].min()) * 0.08
    ax.set_xlim(df["total_transfers"].min() - x_pad, df["total_transfers"].max() + x_pad)
    ax.set_ylim(df[y_col].min() - y_pad, df[y_col].max() + y_pad)

    _draw_quadrants(ax, x_split, y_split, metric["good_term"], metric["bad_term"])

    # Zoom tuned for the full ~136-team FBS field; smaller filtered views (e.g.
    # one conference) get bigger logos so they stay legible.
    logo_zoom = LOGO_ZOOM if len(df) > 40 else LOGO_ZOOM * 1.8
    for _, row in df.iterrows():
        _add_logo(ax, row["total_transfers"], row[y_col], row["logo_path"], zoom=logo_zoom)
    _highlight_indiana(ax, df, y_col)

    ax.set_axisbelow(True)
    ax.yaxis.set_major_formatter(metric["formatter"])
    ax.set_xlabel("Total Transfer Portal Moves (Departures + Arrivals)", fontsize=18)
    ax.set_ylabel(metric["axis_label"], fontsize=18)
    ax.tick_params(axis="both", labelsize=15)
    ax.spines[["top", "right"]].set_visible(False)

    title_scope = conference if conference else "CFB"
    fig.suptitle(
        f"Roster Continuity vs. {metric['title_label']} - {title_scope} {year}", fontsize=24, fontweight="bold", y=0.98
    )
    fig.subplots_adjust(top=0.90, right=0.97, left=0.07, bottom=0.10)

    add_chart_source_note(fig)
    return fig


if __name__ == "__main__":
    fig = transfer_portal_vs_wins_scatter(2025)
    out_path = "src/viz/output/transfer_portal_vs_wins_2025.png"
    import os

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.savefig(out_path, dpi=150, facecolor="white")
    print(f"wrote {out_path}")
