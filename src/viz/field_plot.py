"""A football-field diagram (yard lines, end zones, mowed-stripe turf) with
one horizontal line per offensive play, running from its starting to ending
field position, a player headshot at the play's endpoint.

The turf here is the same two greens as `style.py`'s `TURF_DARK`/
`TURF_LIGHT` (the webapp shell's field theme, and `add_turf_frame`'s
backdrop) — reused as the actual mowed-stripe pattern of a real field
diagram instead of decorative chrome around a chart, since that's what this
visual is asking to be: literally a field, not a chart sitting on one.

Pairs with `src/data/postgame.py`'s `get_offensive_plays_with_field_position()`.
Built for `src/app/game_field_viewer.py`, but usable standalone.
"""

import matplotlib.patches as patches
import matplotlib.pyplot as plt
import pandas as pd

from src.viz.style import LOSS_COLOR, TURF_DARK, TURF_LIGHT, WIN_COLOR, add_logo_marker, apply_matplotlib_style

END_ZONE_DEPTH = 10  # yards, each side — standard college field
FIELD_STRIPE_YARDS = 5  # a mowed stripe's width, matching the real 5-yard bands
PLAYER_PHOTO_ZOOM = 0.05


def draw_field(ax: plt.Axes) -> None:
    """The static field background: alternating turf stripes, yard lines
    every 10 with numbers, hash marks, and shaded end zones. Draws into
    `ax`'s full x-range of -END_ZONE_DEPTH to 100+END_ZONE_DEPTH — set that
    xlim (and whatever ylim the caller needs for its play lanes) before or
    after calling this; zorder keeps it behind anything drawn on top."""
    field_left, field_right = -END_ZONE_DEPTH, 100 + END_ZONE_DEPTH
    y0, y1 = ax.get_ylim()

    for x in range(0, 100, FIELD_STRIPE_YARDS):
        color = TURF_LIGHT if (x // FIELD_STRIPE_YARDS) % 2 else TURF_DARK
        ax.add_patch(patches.Rectangle((x, y0), FIELD_STRIPE_YARDS, y1 - y0, facecolor=color, edgecolor="none", zorder=-100))

    end_zone_color = "#0c2016"  # solid, deliberately darker than either turf stripe so it reads as a distinct zone, not just another stripe
    for x0 in (field_left, 100):
        ax.add_patch(patches.Rectangle((x0, y0), END_ZONE_DEPTH, y1 - y0, facecolor=end_zone_color, edgecolor="none", zorder=-99))
        ax.text(
            x0 + END_ZONE_DEPTH / 2, (y0 + y1) / 2, "END ZONE", color="white", fontsize=13, fontweight="bold",
            ha="center", va="center", rotation=90, alpha=0.55, zorder=-89,
        )

    for x in range(0, 101, 10):
        ax.axvline(x, color="white", linewidth=1.4 if x in (0, 100) else 0.9, zorder=-90)
    for x in range(0, 101, 5):
        for y in (y0 + (y1 - y0) * 0.06, y1 - (y1 - y0) * 0.06):
            ax.plot([x, x], [y - (y1 - y0) * 0.01, y + (y1 - y0) * 0.01], color="white", linewidth=1, zorder=-90)

    for x in range(10, 100, 10):
        yard_number = x if x <= 50 else 100 - x
        ax.text(x, y1 - (y1 - y0) * 0.03, str(yard_number), color="white", fontsize=13, fontweight="bold", ha="center", va="top", zorder=-89)
        ax.text(x, y0 + (y1 - y0) * 0.03, str(yard_number), color="white", fontsize=13, fontweight="bold", ha="center", va="bottom", zorder=-89)

    ax.set_xlim(field_left, field_right)
    ax.set_xticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.grid(False)


def plot_offensive_plays(ax: plt.Axes, plays: pd.DataFrame, roster_lookup: dict[int, dict], image_cache: dict | None = None) -> None:
    """One horizontal line per row of `plays` (see
    `get_offensive_plays_with_field_position`'s columns), stacked in the
    given row order — green for a positive gain, red for a loss, thicker for
    an explosive play — with the ball-carrier's headshot (if `roster_lookup`
    has one for their jersey number) at the play's endpoint. Caller is
    responsible for `draw_field`'s ylim covering `range(len(plays))` with a
    little padding.

    Photos are decoded once per distinct jersey number, not once per play —
    a running back with a dozen carries would otherwise have their headshot
    re-decoded from disk on every single one. Pass in `image_cache` from the
    caller (e.g. an `st.cache_resource`-backed dict) to persist decoded
    photos across repeated calls too — a Streamlit app rebuilds the figure on
    every filter change, and a fresh per-call dict would otherwise re-decode
    every headshot from disk on every rerun."""
    if image_cache is None:
        image_cache = {}
    for lane, row in enumerate(plays.itertuples()):
        color = WIN_COLOR if row.yards_gained >= 0 else LOSS_COLOR
        ax.plot(
            [row.start_yard, row.end_yard], [lane, lane],
            color=color, linewidth=4 if row.is_explosive else 2, alpha=0.95, zorder=10,
            solid_capstyle="round",
        )
        ax.scatter([row.start_yard], [lane], s=22, color=color, zorder=11)
        ax.scatter([row.end_yard], [lane], s=45, color=color, zorder=11, marker=">" if row.end_yard >= row.start_yard else "<")

        info = roster_lookup.get(row.jersey_number, {})
        photo_path = info.get("photo_path")
        if photo_path:
            add_logo_marker(ax, row.end_yard, lane, photo_path, zoom=PLAYER_PHOTO_ZOOM, image_cache=image_cache)
        else:
            ax.annotate(f"#{row.jersey_number}", (row.end_yard, lane), xytext=(0, 10), textcoords="offset points", ha="center", fontsize=8, fontweight="bold")


def build_field_figure(
    plays: pd.DataFrame, roster_lookup: dict[int, dict], title: str, subtitle: str = "", image_cache: dict | None = None
) -> plt.Figure:
    """A complete field figure for `plays` (already filtered by the caller —
    e.g. `src/app/game_field_viewer.py`'s quarter/player filters): the field
    background sized to fit every row, one lane per play, oldest at top.

    `image_cache` is forwarded to `plot_offensive_plays` — pass a
    long-lived dict (e.g. from `st.cache_resource`) so a caller that rebuilds
    this figure repeatedly (a Streamlit filter change) doesn't re-decode
    every player photo from disk each time."""
    apply_matplotlib_style()
    n = max(len(plays), 1)
    fig_height = max(4, 0.5 * n + 2)
    fig, ax = plt.subplots(figsize=(16, fig_height))

    ax.set_ylim(n - 0.5, -1.5)  # first play at top, extra headroom for headshots above lane 0
    draw_field(ax)
    if not plays.empty:
        plot_offensive_plays(ax, plays.reset_index(drop=True), roster_lookup, image_cache=image_cache)
    else:
        ax.text(45, n / 2, "No plays match the current filters", ha="center", va="center", fontsize=16, color="white", fontweight="bold", zorder=20)

    # Positioned by absolute inches from the top rather than a fixed figure
    # fraction, since fig_height itself varies a lot with play count (a
    # fractional offset that looks right at 4 plays would crowd the title at
    # 50) — see ap_poll_trend.py's dot plot for the same class of bug.
    #
    # Both title and subtitle are anchored va="top" so their y values are
    # directly stackable top-offsets rather than one being a baseline (fig.text's
    # default) and the other a box top (suptitle's default) — mixing those two
    # conventions is what caused the two lines to overlap regardless of
    # fig_height in an earlier version of this function.
    title_top_in = 0.3
    title_height_in = 0.34  # ~20pt bold, line height
    subtitle_height_in = 0.24  # ~13pt, line height
    gap_in = 0.12

    subtitle_top_in = title_top_in + title_height_in + gap_in
    header_in = subtitle_top_in + (subtitle_height_in + gap_in if subtitle else 0)

    fig.suptitle(title, fontsize=20, fontweight="bold", y=1 - title_top_in / fig_height, va="top")
    if subtitle:
        fig.text(0.5, 1 - subtitle_top_in / fig_height, subtitle, fontsize=13, color="#555555", ha="center", va="top")
    fig.subplots_adjust(top=1 - header_in / fig_height, bottom=0.02, left=0.02, right=0.98)
    return fig
