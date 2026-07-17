import matplotlib.pyplot as plt
from great_tables import GT, html, loc, style

TABLE_FONT = "Helvetica"
HEADER_BG = "#1a1a2e"
HEADER_TEXT = "#ffffff"
ROW_STRIPE = "#f5f5f7"
SOURCE_NOTE = html("Source: collegefootballdata.com&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Graphic: kb_analytix")
HEADING_TITLE_SIZE = "24px"
SOURCE_NOTE_SIZE = "13px"

# Minimum `cols_width()` values for common column shapes, at this house font/weight.
# Anything narrower than these wraps its header onto two lines.
NARROW_COL_WIDTH = "70px"  # short counting stats, W/L, single scores ("10-2", "W")
PERCENT_COL_WIDTH = "130px"  # "Off Success%" header + "46.3%" body
RATING_COL_WIDTH = "115px"  # "value (No. rank)" cells, e.g. "24.4 (No. 1)"

CHART_SOURCE_NOTE = "Source: collegefootballdata.com        Graphic: kb_analytix"
CHART_SOURCE_NOTE_SIZE = 11

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
}


def apply_matplotlib_style() -> None:
    plt.rcParams.update(MPL_RCPARAMS)


def add_chart_source_note(fig: plt.Figure) -> None:
    """Standard source/attribution footnote for every matplotlib chart —
    the chart equivalent of `SOURCE_NOTE` on GT tables. Placed bottom-right so
    it never collides with a chart-specific caveat placed bottom-left (e.g.
    "excluded" notes)."""
    fig.text(0.99, 0.01, CHART_SOURCE_NOTE, fontsize=CHART_SOURCE_NOTE_SIZE, color="#888888", ha="right")


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
            source_notes_font_size=SOURCE_NOTE_SIZE,
        )
        .tab_source_note(source_note=SOURCE_NOTE)
    )


def team_header_title(title_text: str, logo_url: str | None):
    """A `tab_header(title=...)` value with the team's logo inline before the
    title text. Use for any team-specific table so branding is consistent
    across the report, not just the first table on a page."""
    logo_html = f'<img src="{logo_url}" style="height:32px; vertical-align:middle; margin-right:10px;">' if logo_url else ""
    return html(f"{logo_html}{title_text}")


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
