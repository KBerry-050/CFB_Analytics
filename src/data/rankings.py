import cfbd
import pandas as pd

from src.data.cache import cached_dataframe
from src.data.client import get_client


def get_poll_rankings(
    year: int, week: int, poll: str = "AP Top 25", season_type: str = "regular"
) -> pd.DataFrame:
    """One specific week's rankings for `poll` — week 1 of a regular season is
    the preseason poll, the one teams carried into their opener.

    Columns: rank, school, conference, firstPlaceVotes, points. Ties share a
    rank and skip the next one (two teams at 14, no 15); that's the poll's own
    numbering and is left as-is rather than renumbered.
    """

    def fetch() -> pd.DataFrame:
        with get_client() as client:
            weeks = cfbd.RankingsApi(client).get_rankings(
                year=year, week=week, season_type=season_type
            )
        for entry in weeks:
            ranked_poll = next((p for p in entry.polls if p.poll == poll), None)
            if ranked_poll:
                return pd.json_normalize([r.to_dict() for r in ranked_poll.ranks])
        raise RuntimeError(f"No '{poll}' poll found for {year} {season_type} week {week}")

    slug = poll.lower().replace(" ", "_")
    return cached_dataframe(f"poll_{slug}_{year}_{season_type}_wk{week}", fetch)


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
