import io
import os
import smtplib
import tempfile
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv
from great_tables import GT

load_dotenv()


def send_html_report(subject: str, html_body: str, inline_images: dict[str, bytes] | None = None) -> None:
    """Send an HTML report. `inline_images` maps a Content-ID (no angle brackets)
    to PNG bytes; reference it in `html_body` as `<img src="cid:{that_id}">`.
    """
    host = os.environ["SMTP_HOST"]
    port = int(os.environ["SMTP_PORT"])
    username = os.environ["SMTP_USERNAME"]
    password = os.environ["SMTP_PASSWORD"]
    recipients = [r.strip() for r in os.environ["REPORT_RECIPIENTS"].split(",") if r.strip()]

    if not recipients:
        raise RuntimeError("REPORT_RECIPIENTS is empty in .env")

    message = MIMEMultipart("related")
    message["Subject"] = subject
    message["From"] = username
    message["To"] = ", ".join(recipients)

    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(html_body, "html"))
    message.attach(alternative)

    for cid, image_bytes in (inline_images or {}).items():
        image = MIMEImage(image_bytes)
        image.add_header("Content-ID", f"<{cid}>")
        image.add_header("Content-Disposition", "inline", filename=f"{cid}.png")
        message.attach(image)

    try:
        with smtplib.SMTP(host, port) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(message)
    except smtplib.SMTPException as e:
        raise RuntimeError(f"Failed to send report '{subject}' to {recipients}: {e}") from e


def send_gt_report(subject: str, *tables: GT) -> None:
    """Email one or more GT tables as a single rendered PNG.

    GT/HTML output must never be emailed as raw `html_body` — email clients
    don't reliably support the CSS grid/flexbox great_tables emits. This
    renders via headless Chrome first (see `src/viz/render.py`), so the result
    looks the same in the inbox as it does in a browser.
    """
    from src.viz.render import combine_gt_tables, render_html_to_png

    html_body = combine_gt_tables(*tables)
    with tempfile.TemporaryDirectory() as tmp_dir:
        png_path = render_html_to_png(html_body, Path(tmp_dir) / "report.png")
        image_bytes = png_path.read_bytes()

    send_html_report(
        subject=subject,
        html_body='<img src="cid:report" style="max-width:100%;">',
        inline_images={"report": image_bytes},
    )


def send_chart_report(subject: str, fig, dpi: int = 150) -> str:
    """Email a matplotlib figure as a single inline PNG.

    The counterpart to `send_gt_report` for the chart half of `src/viz`. A
    figure is already an image, so unlike a GT table there's no headless-Chrome
    step — it encodes straight to PNG bytes. The white facecolor is set
    explicitly because a transparent background renders as black in some mail
    clients. Returns the subject that was sent.
    """
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=dpi, facecolor="white")

    send_html_report(
        subject=subject,
        html_body='<img src="cid:chart" style="max-width:100%; display:block; margin:0 auto;">',
        inline_images={"chart": buffer.getvalue()},
    )
    return subject


def send_postgame_report(game_id: int, subject: str | None = None) -> str:
    """Email the post-game card for one game as a single inline PNG.

    Same reasoning as `send_gt_report`: the report is CSS grid plus inline SVG,
    neither of which email clients render reliably, so what goes out is the
    rendered image rather than the page. Returns the subject that was sent.
    """
    from src.data.postgame import get_game_summary
    from src.viz.postgame_report import render_postgame_report

    meta = get_game_summary(game_id).iloc[0]
    subject = subject or (
        f"Post-Game Report — {meta['away_team']} {meta['away_points']}, "
        f"{meta['home_team']} {meta['home_points']} ({meta['season']} Week {meta['week']})"
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        _, png_path = render_postgame_report(game_id, str(Path(tmp_dir) / "postgame"))
        image_bytes = Path(png_path).read_bytes()

    send_html_report(
        subject=subject,
        # The card is designed against its own dark background, so it sits on a
        # white plate rather than inheriting whatever the client's body color is.
        html_body=(
            '<div style="background:#ffffff; padding:14px;">'
            '<img src="cid:postgame" style="max-width:100%; display:block; margin:0 auto;">'
            "</div>"
        ),
        inline_images={"postgame": image_bytes},
    )
    return subject


if __name__ == "__main__":
    import sys

    from src.viz.top_offenses import top_offenses_table

    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
    table = top_offenses_table(year)
    send_gt_report(f"Top FBS Offenses — {year}", table)
    print(f"Sent top offenses report for {year}")
