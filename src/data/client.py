import os

import cfbd
from dotenv import load_dotenv

load_dotenv()


def get_client() -> cfbd.ApiClient:
    api_key = os.environ.get("CFBD_API_KEY")
    if not api_key:
        raise RuntimeError(
            "CFBD_API_KEY is not set. Copy .env.example to .env and fill it in "
            "(get a key at https://collegefootballdata.com/key)."
        )
    configuration = cfbd.Configuration(access_token=api_key)
    return cfbd.ApiClient(configuration)
