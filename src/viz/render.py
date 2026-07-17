import shutil
import subprocess
from pathlib import Path

from great_tables import GT
from PIL import Image, ImageChops

# Headless-Chrome binary candidates, checked in order.
_CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "chromium-browser",
    "chromium",
]


def _find_chrome() -> str:
    for candidate in _CHROME_CANDIDATES:
        if Path(candidate).exists() or shutil.which(candidate):
            return candidate
    raise RuntimeError(
        "No Chrome/Chromium binary found for HTML rendering. Install Google Chrome, "
        "or add its path to _CHROME_CANDIDATES in src/viz/render.py."
    )


def combine_gt_tables(*tables: GT, gap_px: int = 32) -> str:
    """Stack GT tables into one standalone HTML page for combined
    export/rendering. Sized to content (never a fixed max-width narrower than
    the widest table — that clips columns instead of wrapping them) with
    horizontal scroll as a fallback for anything still too wide for the
    viewport it's rendered in.
    """
    sections = "".join(
        f'<div style="margin-bottom: {gap_px}px; overflow-x: auto;">{t.as_raw_html()}</div>' for t in tables
    )
    return f"""
    <div style="width: fit-content; max-width: 100%; margin: 0 auto; font-family: Helvetica, Arial, sans-serif;">
        {sections}
    </div>
    """


def render_html_to_png(
    html: str,
    out_path: str | Path,
    width: int = 1600,
    height: int = 1600,
    crop: bool = True,
) -> Path:
    """Render an HTML string to a PNG via headless Chrome.

    Use this for any GT-table or dashboard output that will be emailed — email
    clients (Gmail, Outlook, ...) don't reliably support the CSS grid/flexbox
    great_tables emits, so raw GT HTML must never be sent directly as an email
    body. See the `viz-style` skill.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    html_path = out_path.with_suffix(".tmp.html")
    html_path.write_text(html)

    try:
        subprocess.run(
            [
                _find_chrome(),
                "--headless",
                "--disable-gpu",
                f"--screenshot={out_path}",
                f"--window-size={width},{height}",
                f"file://{html_path.resolve()}",
            ],
            check=True,
            capture_output=True,
        )
    finally:
        html_path.unlink()

    if crop:
        _autocrop(out_path)
    return out_path


def _autocrop(path: Path, padding: int = 20) -> None:
    """Trim surrounding whitespace down to the rendered content, since the
    screenshot viewport is almost always taller/wider than the actual table."""
    img = Image.open(path).convert("RGB")
    bg = Image.new("RGB", img.size, (255, 255, 255))
    bbox = ImageChops.difference(img, bg).getbbox()
    if bbox is None:
        return
    padded = (
        max(0, bbox[0] - padding),
        max(0, bbox[1] - padding),
        min(img.size[0], bbox[2] + padding),
        min(img.size[1], bbox[3] + padding),
    )
    img.crop(padded).save(path)
