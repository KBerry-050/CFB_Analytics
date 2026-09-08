"""QB Pass Chart — an interactive (not static-image) per-game pass chart:
a vertical football field with yard markings, where each of a QB's throws
animates in as a green completion line (labeled by receiver, gold star if a
touchdown) or a red/amber miss marker. A dropdown selects the game; down
(1st-4th) fills in for the field's lateral axis since CFBD has no real hash
position. Works for any passer/team/year
(`render_qb_pass_chart(player_name, team, year, out_path)`); Notre Dame's
C.J. Carr (2025) was the pilot case, first prototyped as a Claude Artifact.

Unlike the rest of src/viz/ (great_tables + matplotlib, rendered to PNG for
email), this produces a standalone interactive HTML file — open it directly
in a browser, or publish it as an Artifact. There's no PNG/email path for it.
"""

import json
from pathlib import Path

import pandas as pd

from src.data.team_profile import get_qb_pass_chart_data
from src.viz.render import render_template

TEMPLATE_PATH = Path(__file__).parent / "qb_pass_chart_template.html"


def build_qb_pass_chart_html(player_name: str, team: str, year: int) -> str:
    """Render the pass-chart HTML for one QB season, data and all, as a
    self-contained string (no external files/scripts required to view it)."""
    df = get_qb_pass_chart_data(player_name, team, year)
    plays = df.where(pd.notnull(df), None).to_dict(orient="records")

    return render_template(
        TEMPLATE_PATH,
        {
            "{{PLAYER}}": player_name,
            "{{TEAM}}": team,
            "{{YEAR}}": str(year),
            "{{DATA}}": json.dumps(plays),
        },
    )


def render_qb_pass_chart(player_name: str, team: str, year: int, out_path: str) -> str:
    """Build the pass chart and write it to `out_path`. Returns the path."""
    html = build_qb_pass_chart_html(player_name, team, year)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    return str(out_path)


if __name__ == "__main__":
    path = render_qb_pass_chart("C.J. Carr", "Notre Dame", 2025, "src/viz/output/carr_pass_chart.html")
    print(f"wrote {path}")
