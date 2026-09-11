import json
from pathlib import Path

import cfbd
import pandas as pd
import requests

from src.data.cache import cached_dataframe
from src.data.client import get_client

LOGO_DIR = Path(__file__).parent / "logos"
PLAYER_PHOTO_DIR = Path(__file__).parent / "player_photos"
ROSTER_DIR = Path(__file__).parent / "rosters"


def get_teams(year: int, conference: str | None = None, classification: str | None = None) -> pd.DataFrame:
    """Team metadata for a season. `classification` filters to one level
    (e.g. "fbs") — CFBD's response spans FBS/FCS/II/III, most of which has no
    roster/advanced-stats/ratings coverage, so anything building a team
    picker should pass `classification="fbs"`. The underlying `get_teams`
    endpoint doesn't take a classification filter itself, so this fetches
    unfiltered (cached once per year/conference, same as before) and filters
    locally — cheap since the field is just an extra column."""

    def fetch() -> pd.DataFrame:
        with get_client() as client:
            teams = cfbd.TeamsApi(client).get_teams(year=year, conference=conference)
        return pd.DataFrame(
            [
                {
                    "id": t.id,
                    "school": t.school,
                    "conference": t.conference,
                    "classification": t.classification,
                    "color": t.color,
                    "alt_color": t.alternate_color,
                    "logo": t.logos[0].replace("http://", "https://") if t.logos else None,
                }
                for t in teams
            ]
        )

    cache_key = f"teams_{year}" + (f"_{conference}" if conference else "")
    df = cached_dataframe(cache_key, fetch)
    if classification:
        df = df[df["classification"] == classification].reset_index(drop=True)
    return df


def _download_cached(url: str, dest_dir: Path, filename: str) -> Path:
    """Download `url` to `dest_dir/filename` unless it's already there,
    returning the local path either way — the shared body of every
    "download and cache an image" helper in this module."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    if not dest.exists():
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        dest.write_bytes(response.content)
    return dest


def download_logo(team_id: int, logo_url: str, variant: str = "") -> Path:
    """Download and cache a team's logo locally, returning the local path.

    `variant` is appended to the cached filename so a team can hold more than
    one mark on disk — CFBD serves both a standard logo and a `logos-dark`
    version lightened for dark backgrounds, and they must not overwrite each
    other."""
    return _download_cached(logo_url, LOGO_DIR, f"{team_id}{variant}.png")


def download_player_photo(photo_url: str) -> Path:
    """Download and cache a player headshot locally, keyed by the id already
    embedded in its own URL (e.g. ".../players/full/5150424.png" caches as
    "5150424.png") — same pattern as `download_logo`, for photos sourced from
    a team's roster page rather than CFBD (which has no headshot endpoint of
    its own, so there's no `player_id` parameter to keep in sync with a
    CFBD id the way `download_logo`'s `team_id` does)."""
    return _download_cached(photo_url, PLAYER_PHOTO_DIR, photo_url.rstrip("/").rsplit("/", 1)[-1])


def roster_slug(team: str, year: int) -> str:
    """The `src/data/rosters/{slug}.json` filename stem for `team`/`year`
    (e.g. "Notre Dame", 2026 -> "notre_dame_2026") — same slugging convention
    as `team_profile.py`'s `_slug` (lowercase, spaces to underscores, "&" to
    "and"), kept here since this module owns the roster-file convention."""
    return f"{team.lower().replace(' ', '_').replace('&', 'and')}_{year}"


def has_roster(slug: str) -> bool:
    """Whether a hand-curated roster file exists for `slug` — lets a caller
    (e.g. the field-viewer app) warn once that no roster is on file for a
    team/year, rather than only inferring it player-by-player from every
    play falling back to a bare jersey number."""
    return (ROSTER_DIR / f"{slug}.json").exists()


def load_roster_lookup(slug: str, download_photos: bool = True) -> dict[int, dict]:
    """Jersey number -> {"name", "position", "photo_path"} for `slug`
    (e.g. "notre_dame_2026", see `roster_slug`), read from
    `src/data/rosters/{slug}.json`.

    CFBD has no headshot endpoint and no reliable way to attribute a jersey
    number to a full name/position from play-by-play alone, so this file is
    curated by hand from a team's own roster page (see any file in
    `src/data/rosters/` for the shape) rather than fetched live — there is no
    "auto-updating" version of this for a reason: scraping a specific
    roster page's HTML at request time in a deployed app is fragile (the
    markup can change) and isn't something to depend on silently breaking.
    When a new game surfaces a jersey number that isn't in the file yet, add
    it by hand (name/position/photo URL from the team's roster page) —
    everything that reads this lookup already treats a missing number as
    "fall back to what the play-by-play itself has" rather than failing.

    A jersey number is returned even if its roster entry has no
    `photo_url` (or `download_photos=False` skips fetching one) — omit
    `"photo_path"` from that entry rather than raising, since a caller may
    only need the name/position."""
    path = ROSTER_DIR / f"{slug}.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    lookup = {int(number): dict(info) for number, info in raw.items()}
    if download_photos:
        for info in lookup.values():
            if info.get("photo_url"):
                info["photo_path"] = download_player_photo(info["photo_url"])
    return lookup
