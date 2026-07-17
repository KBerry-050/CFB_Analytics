from pathlib import Path

import cfbd
import pandas as pd
import requests

from src.data.cache import cached_dataframe
from src.data.client import get_client

LOGO_DIR = Path(__file__).parent / "logos"


def get_teams(year: int, conference: str | None = None) -> pd.DataFrame:
    def fetch() -> pd.DataFrame:
        with get_client() as client:
            teams = cfbd.TeamsApi(client).get_teams(year=year, conference=conference)
        return pd.DataFrame(
            [
                {
                    "id": t.id,
                    "school": t.school,
                    "conference": t.conference,
                    "color": t.color,
                    "alt_color": t.alternate_color,
                    "logo": t.logos[0].replace("http://", "https://") if t.logos else None,
                }
                for t in teams
            ]
        )

    cache_key = f"teams_{year}" + (f"_{conference}" if conference else "")
    return cached_dataframe(cache_key, fetch)


def download_logo(team_id: int, logo_url: str) -> Path:
    """Download and cache a team's logo locally, returning the local path."""
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    dest = LOGO_DIR / f"{team_id}.png"
    if not dest.exists():
        response = requests.get(logo_url, timeout=10)
        response.raise_for_status()
        dest.write_bytes(response.content)
    return dest
