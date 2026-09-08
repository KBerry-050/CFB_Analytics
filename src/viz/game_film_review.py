"""Build a self-contained HTML review artifact for one game's video/play-by-play
sync (see game_film.py's `build_video_play_sync` and its output CSV shape).

The OCR sync pipeline is probabilistic — clock reads can be off by a digit,
and `match_windows_to_plays` always returns its *closest* guess even when
that guess is wrong (see its docstring). This module doesn't change the sync
math; it renders each matched window next to the actual video frame the
reading came from, so a human can eyeball whether the OCR/match was right
without scrubbing the source video by hand.

Deterministic and reusable: given the same play_sync data + frame cache
directory + fps, `build_review_html` always emits byte-identical HTML (no
wall-clock timestamps, no random IDs). Re-run it for any week by pointing it
at that week's data/cache/fps; nothing here is hardcoded to one game.
"""

import argparse
import base64
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from src.data.scoreboard_ocr import frame_index_for_timestamp
from src.viz.render import render_template

TEMPLATE_PATH = Path(__file__).parent / "game_film_review_template.html"

# Below this, treat the OCR/match as trustworthy without a second look.
GOOD_GAP_SECONDS = 5.0
# Above GOOD, below/at this, worth a glance. Above this, flagged for review.
WARN_GAP_SECONDS = 10.0

_ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}

# A flat placeholder (no PIL dependency) shown when a window's timestamp falls
# outside the extracted frame cache — e.g. the cache only covers a slice of
# the video, or fps/start_seconds passed here doesn't match how it was
# extracted (see extract_frames() in scoreboard_ocr.py).
_MISSING_FRAME_DATA_URI = (
    "data:image/svg+xml;base64,"
    + base64.b64encode(
        b'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360">'
        b'<rect width="640" height="360" fill="#171c26"/>'
        b'<text x="320" y="180" fill="#5b6478" font-family="monospace" '
        b'font-size="20" text-anchor="middle">frame not in cache</text></svg>'
    ).decode()
)


def _frame_path(seconds: float, frame_cache_dir: Path, fps: float, start_seconds: float) -> Path:
    index = frame_index_for_timestamp(seconds, fps, start_seconds)
    return frame_cache_dir / f"frame_{index:06d}.jpg"


def _encode_frame(path: Path) -> str:
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return _MISSING_FRAME_DATA_URI
    return f"data:image/jpeg;base64,{base64.b64encode(data).decode()}"


def _mmss(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


def _severity(gap_seconds: float | None) -> str:
    if gap_seconds is None:
        return "unmatched"
    if gap_seconds <= GOOD_GAP_SECONDS:
        return "good"
    if gap_seconds <= WARN_GAP_SECONDS:
        return "warn"
    return "critical"


def _play_label(row: pd.Series) -> str:
    if pd.isna(row["matched_play_id"]):
        return "No matching play found"
    return f"{row['matched_athlete']} — {row['matched_stat_type']}"


def _down_distance_label(row: pd.Series) -> str | None:
    if pd.isna(row["matched_down"]):
        return None
    down = _ORDINALS.get(int(row["matched_down"]), f"{int(row['matched_down'])}th")
    return f"{down} & {int(row['matched_distance'])}"


def _card_skeleton(row: pd.Series, frame_cache_dir: Path, fps: float, start_seconds: float) -> dict:
    """A card's fields, with each frame holding a resolved (not yet encoded)
    Path — encoding happens once per unique path afterward, since a window's
    start/end can round to the same frame file."""
    start, end = float(row["window_start_seconds"]), float(row["window_end_seconds"])
    frame_specs = [("first reading", start)]
    if end != start:
        frame_specs.append(("last reading", end))
    frames = [
        {"label": label, "seconds": seconds, "path": _frame_path(seconds, frame_cache_dir, fps, start_seconds)}
        for label, seconds in frame_specs
    ]

    gap = None if pd.isna(row["match_gap_seconds"]) else float(row["match_gap_seconds"])
    return {
        "quarter": f"Q{int(row['period'])}",
        "clock": f"{int(row['clock_minutes'])}:{int(row['clock_seconds']):02d}",
        "videoStart": _mmss(start),
        "videoEnd": _mmss(end) if end != start else None,
        "nReadings": int(row["n_readings"]),
        "playLabel": _play_label(row),
        "downDistance": _down_distance_label(row),
        "playId": None if pd.isna(row["matched_play_id"]) else str(int(row["matched_play_id"])),
        "gapLabel": "no match" if gap is None else f"{gap:g}s",
        "severity": _severity(gap),
        "frames": frames,
    }


def build_review_html(
    play_sync: pd.DataFrame,
    frame_cache_dir: str,
    out_path: str,
    fps: float = 1.0,
    start_seconds: float = 0.0,
    game_label: str = "",
) -> Path:
    """Render `play_sync` (a DataFrame shaped like game_film.py's
    `build_video_play_sync` output) into a standalone HTML page pairing each
    matched window with its source video frame(s), for visual QA.

    `fps`/`start_seconds` must match the values passed to `extract_frames`
    (or `build_video_play_sync`) when the frame cache at `frame_cache_dir`
    was built — otherwise frame lookups silently land on the wrong frame's
    timestamp. If the cache has a `_meta.json` sidecar (written by
    `extract_frames` since it started recording this), a mismatch raises
    immediately instead of quietly mis-rendering every card; older caches
    without one render with an on-page warning instead, since there's
    nothing to verify against.
    """
    df = play_sync.sort_values("window_start_seconds").reset_index(drop=True)
    cache_dir = Path(frame_cache_dir)

    meta_path = cache_dir / "_meta.json"
    cache_verified = False
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if meta.get("fps") != fps or meta.get("start_seconds") != start_seconds:
            raise ValueError(
                f"fps/start_seconds mismatch: {meta_path} says this cache was extracted with "
                f"fps={meta.get('fps')}, start_seconds={meta.get('start_seconds')}, but "
                f"build_review_html was called with fps={fps}, start_seconds={start_seconds}. "
                "Every frame lookup below would silently point at the wrong timestamp."
            )
        cache_verified = True

    cards = [_card_skeleton(row, cache_dir, fps, start_seconds) for _, row in df.iterrows()]

    unique_paths = sorted({f["path"] for c in cards for f in c["frames"]}, key=str)
    with ThreadPoolExecutor(max_workers=8) as pool:
        encoded = dict(zip(unique_paths, pool.map(_encode_frame, unique_paths)))
    for card in cards:
        for frame in card["frames"]:
            frame["src"] = encoded[frame.pop("path")]

    matched_gaps = df["match_gap_seconds"].dropna().tolist()
    summary = {
        "total": len(cards),
        "unmatched": sum(1 for c in cards if c["severity"] == "unmatched"),
        "needsReview": sum(1 for c in cards if c["severity"] in ("warn", "critical")),
        "avgGap": round(sum(matched_gaps) / len(matched_gaps), 1) if matched_gaps else None,
        "cacheVerified": cache_verified,
    }

    payload = {"gameLabel": game_label, "summary": summary, "cards": cards}
    html = render_template(
        TEMPLATE_PATH,
        {
            "__GAME_LABEL__": game_label or "Game Film Sync Review",
            "__REVIEW_DATA_JSON__": json.dumps(payload, sort_keys=True),
        },
    )

    out = Path(out_path)
    out.write_text(html)
    return out


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--play-sync-csv", required=True)
    parser.add_argument("--frame-cache-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--fps", type=float, default=1.0)
    parser.add_argument("--start-seconds", type=float, default=0.0)
    parser.add_argument("--game-label", default="")
    args = parser.parse_args()

    out = build_review_html(
        pd.read_csv(args.play_sync_csv),
        args.frame_cache_dir,
        args.out,
        fps=args.fps,
        start_seconds=args.start_seconds,
        game_label=args.game_label,
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    _main()
