from pathlib import Path

import pandas as pd

MAX_SHEET_NAME_LEN = 31  # Excel hard limit


def _strip_tz(df: pd.DataFrame) -> pd.DataFrame:
    """Excel can't hold timezone-aware datetimes; drop the tz (values are UTC)."""
    df = df.copy()
    for col in df.select_dtypes(include=["datetimetz"]).columns:
        df[col] = df[col].dt.tz_localize(None)
    return df


def export_profile_to_excel(profile: dict[str, pd.DataFrame], path: str | Path) -> Path:
    """Write a team-profile dict (category -> DataFrame) to one .xlsx workbook,
    one sheet per category, for ad hoc browsing outside of pandas/notebooks."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
        for category, df in profile.items():
            sheet_name = category[:MAX_SHEET_NAME_LEN]
            df = _strip_tz(df)
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            worksheet = writer.sheets[sheet_name]
            for i, col in enumerate(df.columns):
                width = min(max(len(str(col)), df[col].astype(str).str.len().max() if len(df) else 0) + 2, 60)
                worksheet.set_column(i, i, width)

    return path
