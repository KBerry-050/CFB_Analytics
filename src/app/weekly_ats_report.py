"""Weekly ATS report: the two `ats_vs_ap_rank` charts (AP-rank order, and
performance-ranked with no x axis) for the most recently completed week,
emailed out. Meant to run every Monday morning for the weekend just played —
see `.claude/skills/weekly-automation/SKILL.md` for the installed schedule.

Idempotent by design (see that skill's "Running it" section), per chart: a
rerun for a week already fully sent is a no-op unless `--force` is passed, so
a missed-then-caught-up launchd job or an accidental double-run doesn't spam
duplicate emails — and if only one of the two charts made it out (a data
delay, a send failure), a rerun resends just the missing one, not both.
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from src.app.send_report import send_html_report
from src.data.games import current_week
from src.viz.ats_vs_ap_rank import ats_margin_ranked_chart, ats_vs_ap_rank_scatter
from src.viz.style import add_turf_frame

LAST_SENT_MARKER = Path("src/data/output/ats_report_last_sent.json")

CHART_BUILDERS = [
    ("AP Rank vs. Performance Against the Spread", ats_vs_ap_rank_scatter),
    ("Performance Against the Spread", ats_margin_ranked_chart),
]


def _sent_titles(year: int, week: int, season_type: str) -> set[str]:
    """Which of this week's charts already went out — empty for a week never
    attempted before, and also empty (not stale) if the marker is left over
    from a *different* week, since a new week always starts fresh."""
    if not LAST_SENT_MARKER.exists():
        return set()
    marker = json.loads(LAST_SENT_MARKER.read_text())
    if (marker.get("year"), marker.get("week"), marker.get("season_type")) != (year, week, season_type):
        return set()
    return set(marker.get("sent_titles", []))


def _save_sent_titles(year: int, week: int, season_type: str, sent_titles: set[str]) -> None:
    LAST_SENT_MARKER.parent.mkdir(parents=True, exist_ok=True)
    LAST_SENT_MARKER.write_text(
        json.dumps({"year": year, "week": week, "season_type": season_type, "sent_titles": sorted(sent_titles)})
    )


def send_weekly_ats_reports(year: int | None = None, force: bool = False) -> None:
    year = year or pd.Timestamp.now().year
    week, season_type = current_week(year)

    sent_titles = set() if force else _sent_titles(year, week, season_type)
    if not force and sent_titles.issuperset(title for title, _ in CHART_BUILDERS):
        print(f"Already sent for {year} {season_type} week {week} — skipping (use --force to resend).")
        return

    for title, build_chart in CHART_BUILDERS:
        if title in sent_titles:
            continue
        subject = f"{title} - CFB {year} Week {week}"
        try:
            fig = build_chart(year, week, season_type=season_type)
        except (ValueError, RuntimeError) as e:
            # No poll release or no closing lines yet for this week — not an
            # error worth failing the whole run over, just nothing to send.
            print(f"Skipped '{subject}': {e}", file=sys.stderr)
            continue

        # No try/except here: send_html_report only raises for things worth
        # crashing loud over (bad SMTP config, empty REPORT_RECIPIENTS, a
        # missing env var) — swallowing those as a "failure" would print the
        # same message a transient network blip would and get silently
        # retried forever instead of surfacing the real problem.
        send_html_report(
            subject,
            '<img src="cid:chart" style="max-width:100%; display:block; margin:0 auto;">',
            {"chart": add_turf_frame(fig)},
        )
        print(f"Sent: {subject}")
        # Saved after each send (not once at the end) so a later chart's
        # failure — or the process dying outright — doesn't cost a resend of
        # the ones that already went out on the next attempt.
        sent_titles.add(title)
        _save_sent_titles(year, week, season_type, sent_titles)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--force", action="store_true", help="resend even if this week was already sent")
    args = parser.parse_args()
    send_weekly_ats_reports(year=args.year, force=args.force)
