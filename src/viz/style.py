import io

import matplotlib.pyplot as plt
from great_tables import GT, html, loc, style
from PIL import Image, ImageDraw

TABLE_FONT = "Helvetica"
HEADER_BG = "#1a1a2e"
HEADER_TEXT = "#ffffff"
ROW_STRIPE = "#f5f5f7"
SOURCE_NOTE = html(
    '<div style="width:100%; text-align:center;">'
    "Source: collegefootballdata.com&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Graphic: kb_analytix"
    "</div>"
)
HEADING_TITLE_SIZE = "24px"
HEADING_SUBTITLE_SIZE = "16px"
SOURCE_NOTE_SIZE = "15px"

# Minimum `cols_width()` values for common column shapes, at this house font/weight.
# Anything narrower than these wraps its header onto two lines.
NARROW_COL_WIDTH = "70px"  # short counting stats, W/L, single scores ("10-2", "W")
PERCENT_COL_WIDTH = "130px"  # "Off Success%" header + "46.3%" body
RATING_COL_WIDTH = "115px"  # "value (No. rank)" cells, e.g. "24.4 (No. 1)"

# Mathtext (`$\mathbf{...}$`) bolds just the label word on each line, "Graphic"
# stacked above "Source" — the fontset rcParams below keep both weights in
# Helvetica rather than mathtext's own default serif-ish font.
CHART_SOURCE_NOTE = r"$\mathbf{Graphic}$: kb_analytix" "\n" r"$\mathbf{Source}$: collegefootballdata.com"
CHART_SOURCE_NOTE_SIZE = 20

# Shared positive/negative indicator colors (upset highlighting, stat deltas, etc.)
WIN_COLOR = "#1b7a3d"
LOSS_COLOR = "#b3261e"

# The webapp shell's own turf colors (`_inject_field_theme` in
# src/app/webapp.py) — reused at full strength here since this frame sits
# *around* a finished chart, not behind its data, so there's no legibility
# tradeoff to mute for.
TURF_DARK = "#1c5c34"
TURF_LIGHT = "#21683c"
TURF_STRIPE_PERIOD = 110  # px, matches the webapp CSS's gradient period
FIELD_GOLD = "#d4af37"  # the webapp's scoreboard-border accent

MPL_RCPARAMS = {
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica", "Arial"],
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.edgecolor": "#333333",
    "axes.grid": True,
    "grid.color": "#dddddd",
    "grid.linewidth": 0.5,
    "figure.dpi": 150,
    "font.size": 11,
    "axes.labelsize": 14,
    "axes.titlesize": 18,
    "axes.titleweight": "bold",
    "xtick.labelsize": 12,
    "ytick.labelsize": 12,
    # Keep mathtext (used to bold part of a label, e.g. add_chart_source_note)
    # in the house sans-serif rather than its own default font.
    "mathtext.fontset": "custom",
    "mathtext.rm": "Helvetica",
    "mathtext.bf": "Helvetica:bold",
}


def apply_matplotlib_style() -> None:
    plt.rcParams.update(MPL_RCPARAMS)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


def add_turf_frame(fig: plt.Figure, dpi: int = 150, margin_ratio: float = 0.055, border_width: int = 8) -> bytes:
    """Composite a rendered chart onto a bigger turf-patterned canvas, like a
    white card laid on the field — the same mowed-stripe-plus-yard-line
    pattern as the webapp shell's page background behind its white GT
    tables (`_inject_field_theme` in src/app/webapp.py), applied here to a
    standalone chart image instead of an app page. A gold border frames the
    card itself, echoing that shell's scoreboard styling.

    Compositing happens with Pillow, not matplotlib, since the chart has
    already been fully drawn by this point — so this returns PNG bytes
    (write straight to a file, or pass as an email's inline image) rather
    than a Figure or an Axes to keep drawing on.
    """
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor="white")
    buf.seek(0)
    card = Image.open(buf).convert("RGB")

    margin = int(round(max(card.size) * margin_ratio))
    canvas_size = (card.width + 2 * margin, card.height + 2 * margin)

    dark, light = _hex_to_rgb(TURF_DARK), _hex_to_rgb(TURF_LIGHT)
    yard_line_color = tuple(round(0.9 * c + 0.1 * 255) for c in light)  # light stripe + ~10% white

    canvas = Image.new("RGB", canvas_size, dark)
    draw = ImageDraw.Draw(canvas)
    for x in range(0, canvas_size[0], TURF_STRIPE_PERIOD):
        if (x // TURF_STRIPE_PERIOD) % 2:
            draw.rectangle([x, 0, x + TURF_STRIPE_PERIOD, canvas_size[1]], fill=light)
    for y in range(0, canvas_size[1], TURF_STRIPE_PERIOD):
        draw.line([(0, y), (canvas_size[0], y)], fill=yard_line_color, width=2)

    border_box = [
        margin - border_width, margin - border_width,
        margin + card.width + border_width - 1, margin + card.height + border_width - 1,
    ]
    draw.rectangle(border_box, outline=_hex_to_rgb(FIELD_GOLD), width=border_width)
    canvas.paste(card, (margin, margin))

    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


def add_chart_source_note(fig: plt.Figure) -> None:
    """Standard source/attribution footnote for every matplotlib chart —
    the chart equivalent of `SOURCE_NOTE` on GT tables. Placed bottom-right so
    it never collides with a chart-specific caveat placed bottom-left (e.g.
    "excluded" notes)."""
    # ha="center" so the shorter "Graphic" line centers over the longer
    # "Source" line instead of both ragged-left off a shared right edge.
    # Centering shifts the block's actual right edge left of wherever it's
    # anchored (by half the block's own width), and that width depends on
    # font/rendering — rather than guess an anchor x that happens to work for
    # today's text, place it once, measure its real extent via the renderer,
    # then re-anchor so the right edge lands exactly at `right_edge`.
    right_edge = 0.97
    text_obj = fig.text(right_edge, 0.01, CHART_SOURCE_NOTE, fontsize=CHART_SOURCE_NOTE_SIZE, color="#333333", ha="center", va="bottom")
    fig.canvas.draw()
    bbox = text_obj.get_window_extent(renderer=fig.canvas.get_renderer()).transformed(fig.transFigure.inverted())
    text_obj.set_x(2 * right_edge - bbox.x1)


def add_logo_marker(
    ax, x: float, y: float, image_path, zoom: float = 0.05,
    offset_points: tuple[float, float] | None = None, image_cache: dict | None = None,
):
    """Plot a team's logo as the data point at (x, y).

    The house alternative to a colored scatter marker: on a team-level chart
    the mark *is* the label, so the reader doesn't have to cross-reference a
    legend. `zoom` is tuned to how many teams share the axes — a full ~136-team
    FBS field needs ~0.05, a 25-team field can go 2-3x larger.

    `offset_points`, when given, anchors the logo to (x, y) but draws it
    `offset_points` pixels away instead of centered on it — for stacking more
    than one marker (e.g. a team logo plus a smaller opponent badge) off the
    same data point without the offset distance changing as the axis scale or
    data range does.

    `image_cache`, when given, is a plain dict this function reads/writes
    itself (keyed by `image_path`) so the same logo file isn't re-decoded
    from disk every time it appears — pass one shared dict across all calls
    for one chart when a team can show up more than once (e.g. as both a
    ranked team and someone else's opponent).
    """
    import matplotlib.pyplot as plt
    from matplotlib.offsetbox import AnnotationBbox, OffsetImage

    if image_cache is None:
        image = plt.imread(image_path)
    elif image_path not in image_cache:
        image_cache[image_path] = plt.imread(image_path)
        image = image_cache[image_path]
    else:
        image = image_cache[image_path]

    imagebox = OffsetImage(image, zoom=zoom)
    kwargs = {"frameon": False, "pad": 0}
    if offset_points is not None:
        kwargs.update(xybox=offset_points, boxcoords="offset points", box_alignment=(0.5, 0.5))
    annotation = AnnotationBbox(imagebox, (x, y), **kwargs)
    ax.add_artist(annotation)
    return annotation


def base_table(gt: GT) -> GT:
    """Common house style applied to every table before column-specific formatting."""
    return (
        gt.opt_table_font(font=TABLE_FONT)
        .opt_row_striping()
        .tab_style(
            style=[style.fill(color=HEADER_BG), style.text(color=HEADER_TEXT, weight="bold")],
            locations=loc.column_labels(),
        )
        .tab_options(
            table_border_top_style="hidden",
            table_border_bottom_style="hidden",
            row_striping_background_color=ROW_STRIPE,
            heading_title_font_size=HEADING_TITLE_SIZE,
            heading_title_font_weight="bold",
            heading_subtitle_font_size=HEADING_SUBTITLE_SIZE,
            source_notes_font_size=SOURCE_NOTE_SIZE,
            source_notes_padding=12,
        )
        .tab_source_note(source_note=SOURCE_NOTE)
    )


def team_header_title(title_text: str, logo_url: str | None):
    """A `tab_header(title=...)` value with the team's logo inline before the
    title text. Use for any team-specific table so branding is consistent
    across the report, not just the first table on a page."""
    logo_html = f'<img src="{logo_url}" style="height:32px; vertical-align:middle; margin-right:10px;">' if logo_url else ""
    return html(f"{logo_html}{title_text}")


def dual_logo_header(title_text: str, left_logo_url: str | None, right_logo_html: str | None):
    """A `tab_header(title=...)` value with one logo pinned top-left and a
    second top-right, title centered between them. Use for any comparison
    table branded by two marks (e.g. a team's primary logo + an alternate
    mark) rather than the single-logo `team_header_title`.

    Bold is set inline (not left to `heading_title_font_weight`) — custom
    HTML dropped into `title=` sits inside GT's title cell but doesn't
    reliably inherit that table option's font-weight.
    """
    left = f'<img src="{left_logo_url}" style="height:40px;">' if left_logo_url else "<span></span>"
    right = right_logo_html or "<span></span>"
    return html(
        f'<div style="display:flex; align-items:center; justify-content:space-between; width:100%;">'
        f'{left}<span style="font-weight:bold;">{title_text}</span>{right}</div>'
    )


def style_team_text_by_color(gt: GT, colors: list[str], team_col: str) -> GT:
    """Color each row's team-name cell with that team's own brand color.

    `colors` must be in the same order as the table's rows.
    """
    for i, color in enumerate(colors):
        gt = gt.tab_style(
            style=style.text(color=color, weight="bold"),
            locations=loc.body(columns=team_col, rows=[i]),
        )
    return gt
