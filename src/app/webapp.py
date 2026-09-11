"""Interactive team-lookup webapp — search any FBS team and browse its
roster, schedule, and season-entering metrics, or run the matchup-analysis
tool against any other team. Local-only: `streamlit run src/app/webapp.py`.

Thin wiring layer only — every table it renders comes straight from
`src/viz` (which already applies house style and never fetches data
itself); this file just hooks up the search UI and embeds the resulting
`great_tables` HTML via `st.iframe` (auto-sized to content height).
`src/data`'s `cached_dataframe` already caches every CFBD pull to parquet, so
a team searched once loads instantly on repeat visits — the `st.cache_data`
wrapping below is an in-session layer on top of that, so switching tabs
doesn't rebuild/re-render a GT table (or re-hit the network for an
as-yet-uncached team) on every Streamlit rerun.
"""

import sys
from pathlib import Path

# `streamlit run` executes this file directly (like `python script.py`), which
# only puts this file's own directory (src/app/) on sys.path — not the
# project root — so `import src...` fails unless we add it ourselves.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from src.data.team_profile import get_team_schedule
from src.data.teams import get_teams
from src.viz.matchup_preview import matchup_preview_table
from src.viz.team_dashboard import team_metrics_table, team_roster_table, team_schedule_table

st.set_page_config(page_title="CFB Analytics", layout="wide")

CACHE_TTL = 3600


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _team_choices(year: int) -> list[str]:
    return sorted(get_teams(year, classification="fbs")["school"].tolist())


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _team_logo(year: int, team: str) -> str | None:
    teams = get_teams(year, classification="fbs")
    match = teams.loc[teams["school"] == team, "logo"]
    return match.iloc[0] if not match.empty else None


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _team_color(year: int, team: str) -> str | None:
    teams = get_teams(year, classification="fbs")
    match = teams.loc[teams["school"] == team, "color"]
    return match.iloc[0] if not match.empty else None


def _inject_field_theme() -> None:
    """Football-field chrome for the app shell: mowed-turf background with
    yard-line striping, a scoreboard-style title, yard-marker tab pills, and
    card framing for the embedded (house-styled, iframe-isolated) GT tables.
    Only the parent page's CSS changes here — an iframe's own document is a
    separate DOM, so none of this touches the tables' own styling."""
    st.markdown(
        """
        <style>
        .stApp {
            background-image:
                repeating-linear-gradient(180deg, rgba(255,255,255,0.10) 0px, rgba(255,255,255,0.10) 3px, transparent 3px, transparent 110px),
                repeating-linear-gradient(90deg, #1c5c34 0px, #1c5c34 55px, #21683c 55px, #21683c 110px);
            background-attachment: fixed;
        }
        [data-testid="stWidgetLabel"] p {
            color: #f5f0e6 !important;
            font-weight: 600;
            letter-spacing: 0.5px;
        }
        .field-scoreboard {
            background: linear-gradient(180deg, #0d1f14 0%, #142c1d 100%);
            border: 3px solid #d4af37;
            border-radius: 14px;
            padding: 20px 28px;
            margin-bottom: 20px;
            text-align: center;
            box-shadow: 0 6px 18px rgba(0,0,0,0.35);
        }
        .field-scoreboard h1 {
            color: #f5f0e6;
            font-weight: 800;
            letter-spacing: 5px;
            text-transform: uppercase;
            margin: 0;
            font-size: 2.1rem;
        }
        .field-scoreboard .subtitle {
            color: #d4af37;
            letter-spacing: 3px;
            font-size: 0.85rem;
            text-transform: uppercase;
            margin-top: 6px;
            font-weight: 600;
        }
        .team-banner {
            background: #fdfcf8;
            border-radius: 12px;
            padding: 14px 22px;
            margin: 4px 0 20px 0;
            display: flex;
            align-items: center;
            gap: 16px;
            box-shadow: 0 4px 14px rgba(0,0,0,0.25);
            border-left: 8px solid #d4af37;
        }
        .team-banner img { height: 48px; }
        .team-banner .team-name {
            font-size: 1.6rem;
            font-weight: 700;
            color: #14301f;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 6px;
            background: rgba(255,255,255,0.16);
            padding: 6px;
            border-radius: 999px;
        }
        .stTabs [data-baseweb="tab"] {
            border-radius: 999px !important;
            background: #fdfcf8;
            color: #14301f;
            font-weight: 600;
        }
        .stTabs [aria-selected="true"] {
            background: #d4af37 !important;
            color: #14301f !important;
        }
        iframe {
            border-radius: 10px;
            box-shadow: 0 4px 16px rgba(0,0,0,0.25);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _roster_html(team: str, year: int) -> str:
    return team_roster_table(team, year).as_raw_html()


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _schedule_html(team: str, year: int) -> str:
    return team_schedule_table(team, year).as_raw_html()


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _metrics_html(team: str, year: int) -> str:
    return team_metrics_table(team, year).as_raw_html()


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _matchup_html(team_a: str, team_b: str, year: int) -> str:
    return matchup_preview_table(team_a, team_b, year).as_raw_html()


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _week1_opponent(team: str, year: int) -> str | None:
    """Best-effort default opponent for the Matchup Analysis tab: `team`'s
    week 1 opponent, if that opponent is itself an FBS team in `year`'s
    picker list (an FCS week-1 tune-up game wouldn't be selectable)."""
    schedule = get_team_schedule(team, year)
    week1 = schedule[schedule["week"] == 1]
    if week1.empty:
        return None
    row = week1.iloc[0]
    opponent = row["awayTeam"] if row["homeTeam"] == team else row["homeTeam"]
    return opponent if opponent in _team_choices(year) else None


def _render(html_body: str) -> None:
    st.iframe(html_body, width="stretch", height="content")


_inject_field_theme()

st.markdown(
    '<div class="field-scoreboard"><h1>CFB Analytics</h1>'
    '<div class="subtitle">Search &bull; Compare &bull; Scout</div></div>',
    unsafe_allow_html=True,
)

year = st.number_input("Season", min_value=2015, max_value=2030, value=2026, step=1)

choices = _team_choices(year)
team = st.selectbox("Search a team", choices, index=choices.index("Notre Dame") if "Notre Dame" in choices else 0)

logo_url = _team_logo(year, team)
team_color = _team_color(year, team) or "#d4af37"
logo_html = f'<img src="{logo_url}">' if logo_url else ""
st.markdown(
    f'<div class="team-banner" style="border-left-color:{team_color};">'
    f'{logo_html}<div class="team-name">{team} — {year}</div></div>',
    unsafe_allow_html=True,
)

roster_tab, schedule_tab, metrics_tab, matchup_tab = st.tabs(["Roster", "Schedule", "Metrics", "Matchup Analysis"])

with roster_tab:
    try:
        with st.spinner(f"Loading {team} roster…"):
            _render(_roster_html(team, year))
    except Exception as e:
        st.error(f"Couldn't load roster for {team} ({year}): {e}")

with schedule_tab:
    try:
        with st.spinner(f"Loading {team} schedule…"):
            _render(_schedule_html(team, year))
    except Exception as e:
        st.error(f"Couldn't load schedule for {team} ({year}): {e}")

with metrics_tab:
    try:
        with st.spinner(f"Loading {team} metrics…"):
            _render(_metrics_html(team, year))
    except Exception as e:
        st.error(f"Couldn't load metrics for {team} ({year}): {e}")

with matchup_tab:
    default_opponent = _week1_opponent(team, year)
    other_choices = [t for t in choices if t != team]
    default_index = other_choices.index(default_opponent) if default_opponent in other_choices else 0
    # Keying on `team` gives this selectbox a fresh widget identity whenever
    # the searched team changes, so its default resets to *that* team's
    # week-1 opponent instead of sticking with whatever was last picked for
    # a different team.
    opponent = st.selectbox("Compare against", other_choices, index=default_index, key=f"matchup_opponent_{team}")

    try:
        with st.spinner(f"Building {team} vs. {opponent} matchup preview…"):
            _render(_matchup_html(team, opponent, year))
    except Exception as e:
        st.error(f"Couldn't build matchup preview for {team} vs. {opponent} ({year}): {e}")
