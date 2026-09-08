"""Automatic scoreboard-clock detection from game film, via Apple's Vision
framework (macOS only — this is the same OCR engine behind Live Text in
Preview/Photos).

Why Vision and not Tesseract: both were tested on this project's actual
broadcast scoreboard font. Tesseract consistently misread the clock digits
(e.g. "15:00" read as "75:00", then "45:00" after trying upscaling, contrast
adjustment, color inversion, and a digit-only whitelist — the "1" glyph in
this font kept getting confused for other digits). Vision read the same crop
correctly on the first attempt and reliably isolates the clock into its own
high-confidence text block, separate from the noisier team-name/down-distance
text around it — see the "KEY TAKEAWAYS" instructions embedded nowhere; this
is simply the empirical result of testing both.

The scoreboard graphic in this film shows the *live, ticking* game clock for
several seconds before each snap (confirmed: consecutive one-second frame
samples read 14:12 -> 14:11 -> 14:10). That means every successfully-OCR'd
frame is already an exact (video_timestamp, game_clock) pair — no
interpolation needed for frames where the graphic is visible. Interpolation
(see game_film.py's estimate_game_clock) is only for anchors placed by hand
when no on-screen clock is available at all.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pandas as pd

CLOCK_PATTERN = re.compile(r"\b(\d{1,2}):(\d{2})\b")

# Normalized region-of-interest (bottom-left origin, Vision's convention) covering the
# scoreboard bar. Generous on purpose — the bar's exact vertical position shifts a few
# percent between camera angles/zooms (confirmed two different pixel offsets across two
# sampled shots in the same broadcast), so a tight/exact crop would miss it on some plays.
SCOREBOARD_ROI = (0.0, 0.40, 1.0, 0.26)  # (x, y, width, height)

MIN_CONFIDENCE = 0.9

# Empirically: game clock text sits at x=0.43 (normalized), the broadcast wall-clock
# ("7:47 PM") at x=0.76. A single upper bound isn't enough — Vision sometimes splits the
# wall-clock's "H:MM" and "PM" into separate text observations, and the bare "H:MM" piece
# can still slip under a simple "< 0.6" cutoff. Require a band around the known game-clock
# position instead of just excluding the wall-clock's, so both filters have to fail (not
# just one) for a wall-clock reading to be accepted as the game clock.
GAME_CLOCK_X_MIN = 0.30
GAME_CLOCK_X_MAX = 0.55


def _find_ffmpeg() -> str:
    for candidate in ("ffmpeg", str(Path.home() / "bin" / "ffmpeg")):
        if shutil.which(candidate) or Path(candidate).exists():
            return candidate
    raise RuntimeError("ffmpeg not found on PATH or in ~/bin — see game_film.py setup notes.")


def extract_frames(
    video_path: str, out_dir: str, fps: float = 1.0, start_seconds: float = 0.0, duration_seconds: float | None = None
) -> None:
    """Extract frames from `video_path` at `fps` frames/sec into `out_dir`,
    named frame_%06d.jpg. Frame N's video timestamp is
    start_seconds + (N - 1) / fps. `start_seconds`/`duration_seconds` let you
    pull a slice for testing rather than the whole file."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [_find_ffmpeg(), "-y"]
    if start_seconds:
        cmd += ["-ss", str(start_seconds)]
    cmd += ["-i", video_path]
    if duration_seconds is not None:
        cmd += ["-t", str(duration_seconds)]
    cmd += ["-vf", f"fps={fps}", str(out_dir / "frame_%06d.jpg")]
    subprocess.run(cmd, check=True, capture_output=True)

    # Sidecar recording the (fps, start_seconds) this directory's frames were
    # extracted at — frame_%06d.jpg filenames only encode index, not time, so
    # anything mapping a timestamp back to a frame (e.g. game_film_review.py)
    # needs this to avoid silently reading the wrong frame under a mismatched
    # fps/start_seconds guess.
    (out_dir / "_meta.json").write_text(json.dumps({"fps": fps, "start_seconds": start_seconds}))


def _frame_index_to_timestamp(frame_path: Path, fps: float, start_seconds: float = 0.0) -> float:
    index = int(frame_path.stem.split("_")[1])
    return start_seconds + (index - 1) / fps


def frame_index_for_timestamp(seconds: float, fps: float, start_seconds: float = 0.0) -> int:
    """Inverse of `_frame_index_to_timestamp`: which frame_%06d.jpg index
    holds a given video timestamp, for the same (fps, start_seconds) an
    extraction used. Public because callers outside this module (e.g.
    game_film_review.py) need to look frames up by timestamp."""
    return round((seconds - start_seconds) * fps) + 1


def ocr_clock(frame_path: str) -> tuple[int, int, float] | None:
    """Read the game clock off one frame via Vision, restricted to
    SCOREBOARD_ROI. Returns (minutes, seconds, confidence) for the
    highest-confidence clock-shaped text block found, or None."""
    import Quartz
    from Foundation import NSURL
    import Vision

    url = NSURL.fileURLWithPath_(str(frame_path))
    source = Quartz.CGImageSourceCreateWithURL(url, None)
    image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    if image is None:
        return None

    observations = []

    def handler(request, error):
        if error is None:
            observations.extend(request.results())

    request = Vision.VNRecognizeTextRequest.alloc().initWithCompletionHandler_(handler)
    request.setRecognitionLevel_(1)  # accurate, not fast
    request.setRegionOfInterest_(Quartz.CGRectMake(*SCOREBOARD_ROI))

    req_handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image, {})
    ok, _ = req_handler.performRequests_error_([request], None)
    if not ok:
        return None

    best = None
    for obs in observations:
        text = obs.text()
        confidence = obs.confidence()
        match = CLOCK_PATTERN.search(text)
        if not match or confidence < MIN_CONFIDENCE:
            continue
        if "AM" in text.upper() or "PM" in text.upper():
            continue  # the broadcast wall-clock ("7:47 PM"), not the game clock
        x = obs.boundingBox().origin.x
        if not (GAME_CLOCK_X_MIN <= x <= GAME_CLOCK_X_MAX):
            continue  # not at the known game-clock position — most likely the wall-clock's
            # bare "H:MM" with its "PM" split into a separate text block Vision didn't merge
        minutes, seconds = int(match.group(1)), int(match.group(2))
        if minutes > 20 or seconds > 59:  # filters out non-clock digit pairs (down/distance, etc.)
            continue
        if best is None or confidence > best[2]:
            best = (minutes, seconds, confidence)
    return best


def detect_clock_readings(
    video_path: str,
    cache_dir: str,
    fps: float = 1.0,
    start_seconds: float = 0.0,
    duration_seconds: float | None = None,
) -> pd.DataFrame:
    """Sweep a video (or a start_seconds/duration_seconds slice of one, for
    testing) and return every frame where the on-screen game clock was
    confidently read. Columns: video_timestamp_seconds, clock_minutes,
    clock_seconds, confidence — one row per successful read (frames where no
    scoreboard graphic is visible, e.g. during live play, simply produce no
    row; that's expected, not an error)."""
    cache_dir = Path(cache_dir)
    frame_files = sorted(cache_dir.glob("frame_*.jpg"))
    if not frame_files:
        extract_frames(video_path, str(cache_dir), fps=fps, start_seconds=start_seconds, duration_seconds=duration_seconds)
        frame_files = sorted(cache_dir.glob("frame_*.jpg"))

    rows = []
    for frame_path in frame_files:
        reading = ocr_clock(str(frame_path))
        if reading is None:
            continue
        minutes, seconds, confidence = reading
        rows.append(
            {
                "video_timestamp_seconds": _frame_index_to_timestamp(frame_path, fps, start_seconds),
                "clock_minutes": minutes,
                "clock_seconds": seconds,
                "confidence": confidence,
            }
        )
    return pd.DataFrame(rows)
