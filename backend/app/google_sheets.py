import json
import os
from pathlib import Path

import gspread
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly", "https://www.googleapis.com/auth/drive.readonly"]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
SECRETS_ROOT = BACKEND_ROOT / "secrets"


def credentials() -> Credentials:
    token_path = Path(os.getenv("GOOGLE_TOKEN_FILE", SECRETS_ROOT / "token.json"))
    source_path = Path(os.getenv("GOOGLE_CREDENTIALS_FILE", SECRETS_ROOT / "credentials.json"))
    creds = None
    for path in (token_path, source_path):
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if "refresh_token" in data and "client_id" in data:
            # Preserve the scopes originally granted to this refresh token.
            # Asking Google to replace them during refresh causes invalid_scope.
            creds = Credentials.from_authorized_user_info(data)
            break
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds:
        data = json.loads(source_path.read_text(encoding="utf-8-sig")) if source_path.exists() else {}
        if "installed" not in data and "web" not in data:
            raise RuntimeError("credentials.json ne contient ni jeton autorisé ni client OAuth Google.")
        flow = InstalledAppFlow.from_client_secrets_file(str(source_path), SCOPES)
        creds = flow.run_local_server(port=0)
    if not creds.valid:
        raise RuntimeError("Les identifiants Google ne sont plus valides.")
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def client() -> gspread.Client:
    return gspread.authorize(credentials())


def spreadsheet_id(value: str) -> str:
    if "/d/" in value:
        return value.split("/d/", 1)[1].split("/", 1)[0]
    return value.strip()


def list_spreadsheets() -> list[dict]:
    files = client().list_spreadsheet_files()
    return [{"id": item["id"], "name": item.get("name", "Sans titre"), "url": f"https://docs.google.com/spreadsheets/d/{item['id']}"} for item in files]


def workbook_metadata(value: str) -> dict:
    book = client().open_by_key(spreadsheet_id(value))
    sheets = [{"title": tab.title, "sheet_id": tab.id, "rows": tab.row_count, "columns": tab.col_count} for tab in book.worksheets()]
    return {"id": book.id, "name": book.title, "url": book.url, "sheets": sheets}


def read_tab(value: str, sheet_name: str, limit: int = 100) -> dict:
    book = client().open_by_key(spreadsheet_id(value))
    tab = book.worksheet(sheet_name)
    values = tab.get(f"A1:{gspread.utils.rowcol_to_a1(min(tab.row_count, limit + 1), min(tab.col_count, 80))}")
    headers = values[0] if values else []
    rows = []
    for raw in values[1:limit + 1]:
        padded = raw + [""] * (len(headers) - len(raw))
        rows.append(dict(zip(headers, padded)))
    return {"spreadsheet_id": book.id, "spreadsheet_name": book.title, "sheet_name": tab.title, "headers": headers, "rows": rows, "total_rows": max(0, len(tab.get_all_values()) - 1)}
