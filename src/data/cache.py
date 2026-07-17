from pathlib import Path
from typing import Callable

import pandas as pd

CACHE_DIR = Path(__file__).parent / "cache"


def cached_dataframe(cache_key: str, fetch_fn: Callable[[], pd.DataFrame]) -> pd.DataFrame:
    """Read cache_key.parquet from disk if present, otherwise call fetch_fn and cache the result."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{cache_key}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    df = fetch_fn()
    df.to_parquet(path)
    return df
