"""Interactive field diagram for one game's offensive plays — a line from
each play's starting to ending field position, with the ball-carrier's
headshot, filterable by quarter and player.

Parameterized by team/year/week (not hardcoded to one game) so it generalizes
to any future Notre Dame game — or any team with a roster file in
`src/data/rosters/`, see `load_roster_lookup`'s docstring for that convention.
Tested against the 2026 week 1 Wisconsin game, which is why that's the
default.

Local-only: `streamlit run src/app/game_field_viewer.py`.
"""

import sys
from pathlib import Path

# `streamlit run` only puts this file's own directory on sys.path, not the
# project root — see webapp.py for the same fix.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from src.data.postgame import get_game_result, get_offensive_plays_with_field_position, resolve_game_id
from src.data.teams import has_roster, load_roster_lookup, roster_slug
from src.viz.field_plot import build_field_figure

st.set_page_config(page_title="CFB Analytics — Field Viewer", layout="wide")

CACHE_TTL = 3600


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _game_id(team: str, year: int, week: int) -> int:
    return resolve_game_id(year, week, team)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _result(team: str, game_id: int) -> dict:
    return get_game_result(team, game_id)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _plays(team: str, year: int, week: int, game_id: int):
    return get_offensive_plays_with_field_position(game_id, year, week, team)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _roster(team: str, year: int) -> dict[int, dict]:
    return load_roster_lookup(roster_slug(team, year))


@st.cache_resource(show_spinner=False)
def _image_cache() -> dict:
    """Persists decoded player-photo arrays across Streamlit reruns — a
    filter change rebuilds the whole figure, and without this the same
    handful of headshots would be re-decoded from disk on every toggle."""
    return {}


def _player_label(jersey_number: int, player_text: str, roster_lookup: dict[int, dict]) -> str:
    name = roster_lookup.get(jersey_number, {}).get("name", player_text)
    return f"#{jersey_number} {name}"


st.title("Offensive Play Field Viewer")

with st.sidebar:
    st.header("Game")
    team = st.text_input("Team", value="Notre Dame")
    year = st.number_input("Season", min_value=2015, max_value=2030, value=2026, step=1)
    week = st.number_input("Week", min_value=1, max_value=20, value=1, step=1)

try:
    game_id = _game_id(team, int(year), int(week))
except ValueError as e:
    st.error(str(e))
    st.stop()

result = _result(team, game_id)
plays = _plays(team, int(year), int(week), game_id)
slug = roster_slug(team, int(year))
if not has_roster(slug):
    st.info(f"No roster file for {team} {int(year)} yet ({slug}.json) — showing jersey numbers only, no names/photos.")
roster_lookup = _roster(team, int(year))

if plays.attrs.get("unparsed_count"):
    st.caption(f"Note: {plays.attrs['unparsed_count']} offensive play(s) had unparseable play text and are left out below.")

if plays.empty:
    st.warning("No offensive plays with recoverable field position for this game.")
    st.stop()

quarters = sorted(plays["period"].unique())
pairs = plays[["jersey_number", "player_text"]].drop_duplicates().sort_values("jersey_number")
label_to_jersey = {_player_label(j, t, roster_lookup): j for j, t in pairs.itertuples(index=False)}

with st.sidebar:
    st.header("Filters")
    selected_quarters = st.multiselect("Quarter", quarters, default=quarters)
    selected_labels = st.multiselect("Player", list(label_to_jersey), default=list(label_to_jersey))

selected_jerseys = {label_to_jersey[label] for label in selected_labels}
filtered = plays[plays["period"].isin(selected_quarters) & plays["jersey_number"].isin(selected_jerseys)]

title = f"{team} vs. {result['opponent']}"
subtitle = f"{int(year)} Week {int(week)}  ({result['team_points']:.0f}-{result['opp_points']:.0f})  •  {len(filtered)} offensive play(s)"
fig = build_field_figure(filtered, roster_lookup, title, subtitle, image_cache=_image_cache())
st.pyplot(fig)
