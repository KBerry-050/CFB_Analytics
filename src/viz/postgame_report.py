"""Post-Game Report — a single-page "broadcast card" summarizing one finished
game: both teams and their marks, the final and quarter-by-quarter score, a
play-by-play win-probability chart, dueling traditional and advanced box-score
bars, per-quarter momentum, a drive-flow ribbon, and the players who moved the
game most by PPA. Works for any completed game
(`render_postgame_report(game_id, out_stem)`); LSU 17 @ Clemson 10, 2025 week 1,
was the pilot case.

This module deliberately does NOT follow the `viz-style` house style
(`src/viz/style.py` — great_tables, Helvetica, light striped tables). It is a
dark, hand-built HTML + inline-SVG poster, per an explicit request for a
different visual register. Don't "correct" it back toward the house style; the
one thing it does keep is the shared source/attribution wording.

Like `qb_pass_chart.py` it renders through `render_template` against a
sibling `.html` file, but every mark is generated as SVG in Python rather than
drawn in JS, so the headless-Chrome screenshot has nothing to wait on. Output
is both the standalone HTML and a 2x PNG.
"""

from __future__ import annotations

import html as html_lib
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.data.postgame import get_postgame_bundle, resolve_game_id
from src.viz.render import render_html_to_png, render_template

TEMPLATE_PATH = Path(__file__).parent / "postgame_report_template.html"

CARD_WIDTH = 1480
CONTENT_WIDTH = 1392  # card width less the 44px section padding on each side

INK = "#f4f6fa"
INK_DIM = "#c3cbd9"
INK_FAINT = "#97a1b3"
RULE = "#2b323f"
PANEL = "#0e1116"
BG = "#0a0c10"
ALERT = "#d9534f"

# On a near-black canvas a dark primary (LSU's #461d7c) disappears, so each team
# renders in whichever of its two brand colors carries more light — which is
# usually the one broadcasts use for the same reason (LSU gold, not purple).
# The floor is set well above "technically visible": these colors also carry the
# dimmed losing-side bars, so a color that only just clears the background turns
# invisible once it's drawn at partial opacity. Teams whose brand colors are
# already bright (Clemson orange, LSU gold) are untouched by it.
_LUMINANCE_FLOOR = 0.20
# Plenty of teams list white as their second color. It clears every brightness
# test and is useless as an identity — it reads as "highlighted", not as a team —
# so candidates below this chroma (white, black, grey) are dropped and the dark
# primary is lightened instead.
_CHROMA_FLOOR = 0.2
# Below this RGB distance the two teams' colors are hard to tell apart, and the
# away side is retried against its other brand color.
_COLLISION_DISTANCE = 60.0

_QUARTER_LABELS = ["1ST", "2ND", "3RD", "4TH"]

# Minimum horizontal gap between two labeled scores on the win-probability chart.
_SCORE_LABEL_SPACING = 68.0
# How far either side of a scoring play to look for the line's local extreme
# when deciding where that play's label can sit.
_SCORE_LABEL_WINDOW = 46.0
# Play-text length the turning-point callout can hold at its box width and
# type size before the text runs past the edge.
_TURNING_POINT_CHARS = 58

_DRIVE_LABELS = {
    "TD": "TD",
    "FG": "FG",
    "PUNT": "PUNT",
    "FUMBLE": "FUM",
    "INT": "INT",
    "DOWNS": "DOWNS",
    "MISSED FG": "MISS FG",
    "END OF HALF": "HALF",
    "END OF GAME": "END",
    "END OF 4TH QUARTER": "END",
    "SF": "SAFETY",
    "INT TD": "PICK 6",
    "FUMBLE RETURN TD": "FUM TD",
    "PUNT RETURN TD": "PUNT TD",
    "KICKOFF RETURN TD": "KICK TD",
}
_TURNOVER_RESULTS = {"FUMBLE", "INT", "DOWNS", "MISSED FG", "INT TD", "FUMBLE RETURN TD"}

GLOSSARY = (
    "PPA — predicted points added, how much a play moved its team's expected points. "
    "Success rate — share of plays gaining 50% of the needed yards on 1st down, 70% on 2nd, 100% on 3rd/4th. "
    "Explosiveness — average PPA on successful plays only. "
    "Havoc — share of the opponent's plays ending in a tackle for loss, forced fumble, interception or pass breakup. "
    "Line yards, stuff rate and power success split rushing credit between the line and the back. "
    "Usage — share of the team's plays a player was involved in."
)
SIGNATURE = "Source: collegefootballdata.com &nbsp;·&nbsp; Graphic: kb_analytix"


@dataclass
class Side:
    """One team's identity and result, resolved once so every section reads the
    same colors, marks and abbreviations."""

    school: str
    abbr: str
    conference: str
    color: str  # display color, already lifted for legibility on dark
    brand: str  # the team's true primary, for background washes
    logo: str | None
    points: int
    rank: float | None
    elo_pre: float | None
    elo_post: float | None
    line_scores: list[int]
    is_home: bool
    won: bool


# --------------------------------------------------------------------------
# color helpers
# --------------------------------------------------------------------------


def _clean_hex(value: str | None) -> str | None:
    if not value:
        return None
    value = str(value).strip()
    if not value.startswith("#"):
        value = "#" + value
    return value if len(value) == 7 else None


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _luminance(hex_color: str) -> float:
    def channel(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = _rgb(hex_color)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _lighten(hex_color: str, amount: float) -> str:
    r, g, b = _rgb(hex_color)
    return "#%02x%02x%02x" % tuple(round(c + (255 - c) * amount) for c in (r, g, b))


def _rgba(hex_color: str, alpha: float) -> str:
    r, g, b = _rgb(hex_color)
    return f"rgba({r},{g},{b},{alpha})"


def _chroma(hex_color: str) -> float:
    r, g, b = _rgb(hex_color)
    return (max(r, g, b) - min(r, g, b)) / 255


def _lift(hex_color: str) -> str:
    """Blend a color toward white until it clears the legibility floor."""
    while _luminance(hex_color) < _LUMINANCE_FLOOR:
        lifted = _lighten(hex_color, 0.12)
        if lifted == hex_color:
            break
        hex_color = lifted
    return hex_color


def _brand_candidates(color: str | None, alt_color: str | None) -> list[str]:
    """A team's brand colors that actually carry hue, brightest first."""
    usable = [c for c in (_clean_hex(color), _clean_hex(alt_color)) if c and _chroma(c) >= _CHROMA_FLOOR]
    return sorted(usable, key=_luminance, reverse=True)


def _display_color(color: str | None, alt_color: str | None) -> str:
    """The brand color a team renders in on the dark card: its most luminous
    hued color, lightened if it's still too dark to read."""
    candidates = _brand_candidates(color, alt_color)
    return _lift(candidates[0]) if candidates else "#9aa3b2"


def _color_distance(a: str, b: str) -> float:
    return sum((x - y) ** 2 for x, y in zip(_rgb(a), _rgb(b))) ** 0.5


def _separate_colors(away: Side, home: Side, away_brand: tuple[str | None, str | None]) -> None:
    """If both teams land on near-identical colors, retry the away side against
    its other brand color — the whole card keys off these two hues, so they have
    to stay apart. Mutates `away.color` in place when a better option exists."""
    if _color_distance(away.color, home.color) >= _COLLISION_DISTANCE:
        return
    alternatives = [_lift(c) for c in _brand_candidates(*away_brand)[1:]]
    if not alternatives:
        return
    best = max(alternatives, key=lambda c: _color_distance(c, home.color))
    if _color_distance(best, home.color) > _color_distance(away.color, home.color):
        away.color = best


# --------------------------------------------------------------------------
# small formatting helpers
# --------------------------------------------------------------------------


def _esc(text: object) -> str:
    return html_lib.escape(str(text))


def _num(value) -> float | None:
    """A plain float, or None for anything missing — every formatter and bar
    below has to survive a stat the box score simply didn't record."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(out) else out


def _clock(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


def _pct(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def _ordinal_rank(rank: float | None) -> str | None:
    return None if rank is None or pd.isna(rank) else f"AP #{int(rank)}"


# --------------------------------------------------------------------------
# bundle -> Side
# --------------------------------------------------------------------------


def _build_sides(bundle: dict) -> tuple[Side, Side]:
    """(away, home) — away first everywhere, matching the broadcast convention
    of listing the visiting team on the left."""
    meta = bundle["summary"].iloc[0]
    context = bundle["context"].iloc[0]
    identity = bundle["identity"].set_index("school")

    def side(prefix: str, is_home: bool) -> Side:
        school = meta[f"{prefix}_team"]
        row = identity.loc[school] if school in identity.index else None
        points = int(meta[f"{prefix}_points"])
        opponent_points = int(meta["home_points" if not is_home else "away_points"])
        scores = meta[f"{prefix}_line_scores"]
        return Side(
            school=school,
            abbr=(row["abbreviation"] if row is not None else school[:4].upper()),
            conference=meta[f"{prefix}_conference"] or "",
            color=_display_color(row["color"], row["alt_color"]) if row is not None else "#9aa3b2",
            brand=(_clean_hex(row["color"]) if row is not None else None) or "#4a5162",
            logo=(row["logo_data_uri"] if row is not None else None),
            points=points,
            rank=_num(context.get(f"{prefix}_rank")),
            elo_pre=_num(meta[f"{prefix}_pregame_elo"]),
            elo_post=_num(meta[f"{prefix}_postgame_elo"]),
            line_scores=[int(s) for s in str(scores).split(",") if s not in ("", "nan")],
            is_home=is_home,
            won=points > opponent_points,
        )

    away, home = side("away", False), side("home", True)
    _separate_colors(away, home, _brand_colors(identity, away.school))
    return away, home


def _brand_colors(identity: pd.DataFrame, school: str) -> tuple[str | None, str | None]:
    if school not in identity.index:
        return None, None
    row = identity.loc[school]
    return row["color"], row["alt_color"]


def _team_rows(frame: pd.DataFrame, away: Side, home: Side) -> tuple[dict, dict]:
    """A frame with one row per team, split into (away_row, home_row) dicts."""
    indexed = frame.set_index("team")
    return indexed.loc[away.school].to_dict(), indexed.loc[home.school].to_dict()


# --------------------------------------------------------------------------
# section: scoreboard hero
# --------------------------------------------------------------------------


def _hero_html(bundle: dict, away: Side, home: Side) -> str:
    meta = bundle["summary"].iloc[0]
    context = bundle["context"].iloc[0]

    kickoff = pd.Timestamp(meta["start_date"])
    # CFBD stamps kickoffs in UTC; a naive value would raise on tz_convert.
    kickoff = kickoff.tz_localize("UTC") if kickoff.tz is None else kickoff
    kickoff = kickoff.tz_convert("US/Eastern")
    where = f"{kickoff.strftime('%b %-d, %Y')} &nbsp;·&nbsp; {_esc(meta['venue'])}"
    # CFBD still designates a home team at a neutral site, and the card's whole
    # left/right and top/bottom framing follows that designation — so say when
    # the venue doesn't actually belong to either team.
    if meta["neutral_site"]:
        where += " &nbsp;·&nbsp; Neutral site"

    conditions = []
    attendance = _num(meta["attendance"])
    if attendance:
        conditions.append(f"{int(attendance):,} in attendance")
    if context.get("indoors"):
        conditions.append("Indoors")
    else:
        temperature = _num(context.get("temperature"))
        if temperature is not None:
            weather = f"{temperature:.0f}°F"
            if context.get("weather_condition"):
                weather += f" {_esc(context['weather_condition'])}"
            wind = _num(context.get("wind_speed"))
            if wind:
                weather += f", wind {wind:.0f} mph"
            conditions.append(weather)

    pills = []
    spread = _num(context.get("spread"))
    if spread is not None:
        favorite, margin = (home, -spread) if spread < 0 else (away, spread)
        pills.append(f"Line <b>{_esc(favorite.abbr)} {-abs(margin):.1f}</b>")
    over_under = _num(context.get("over_under"))
    if over_under is not None:
        pills.append(f"O/U <b>{over_under:.1f}</b>")
    pregame_wp = _num(context.get("home_pregame_wp"))
    if pregame_wp is not None:
        pills.append(f"Pregame <b>{_esc(home.abbr)} {pregame_wp * 100:.0f}%</b>")
    excitement = _num(meta["excitement"])
    if excitement is not None:
        pills.append(f"Excitement <b>{excitement:.1f}</b>")

    # An upset is framed off the pregame market, not the poll ranks: the
    # underdog winning is the thing the numbers didn't expect.
    if pregame_wp is not None:
        winner = home if home.won else away
        winner_wp = pregame_wp if winner.is_home else 1 - pregame_wp
        if winner_wp < 0.5:
            pills.append(
                f'<span class="pill flag">Upset &nbsp;·&nbsp; {_esc(winner.abbr)} won at '
                f"{winner_wp * 100:.0f}%</span>"
            )

    pill_html = "".join(p if p.startswith("<span") else f'<span class="pill">{p}</span>' for p in pills)

    glow = (
        f"background: radial-gradient(760px 320px at 0% 10%, {_rgba(away.brand, 0.34)}, transparent 68%), "
        f"radial-gradient(760px 320px at 100% 10%, {_rgba(home.brand, 0.34)}, transparent 68%);"
    )

    return f"""
  <section class="hero" style="{glow}">
    <div class="hero-grid">
      {_team_block(away)}
      <div class="num score {'' if away.won else 'lost'}" style="color:{away.color if away.won else ''}">{away.points}</div>
      <div class="center">
        <div class="final">FINAL</div>
        <div class="where">{where}</div>
        <div class="cond">{' &nbsp;·&nbsp; '.join(conditions)}</div>
        <div class="pills">{pill_html}</div>
      </div>
      <div class="num score {'' if home.won else 'lost'}" style="color:{home.color if home.won else ''}">{home.points}</div>
      {_team_block(home)}
    </div>
    {_line_score_html(away, home)}
  </section>"""


def _team_block(side: Side) -> str:
    logo = f'<img src="{side.logo}" alt="{_esc(side.school)}">' if side.logo else ""
    rank = _ordinal_rank(side.rank)
    rank_html = f'<div class="rank" style="background:{side.color}">{rank}</div>' if rank else ""
    elo = ""
    if side.elo_pre is not None and side.elo_post is not None:
        delta = side.elo_post - side.elo_pre
        elo = f'<div class="sub">Elo {side.elo_pre:.0f} &rarr; {side.elo_post:.0f} ({delta:+.0f})</div>'
    return f"""<div class="team">
        {logo}
        {rank_html}
        <div class="school" style="font-size:{_school_font_size(side.school)}">{_esc(side.school)}</div>
        <div class="sub">{_esc(side.conference)}</div>
        {elo}
      </div>"""


def _school_font_size(school: str) -> str:
    """Step long school names down so they fit the 250px team column on one
    line — "Western Michigan" at the base size wraps, which leaves the two team
    blocks sitting at different heights."""
    if len(school) <= 11:
        return "30px"
    return "24px" if len(school) <= 17 else "19px"


def _line_score_html(away: Side, home: Side) -> str:
    periods = max(len(away.line_scores), len(home.line_scores), 4)
    headers = "".join(f"<th>{_period_label(i + 1)}</th>" for i in range(periods))

    def row(side: Side) -> str:
        cells = "".join(
            f'<td class="q num">{side.line_scores[i] if i < len(side.line_scores) else "—"}</td>'
            for i in range(periods)
        )
        return (
            f'<tr><td class="team-cell"><span class="swatch" style="background:{side.color}"></span>'
            f"{_esc(side.school)}</td>{cells}"
            f'<td class="tot num">{side.points}</td></tr>'
        )

    return f"""
    <div class="linescore">
      <table>
        <tr><th></th>{headers}<th>T</th></tr>
        {row(away)}
        {row(home)}
      </table>
    </div>"""


# --------------------------------------------------------------------------
# section: win probability
# --------------------------------------------------------------------------


# Overtime carries no game clock, so every OT play would land on the same x.
# Instead the axis reserves a trailing band and spreads the OT plays evenly
# across it, separated from regulation by a labeled divider.
_OT_BAND_FRACTION = 0.18


def _win_probability_svg(bundle: dict, away: Side, home: Side) -> str:
    wp = bundle["win_prob"].copy()
    context = bundle["context"].iloc[0]

    width, height = CONTENT_WIDTH, 300
    left, right, top, bottom = 66, 58, 32, 34
    x0, x1 = left, width - right
    y0, y1 = top, height - bottom
    plot_w, plot_h = x1 - x0, y1 - y0
    mid_y = y0 + plot_h / 2

    has_overtime = bool((wp["period"] > 4).any())
    regulation_w = plot_w * (1 - _OT_BAND_FRACTION) if has_overtime else plot_w

    def reg_x(seconds: float) -> float:
        """Where a regulation game-clock position falls on the axis."""
        return x0 + min(max(seconds, 0.0), 3600.0) / 3600 * regulation_w

    overtime = wp.index[wp["period"] > 4]
    ot_x = {}
    for order, index in enumerate(overtime):
        # +1 so the first overtime play sits inside the band rather than on the
        # divider, and the last lands on the right edge.
        ot_x[index] = x0 + regulation_w + (order + 1) / len(overtime) * (plot_w - regulation_w)

    wp["x"] = [
        ot_x.get(index, reg_x(seconds))
        for index, seconds in zip(wp.index, wp["elapsed_seconds"])
    ]
    wp["y"] = y1 - wp["home_win_prob"] * plot_h

    points = list(zip(wp["x"], wp["y"]))
    line_path = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area_path = f"{line_path} L {points[-1][0]:.1f},{mid_y:.1f} L {points[0][0]:.1f},{mid_y:.1f} Z"

    parts = [
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<defs>",
        f'<clipPath id="wp-home"><rect x="{x0}" y="{y0}" width="{plot_w}" height="{mid_y - y0}"/></clipPath>',
        f'<clipPath id="wp-away"><rect x="{x0}" y="{mid_y}" width="{plot_w}" height="{y1 - mid_y}"/></clipPath>',
        "</defs>",
        f'<rect x="{x0}" y="{y0}" width="{plot_w}" height="{plot_h}" fill="{PANEL}" rx="3"/>',
    ]

    # Horizontal reference lines; the 50% line is the one that matters, so it
    # reads brighter than the quartiles.
    for level in (0.25, 0.5, 0.75):
        y = y1 - level * plot_h
        stroke = RULE if level == 0.5 else "#171b23"
        parts.append(
            f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" stroke="{stroke}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{x0 - 10}" y="{y + 4:.1f}" text-anchor="end" font-size="11" '
            f'fill="{INK_FAINT}">{level * 100:.0f}%</text>'
        )

    parts += [
        f'<path d="{area_path}" fill="{_rgba(home.color, 0.34)}" clip-path="url(#wp-home)"/>',
        f'<path d="{area_path}" fill="{_rgba(away.color, 0.34)}" clip-path="url(#wp-away)"/>',
        f'<path d="{line_path}" fill="none" stroke="{INK}" stroke-width="2" '
        'stroke-linejoin="round" stroke-linecap="round"/>',
    ]

    # Period dividers and labels.
    boundaries = [(quarter * 900, _period_label(quarter)) for quarter in range(1, 5)]
    for boundary, label in boundaries:
        x = reg_x(boundary)
        if boundary < 3600 or has_overtime:
            parts.append(
                f'<line x1="{x:.1f}" y1="{y0}" x2="{x:.1f}" y2="{y1}" stroke="{RULE}" '
                'stroke-width="1" stroke-dasharray="2 4"/>'
            )
        parts.append(
            f'<text x="{reg_x(boundary - 450):.1f}" y="{y0 - 10}" text-anchor="middle" font-size="11" '
            f'letter-spacing="1" fill="{INK_DIM}">{label}</text>'
        )
    if has_overtime:
        parts.append(
            f'<text x="{(x0 + regulation_w + x1) / 2:.1f}" y="{y0 - 10}" text-anchor="middle" '
            f'font-size="11" letter-spacing="1" fill="{INK_DIM}">OT</text>'
        )

    # The axis reads as "how likely was each team to win": the home team anchors
    # the top, the away team the bottom. Both labels live in the left margin,
    # outside the plot, so nothing inside has to route around them.
    parts += [
        f'<text x="{x0 - 10}" y="{y0 + 10}" text-anchor="end" font-size="12" letter-spacing="0.8" '
        f'font-weight="700" fill="{home.color}">{_esc(home.abbr)}</text>',
        f'<text x="{x0 - 10}" y="{y1}" text-anchor="end" font-size="12" letter-spacing="0.8" '
        f'font-weight="700" fill="{away.color}">{_esc(away.abbr)}</text>',
    ]

    pregame_wp = _num(context.get("home_pregame_wp"))
    if pregame_wp is not None:
        # The dot marks where the betting market had the game before kickoff.
        # Its caption goes in the period-label row above the plot rather than
        # beside the dot, which in a lopsided matchup would land on top of the
        # first scoring play's label.
        y = y1 - pregame_wp * plot_h
        parts += [
            f'<circle cx="{x0}" cy="{y:.1f}" r="3.5" fill="{BG}" stroke="{INK_DIM}" stroke-width="1.5"/>',
            f'<text x="{x0}" y="{y0 - 10}" font-size="10.5" letter-spacing="0.6" '
            f'fill="{INK_FAINT}">PREGAME {_esc(home.abbr)} {pregame_wp * 100:.0f}%</text>',
        ]

    parts.append(_scoring_markers(wp, away, home, mid_y, x0, x1, y0, y1))
    parts.append(_turning_point(wp, away, home, points, x0, x1, y0, y1))
    parts.append("</svg>")

    return f"""
  <section>
    <div class="eyebrow">Win probability &nbsp;·&nbsp; every play</div>
    {''.join(parts)}
  </section>"""


def _scoring_markers(wp: pd.DataFrame, away: Side, home: Side, mid_y: float,
                     x_min: float, x_max: float, y_top: float, y_bottom: float) -> str:
    """Dots and labels for each score change, read off the running score rather
    than the play text so a scoring play the feed words unusually still lands."""
    points = list(zip(wp["x"], wp["y"]))
    events = []
    previous = (0, 0)
    for row in wp.itertuples():
        scores = (int(row.home_score), int(row.away_score))
        if scores == previous:
            continue
        home_delta, away_delta = scores[0] - previous[0], scores[1] - previous[1]
        # CFBD's feed zeroes the running score at the overtime boundary. A score
        # that goes down is that reset, not a play — ignore the row entirely and
        # keep comparing against the last real score.
        if home_delta < 0 or away_delta < 0:
            continue
        previous = scores
        scorer, delta = (home, home_delta) if home_delta > away_delta else (away, away_delta)
        kind = {2: "SAFETY", 3: "FG", 6: "TD", 7: "TD", 8: "TD"}.get(delta, "SCORE")
        events.append((row.x, row.y, scores, scorer, kind))

    labeled = _thin_labels([x for x, _, _, _, _ in events], x_min, x_max)

    parts = []
    for index, (x, y, scores, scorer, kind) in enumerate(events):
        first_y = _score_label_y(points, x, y, mid_y, y_top, y_bottom)
        label_x = min(max(x, x_min + 46), x_max - 46)

        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{BG}" '
            f'stroke="{scorer.color}" stroke-width="2.5"/>'
        )
        if index not in labeled:
            continue

        parts.append(
            f'<text x="{label_x:.1f}" y="{first_y:.1f}" text-anchor="middle" font-size="11" '
            f'letter-spacing="0.7" font-weight="700" fill="{scorer.color}">'
            f"{_esc(scorer.abbr)} {kind}</text>"
        )
        # Score reads from the scoring team's side ("CLEM FG / 3-0"), which is
        # how a broadcast would call it, not always home-first.
        scorer_points, other_points = (scores[0], scores[1]) if scorer is home else (scores[1], scores[0])
        parts.append(
            f'<text class="num" x="{label_x:.1f}" y="{first_y + 15:.1f}" '
            f'text-anchor="middle" font-size="15" fill="{INK}">'
            f"{scorer_points}&#8211;{other_points}</text>"
        )
    return "".join(parts)


def _score_label_y(points: list[tuple[float, float]], x: float, y: float,
                   mid_y: float, y_top: float, y_bottom: float) -> float:
    """Baseline for a score label's first line.

    A fixed offset from the marker isn't enough: the win-probability line often
    peaks just beside a scoring play, and the label lands on the line. So the
    label clears the line's local extreme within a window either side of the
    marker instead. Preference is the side away from the 50% midline — the side
    the shaded area isn't filling — but a line pinned near the top or bottom of
    the plot flips the label back into the band, where it still reads against
    the 34%-alpha fill.
    """

    def extreme(above: bool) -> float:
        nearby = [py for px, py in points if abs(px - x) <= _SCORE_LABEL_WINDOW]
        if not nearby:
            return y
        return min(nearby) if above else max(nearby)

    for above in (True, False) if y < mid_y else (False, True):
        candidate = extreme(above) - 22 if above else extreme(above) + 24
        if above and candidate >= y_top + 10:
            return candidate
        if not above and candidate <= y_bottom - 19:
            return candidate
    # Neither side has room — a near-certain game that still scored at both
    # extremes. Sit the label just off the marker, clamped inside the plot.
    return min(max(y + 20, y_top + 14), y_bottom - 20)


def _thin_labels(positions: list[float], x_min: float, x_max: float) -> set[int]:
    """Which score markers get a text label. A scoring-heavy game would pile its
    labels on top of each other, so they're thinned by minimum spacing — but the
    game-winning score is always kept, displacing an earlier label if it has to.
    """
    if not positions:
        return set()

    def clamp(x: float) -> float:
        return min(max(x, x_min + 46), x_max - 46)

    kept: list[int] = []
    for index, position in enumerate(positions):
        if not kept or clamp(position) - clamp(positions[kept[-1]]) >= _SCORE_LABEL_SPACING:
            kept.append(index)
    final = len(positions) - 1
    if final not in kept:
        while kept and clamp(positions[final]) - clamp(positions[kept[-1]]) < _SCORE_LABEL_SPACING:
            kept.pop()
        kept.append(final)
    return set(kept)


def _turning_point(wp: pd.DataFrame, away: Side, home: Side,
                   points: list[tuple[float, float]], x0, x1, y0, y1) -> str:
    """Callout for the single play that moved win probability most.

    The box goes in the horizontal half opposite the play (so the leader line
    never crosses the whole chart) and, of the two corners there, the one the
    win-probability line itself stays farthest away from. The 26px insets keep
    it clear of the team labels pinned inside the plot's top and bottom edges.
    """
    row = wp.loc[wp["wp_swing"].abs().idxmax()]
    swing = float(row["wp_swing"])
    beneficiary = home if swing > 0 else away
    x, y = float(row["x"]), float(row["y"])

    box_w, box_h = 392.0, 70.0
    box_x = x0 + 14 if x > (x0 + x1) / 2 else x1 - box_w - 14
    box_y = max(
        (y0 + 26, y1 - 26 - box_h),
        key=lambda box_top: _clearance(points, box_x, box_top, box_w, box_h),
    )

    text = str(row["play_text"])
    if len(text) > _TURNING_POINT_CHARS:
        text = text[: _TURNING_POINT_CHARS - 3].rstrip() + "…"

    anchor_x = box_x + box_w if box_x + box_w < x else box_x
    anchor_y = box_y + box_h / 2

    return (
        f'<line x1="{anchor_x:.1f}" y1="{anchor_y:.1f}" x2="{x:.1f}" y2="{y:.1f}" '
        f'stroke="{INK_FAINT}" stroke-width="1" stroke-dasharray="2 3"/>'
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8" fill="none" stroke="{beneficiary.color}" stroke-width="1.5"/>'
        f'<rect x="{box_x:.1f}" y="{box_y:.1f}" width="{box_w}" height="{box_h}" rx="3" '
        f'fill="{BG}" fill-opacity="0.94" stroke="{RULE}"/>'
        f'<text x="{box_x + 14:.1f}" y="{box_y + 19:.1f}" font-size="10" letter-spacing="1.4" '
        f'font-weight="700" fill="{INK_DIM}">TURNING POINT</text>'
        f'<text x="{box_x + 14:.1f}" y="{box_y + 39:.1f}" font-size="12.5" fill="{INK}">{_esc(text)}</text>'
        f'<text x="{box_x + 14:.1f}" y="{box_y + 58:.1f}" font-size="12" font-weight="700" '
        f'fill="{beneficiary.color}">{abs(swing) * 100:.0f}% win probability swing to '
        f"{_esc(beneficiary.abbr)}</text>"
    )



def _clearance(points: list[tuple[float, float]], bx: float, by: float, bw: float, bh: float) -> float:
    """Distance from a candidate box to the nearest point on a plotted series —
    used to park an annotation where it won't sit on top of the data."""
    return min(
        max(bx - px, 0, px - (bx + bw)) + max(by - py, 0, py - (by + bh)) for px, py in points
    )


# --------------------------------------------------------------------------
# section: dueling stat bars
# --------------------------------------------------------------------------

# (label, value, display, higher_is_better) — value drives the bar and the
# winner mark, display is what the reader sees, and the two differ wherever the
# honest number is a rate but the familiar one is a raw count ("3-13").
TRADITIONAL_METRICS = [
    ("Total Yards", lambda b, a: _num(b.get("total_yards")), lambda v, b, a: f"{v:.0f}", True),
    (
        "Yards / Play",
        lambda b, a: _safe_ratio(_num(b.get("total_yards")), _num(a.get("plays"))),
        lambda v, b, a: f"{v:.1f}",
        True,
    ),
    ("Passing Yards", lambda b, a: _num(b.get("passing_yards")), lambda v, b, a: f"{v:.0f}", True),
    (
        "Comp / Att",
        lambda b, a: _safe_ratio(_num(b.get("completions")), _num(b.get("pass_attempts"))),
        lambda v, b, a: f"{b.get('completions', 0):.0f}-{b.get('pass_attempts', 0):.0f}",
        True,
    ),
    ("Rushing Yards", lambda b, a: _num(b.get("rushing_yards")), lambda v, b, a: f"{v:.0f}", True),
    ("Yards / Rush", lambda b, a: _num(b.get("yards_per_rush")), lambda v, b, a: f"{v:.1f}", True),
    ("First Downs", lambda b, a: _num(b.get("first_downs")), lambda v, b, a: f"{v:.0f}", True),
    (
        "3rd Down",
        lambda b, a: _safe_ratio(_num(b.get("third_down_conv")), _num(b.get("third_down_att"))),
        lambda v, b, a: f"{b.get('third_down_conv', 0):.0f}-{b.get('third_down_att', 0):.0f}",
        True,
    ),
    (
        "4th Down",
        lambda b, a: _safe_ratio(_num(b.get("fourth_down_conv")), _num(b.get("fourth_down_att"))),
        lambda v, b, a: f"{b.get('fourth_down_conv', 0):.0f}-{b.get('fourth_down_att', 0):.0f}",
        True,
    ),
    ("Sacks", lambda b, a: _num(b.get("sacks")), lambda v, b, a: f"{v:.0f}", True),
    ("Tackles For Loss", lambda b, a: _num(b.get("tackles_for_loss")), lambda v, b, a: f"{v:.0f}", True),
    ("Turnovers", lambda b, a: _num(b.get("turnovers")), lambda v, b, a: f"{v:.0f}", False),
    (
        "Penalty Yards",
        lambda b, a: _num(b.get("penalty_yards")),
        lambda v, b, a: f"{b.get('penalties', 0):.0f}-{v:.0f}",
        False,
    ),
    (
        "Possession",
        lambda b, a: _num(b.get("possession_seconds")),
        lambda v, b, a: _clock(v),
        True,
    ),
]

ADVANCED_METRICS = [
    ("PPA / Play", lambda b, a: _num(a.get("ppa")), lambda v, b, a: f"{v:+.3f}", True),
    ("Success Rate", lambda b, a: _num(a.get("success_rate")), lambda v, b, a: _pct(v), True),
    ("Explosiveness", lambda b, a: _num(a.get("explosiveness")), lambda v, b, a: f"{v:.2f}", True),
    ("Std. Downs SR", lambda b, a: _num(a.get("standard_downs_sr")), lambda v, b, a: _pct(v), True),
    ("Pass. Downs SR", lambda b, a: _num(a.get("passing_downs_sr")), lambda v, b, a: _pct(v), True),
    ("Passing PPA", lambda b, a: _num(a.get("ppa_passing")), lambda v, b, a: f"{v:+.3f}", True),
    ("Rushing PPA", lambda b, a: _num(a.get("ppa_rushing")), lambda v, b, a: f"{v:+.3f}", True),
    ("Havoc Rate", lambda b, a: _num(a.get("havoc")), lambda v, b, a: _pct(v), True),
    ("Line Yards / Rush", lambda b, a: _num(a.get("line_yards")), lambda v, b, a: f"{v:.1f}", True),
    ("Stuff Rate", lambda b, a: _num(a.get("stuff_rate")), lambda v, b, a: _pct(v), False),
    ("Power Success", lambda b, a: _num(a.get("power_success")), lambda v, b, a: _pct(v, 0), True),
    (
        "Avg Start",
        lambda b, a: _flip_field_position(_num(a.get("avg_start"))),
        lambda v, b, a: f"Own {v:.0f}",
        True,
    ),
    ("Scoring Opps", lambda b, a: _num(a.get("scoring_opps")), lambda v, b, a: f"{v:.0f}", True),
    ("Points / Opp", lambda b, a: _num(a.get("points_per_opp")), lambda v, b, a: f"{v:.2f}", True),
]


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or not denominator:
        return None
    return numerator / denominator


def _flip_field_position(yards_to_goal: float | None) -> float | None:
    """CFBD reports average starting field position as yards to the opponent's
    goal line; readers expect it as their own yard line, where bigger is
    better."""
    return None if yards_to_goal is None else 100 - yards_to_goal


def _duel_html(bundle: dict, away: Side, home: Side) -> str:
    away_box, home_box = _team_rows(bundle["team_box"], away, home)
    away_adv, home_adv = _team_rows(bundle["advanced_box"], away, home)

    def column(title: str, metrics: list) -> str:
        rows = [
            _duel_row(label, away, home, value_fn, display_fn, higher_is_better,
                      away_box, home_box, away_adv, home_adv)
            for label, value_fn, display_fn, higher_is_better in metrics
        ]
        return f'<div class="duel-col"><div class="eyebrow">{title}</div>{"".join(rows)}</div>'

    return f"""
  <section>
    <div class="eyebrow">Team comparison &nbsp;·&nbsp; {_esc(away.school)} left, {_esc(home.school)} right</div>
    <div class="duel">
      {column("Box score", TRADITIONAL_METRICS)}
      {column("Advanced metrics", ADVANCED_METRICS)}
    </div>
  </section>"""


def _duel_row(label, away, home, value_fn, display_fn, higher_is_better,
              away_box, home_box, away_adv, home_adv) -> str:
    away_value = value_fn(away_box, away_adv)
    home_value = value_fn(home_box, home_adv)
    away_text = display_fn(away_value, away_box, away_adv) if away_value is not None else "—"
    home_text = display_fn(home_value, home_box, home_adv) if home_value is not None else "—"

    # Bars are scaled against the larger of the two, not their sum, so the
    # leader always reaches the edge and the gap is what the eye compares.
    scale = max(abs(away_value or 0), abs(home_value or 0)) or 1.0

    def bar(value: float | None, sides: str, is_winner: bool) -> str:
        if value is None:
            return f'<div class="track {sides}"></div>'
        width = abs(value) / scale * 100
        classes = " ".join(c for c in ("neg" if value < 0 else "", "" if is_winner else "lose") if c)
        return f'<div class="track {sides}"><i class="{classes}" style="width:{width:.1f}%"></i></div>'

    if away_value is None or home_value is None or away_value == home_value:
        away_wins = home_wins = True
    else:
        away_wins = (away_value > home_value) if higher_is_better else (away_value < home_value)
        home_wins = not away_wins

    return f"""<div class="duel-row">
        <div class="num dv l{'' if away_wins else ' dim'}">{away_text}</div>
        {bar(away_value, 'l', away_wins)}
        <div class="lab">{_esc(label)}</div>
        {bar(home_value, 'r', home_wins)}
        <div class="num dv r{'' if home_wins else ' dim'}">{home_text}</div>
      </div>"""


# --------------------------------------------------------------------------
# section: momentum (quarter splits + drive flow)
# --------------------------------------------------------------------------


def _momentum_html(bundle: dict, away: Side, home: Side) -> str:
    return f"""
  <section>
    <div class="eyebrow">Momentum</div>
    <div class="momentum">
      {_quarter_svg(bundle, away, home)}
      {_drive_flow_svg(bundle, away, home)}
    </div>
  </section>"""


def _quarter_svg(bundle: dict, away: Side, home: Side) -> str:
    splits = bundle["quarter_splits"]
    width, height = 604, 272
    panel_w = (width - 12) / 4

    def value(team: str, metric: str, quarter: int) -> float | None:
        match = splits[
            (splits["team"] == team) & (splits["metric"] == metric) & (splits["quarter"] == quarter)
        ]
        return None if match.empty else _num(match.iloc[0]["value"])

    ppa_values = [value(s.school, "ppa", q) for s in (away, home) for q in (1, 2, 3, 4)]
    ppa_scale = max((abs(v) for v in ppa_values if v is not None), default=1.0) or 1.0
    sr_values = [value(s.school, "success_rate", q) for s in (away, home) for q in (1, 2, 3, 4)]
    sr_scale = max(max((v for v in sr_values if v is not None), default=0.5), 0.5)

    parts = [
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<text x="6" y="11" font-size="11" letter-spacing="1.3" font-weight="700" '
        f'fill="{INK_DIM}">PPA PER PLAY</text>',
        f'<text x="6" y="170" font-size="11" letter-spacing="1.3" font-weight="700" '
        f'fill="{INK_DIM}">SUCCESS RATE</text>',
    ]

    # Two stacked charts sharing one set of quarter columns. The reach of each
    # is set so a full-height bar's value label still clears the header of the
    # chart below it — a big negative PPA quarter and a high success rate in the
    # same quarter would otherwise collide.
    ppa_zero, ppa_reach = 88.0, 46.0
    sr_base, sr_reach = 244.0, 44.0

    for quarter in range(1, 5):
        cx = 6 + panel_w * (quarter - 0.5)
        if quarter > 1:
            x = 6 + panel_w * (quarter - 1)
            parts.append(
                f'<line x1="{x:.1f}" y1="20" x2="{x:.1f}" y2="{sr_base + 8:.1f}" stroke="#161a21" stroke-width="1"/>'
            )
        parts.append(
            f'<line x1="{cx - panel_w / 2 + 8:.1f}" y1="{ppa_zero}" x2="{cx + panel_w / 2 - 8:.1f}" '
            f'y2="{ppa_zero}" stroke="{RULE}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{cx:.1f}" y="266" text-anchor="middle" font-size="11" letter-spacing="1" '
            f'fill="{INK_DIM}">{_QUARTER_LABELS[quarter - 1]}</text>'
        )

        # CFBD doesn't always carry splits for every quarter (garbage time in a
        # rout is a common gap). Say so rather than leaving a panel that reads
        # as two teams doing nothing.
        if all(
            value(s.school, m, quarter) is None
            for s in (away, home)
            for m in ("ppa", "success_rate")
        ):
            parts.append(
                f'<text x="{cx:.1f}" y="{ppa_zero - 6:.1f}" text-anchor="middle" font-size="10.5" '
                f'letter-spacing="0.8" fill="{INK_FAINT}">NO DATA</text>'
            )
            continue

        for index, side in enumerate((away, home)):
            bar_x = cx - 34 + index * 38
            ppa = value(side.school, "ppa", quarter)
            if ppa is not None:
                bar_h = abs(ppa) / ppa_scale * ppa_reach
                bar_y = ppa_zero - bar_h if ppa >= 0 else ppa_zero
                parts.append(
                    f'<rect x="{bar_x:.1f}" y="{bar_y:.1f}" width="30" height="{max(bar_h, 1):.1f}" '
                    f'fill="{side.color}" fill-opacity="{0.95 if ppa >= 0 else 0.4}"/>'
                )
                label_y = bar_y - 5 if ppa >= 0 else bar_y + bar_h + 13
                parts.append(
                    f'<text class="num" x="{bar_x + 15:.1f}" y="{label_y:.1f}" text-anchor="middle" '
                    f'font-size="14" fill="{INK if ppa >= 0 else INK_DIM}">{ppa:+.2f}</text>'
                )

            success = value(side.school, "success_rate", quarter)
            if success is not None:
                bar_h = success / sr_scale * sr_reach
                parts.append(
                    f'<rect x="{bar_x:.1f}" y="{sr_base - bar_h:.1f}" width="30" height="{bar_h:.1f}" '
                    f'fill="{side.color}" fill-opacity="0.95"/>'
                )
                parts.append(
                    f'<text class="num" x="{bar_x + 15:.1f}" y="{sr_base - bar_h - 5:.1f}" '
                    f'text-anchor="middle" font-size="14" fill="{INK}">{success * 100:.0f}%</text>'
                )

    parts.append(f'<line x1="6" y1="{sr_base}" x2="{width - 6}" y2="{sr_base}" stroke="{RULE}" stroke-width="1"/>')
    parts.append(_swatch_legend(width - 6, 11, (away, home), anchor="end"))
    parts.append("</svg>")
    return "".join(parts)


def _swatch_legend(x: float, y: float, sides: tuple[Side, ...], anchor: str = "start") -> str:
    """Inline team key, laid out right-to-left when anchored to the right edge
    so it never runs past the SVG."""
    parts = []
    cursor = x
    for side in reversed(sides) if anchor == "end" else sides:
        label_w = len(side.abbr) * 6.6
        if anchor == "end":
            cursor -= label_w
            parts.append(
                f'<text x="{cursor:.1f}" y="{y}" font-size="11" letter-spacing="0.8" '
                f'font-weight="700" fill="{side.color}">{_esc(side.abbr)}</text>'
            )
            cursor -= 8
            parts.append(f'<rect x="{cursor - 6:.1f}" y="{y - 8}" width="6" height="8" fill="{side.color}"/>')
            cursor -= 20
        else:
            parts.append(f'<rect x="{cursor:.1f}" y="{y - 8}" width="6" height="8" fill="{side.color}"/>')
            parts.append(
                f'<text x="{cursor + 10:.1f}" y="{y}" font-size="11" letter-spacing="0.8" '
                f'font-weight="700" fill="{side.color}">{_esc(side.abbr)}</text>'
            )
            cursor += label_w + 26
    return "".join(parts)


def _period_label(period: int) -> str:
    return _QUARTER_LABELS[period - 1] if period <= 4 else f"OT{period - 4}"


def _drive_result_label(result: str) -> str:
    result = (result or "").upper()
    return _DRIVE_LABELS.get(result, result[:7])


def _drive_flow_svg(bundle: dict, away: Side, home: Side) -> str:
    drives = bundle["drives"]
    width, height = 736, 272
    axis_y = 140.0
    reach = 74.0

    n = max(len(drives), 1)
    # Left gutter reserved for the two team labels that key the axis, so the
    # first drive's bar never lands underneath them.
    gutter = 40.0
    col_w = (width - gutter - 6) / n
    bar_w = min(26.0, col_w - 5)
    max_yards = max(float(drives["yards"].max()), 1.0)

    parts = [
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<text x="6" y="11" font-size="11" letter-spacing="1.3" font-weight="700" '
        f'fill="{INK_DIM}">DRIVE FLOW &#183; BAR HEIGHT = YARDS GAINED</text>',
        f'<line x1="6" y1="{axis_y}" x2="{width - 6}" y2="{axis_y}" stroke="{RULE}" stroke-width="1"/>',
        f'<text x="{gutter + 4:.1f}" y="26" font-size="10.5" letter-spacing="0.8" '
        f'fill="{INK_FAINT}">{_QUARTER_LABELS[0]}</text>',
    ]

    previous_period = None
    for index, drive in enumerate(drives.itertuples()):
        cx = gutter + col_w * (index + 0.5)
        if previous_period is not None and drive.start_period != previous_period:
            x = gutter + col_w * index
            parts.append(
                f'<line x1="{x:.1f}" y1="18" x2="{x:.1f}" y2="{height - 20}" stroke="{RULE}" '
                'stroke-width="1" stroke-dasharray="2 4"/>'
            )
            parts.append(
                f'<text x="{x + 4:.1f}" y="26" font-size="10.5" letter-spacing="0.8" '
                f'fill="{INK_FAINT}">{_period_label(int(drive.start_period))}</text>'
            )
        previous_period = drive.start_period

        side = home if drive.is_home_offense else away
        yards = max(float(drive.yards or 0), 0.0)
        bar_h = 7 + yards / max_yards * reach
        fill_opacity, stroke = _drive_style(str(drive.result))
        label = _drive_result_label(str(drive.result))

        if drive.is_home_offense:
            bar_y = axis_y - bar_h
            label_transform = f"translate({cx + 3.5:.1f},{bar_y - 5:.1f}) rotate(-90)"
            label_anchor = "start"
        else:
            bar_y = axis_y
            label_transform = f"translate({cx + 3.5:.1f},{axis_y + bar_h + 5:.1f}) rotate(-90)"
            label_anchor = "end"

        stroke_attr = f' stroke="{stroke}" stroke-width="1"' if stroke else ""
        parts.append(
            f'<rect x="{cx - bar_w / 2:.1f}" y="{bar_y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" '
            f'fill="{side.color}" fill-opacity="{fill_opacity}"{stroke_attr} rx="1"/>'
        )
        parts.append(
            f'<text transform="{label_transform}" text-anchor="{label_anchor}" font-size="10" '
            f'letter-spacing="0.4" font-weight="700" fill="{INK_DIM}">{_esc(label)}</text>'
        )

    parts.append(
        f'<text x="6" y="{axis_y - 6:.1f}" font-size="11" letter-spacing="0.8" font-weight="700" '
        f'fill="{home.color}">{_esc(home.abbr)}</text>'
    )
    parts.append(
        f'<text x="6" y="{axis_y + 14:.1f}" font-size="11" letter-spacing="0.8" font-weight="700" '
        f'fill="{away.color}">{_esc(away.abbr)}</text>'
    )
    parts.append(
        f'<text x="{width - 6}" y="{height - 4}" text-anchor="end" font-size="10.5" '
        f'fill="{INK_FAINT}">Solid = points &#183; outlined = turnover or turnover on downs</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def _drive_style(result: str) -> tuple[float, str | None]:
    result = result.upper()
    if result in ("TD", "FG", "SF") or result.endswith(" TD"):
        return 0.95, None
    if result in _TURNOVER_RESULTS:
        return 0.14, ALERT
    return 0.4, None


# --------------------------------------------------------------------------
# section: player impact
# --------------------------------------------------------------------------


def _players_html(bundle: dict, away: Side, home: Side, top_n: int = 5) -> str:
    players = bundle["player_impact"]
    if players.empty:
        return ""
    scale = max(float(players["total_ppa"].abs().max()), 0.1)

    def column(side: Side) -> str:
        subset = players[players["team"] == side.school].nlargest(top_n, "total_ppa")
        rows = "".join(_player_row(row, side, scale) for row in subset.itertuples())
        logo = f'<img src="{side.logo}" alt="">' if side.logo else ""
        return f"""<div class="pcol">
        <h4>{logo}<span style="color:{side.color}">{_esc(side.school)}</span></h4>
        {rows}
      </div>"""

    return f"""
  <section>
    <div class="eyebrow">Player impact &nbsp;·&nbsp; top {top_n} by total PPA</div>
    <div class="players">
      {column(away)}
      {column(home)}
    </div>
  </section>"""


def _player_row(row, side: Side, scale: float) -> str:
    total_ppa = _num(row.total_ppa) or 0.0
    usage = _num(row.usage)
    stat_line = row.stat_line if isinstance(row.stat_line, str) else ""
    width = abs(total_ppa) / scale * 100
    color = side.color if total_ppa >= 0 else ALERT
    return f"""<div class="prow">
        <div class="pos">{_esc(row.position or '—')}</div>
        <div>
          <div class="name">{_esc(row.player)}</div>
          <div class="line">{_esc(stat_line)}</div>
          <div class="pbar"><i style="width:{width:.1f}%; background:{color}"></i></div>
        </div>
        <div class="impact">
          <div class="num v" style="color:{color}">{total_ppa:+.1f}</div>
          <div class="u">PPA &nbsp;·&nbsp; {_pct(usage, 0) if usage is not None else '—'} usage</div>
        </div>
      </div>"""


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------


def _footer_html() -> str:
    return f"""
  <div class="foot">
    <div class="gloss">{GLOSSARY}</div>
    <div class="sig">{SIGNATURE}</div>
  </div>"""


def build_postgame_report_html(game_id: int) -> str:
    """The complete post-game card for one game as a self-contained HTML string
    — logos embedded, no external scripts, styles or fonts beyond system ones."""
    bundle = get_postgame_bundle(game_id)
    away, home = _build_sides(bundle)
    meta = bundle["summary"].iloc[0]

    return render_template(
        TEMPLATE_PATH,
        {
            "{{TITLE}}": f"{away.school} {away.points}, {home.school} {home.points} — "
            f"{meta['season']} Week {meta['week']}",
            "{{AWAY_COLOR}}": away.color,
            "{{HOME_COLOR}}": home.color,
            "{{HERO}}": _hero_html(bundle, away, home),
            "{{WINPROB}}": _win_probability_svg(bundle, away, home),
            "{{DUEL}}": _duel_html(bundle, away, home),
            "{{MOMENTUM}}": _momentum_html(bundle, away, home),
            "{{PLAYERS}}": _players_html(bundle, away, home),
            "{{FOOTER}}": _footer_html(),
        },
    )


def render_postgame_report(game_id: int, out_stem: str, png_height: int = 2400) -> tuple[str, str]:
    """Write the report to `<out_stem>.html` and a 2x `<out_stem>.png`.

    `png_height` is the headless-Chrome viewport height in CSS pixels; Chrome
    screenshots the viewport rather than the full page, so it has to clear the
    whole card or the bottom sections are cut off.
    """
    html = build_postgame_report_html(game_id)

    html_path = Path(out_stem).with_suffix(".html")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html)

    png_path = render_html_to_png(
        html,
        Path(out_stem).with_suffix(".png"),
        width=CARD_WIDTH + 60,
        height=png_height,
        scale=2,
    )
    return str(html_path), str(png_path)


if __name__ == "__main__":
    game_id = resolve_game_id(2025, 1, "LSU")
    html_path, png_path = render_postgame_report(
        game_id, "src/viz/output/postgame_lsu_clemson_2025_wk1"
    )
    print(f"wrote {html_path}")
    print(f"wrote {png_path}")
