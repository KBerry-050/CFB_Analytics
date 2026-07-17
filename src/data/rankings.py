import cfbd
import pandas as pd

from src.data.cache import cached_dataframe
from src.data.client import get_client


def get_final_poll(year: int, poll: str = "AP Top 25") -> pd.DataFrame:
    """A season's final rankings for `poll` — the postseason (post-bowl) week
    if the poll ran one, otherwise its last regular-season week.
    Columns: rank, teamId, school, conference, firstPlaceVotes, points.
    """

    def fetch() -> pd.DataFrame:
        with get_client() as client:
            weeks = cfbd.RankingsApi(client).get_rankings(year=year)

        postseason = [w for w in weeks if w.season_type == cfbd.SeasonType.POSTSEASON]
        regular = sorted((w for w in weeks if w.season_type == cfbd.SeasonType.REGULAR), key=lambda w: w.week)
        for week in postseason + regular[::-1]:
            ranked_poll = next((p for p in week.polls if p.poll == poll), None)
            if ranked_poll:
                return pd.json_normalize([r.to_dict() for r in ranked_poll.ranks])

        raise RuntimeError(f"No '{poll}' poll found for {year}")

    return cached_dataframe(f"final_poll_{poll.lower().replace(' ', '_')}_{year}", fetch)
