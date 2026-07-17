import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from great_tables import GT

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

MIME_TYPES = {
    ".png": "image/png",
    ".html": "text/html",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _drive_client():
    key_path = os.environ["GOOGLE_SERVICE_ACCOUNT_KEY_PATH"]
    if not Path(key_path).exists():
        raise RuntimeError(
            f"GOOGLE_SERVICE_ACCOUNT_KEY_PATH ({key_path}) doesn't exist. "
            "See the Google Drive setup steps in .env.example."
        )
    credentials = service_account.Credentials.from_service_account_file(key_path, scopes=SCOPES)
    return build("drive", "v3", credentials=credentials)


def upload_file_to_drive(file_path: str | Path, folder_id: str | None = None) -> str:
    """Upload a file to a Google Drive folder, returning its shareable link.

    `folder_id` defaults to `GOOGLE_DRIVE_FOLDER_ID` from `.env`. The target
    folder must be shared with the service account's email (see
    `.env.example`) with at least Editor/Content Manager access — a service
    account can't upload into a folder it can't see.
    """
    file_path = Path(file_path)
    folder_id = folder_id or os.environ["GOOGLE_DRIVE_FOLDER_ID"]
    mime_type = MIME_TYPES.get(file_path.suffix.lower(), "application/octet-stream")

    service = _drive_client()
    file_metadata = {"name": file_path.name, "parents": [folder_id]}
    media = MediaFileUpload(str(file_path), mimetype=mime_type)
    uploaded = service.files().create(body=file_metadata, media_body=media, fields="id, webViewLink").execute()
    return uploaded["webViewLink"]


def upload_gt_report_to_drive(filename: str, *tables: GT, folder_id: str | None = None) -> str:
    """Render one or more GT tables to a single PNG (same rendering path as
    `send_gt_report`) and upload it to Drive, returning the shareable link."""
    from src.viz.render import combine_gt_tables, render_html_to_png

    html_body = combine_gt_tables(*tables)
    with tempfile.TemporaryDirectory() as tmp_dir:
        png_path = render_html_to_png(html_body, Path(tmp_dir) / filename)
        return upload_file_to_drive(png_path, folder_id=folder_id)
