"""Google Sheets access. Every read/write to Sheets goes through this class."""
from datetime import date

from config import (GOOGLE_CREDENTIALS_PATH, GOOGLE_SHEETS_ID, LOG_HEADERS,
                    QUEUE_COLUMNS, QUEUE_HEADERS, TAB_HOT, TAB_LOG, TAB_QUEUE, TABS)

QUEUE_COL_INDEX = {key: i + 1 for i, (key, _) in enumerate(QUEUE_COLUMNS)}

INT_FIELDS = {"original_score", "messages_sent", "day_number"}


def _to_int(value, default=0):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def row_to_record(row: dict, row_number: int) -> dict:
    """Sheet row (header keys) → code dict (snake_case keys) + '_row' number."""
    record = {}
    for key, header in QUEUE_COLUMNS:
        value = row.get(header, "")
        record[key] = _to_int(value) if key in INT_FIELDS else str(value).strip()
    record["_row"] = row_number
    return record


class SheetsClient:
    def __init__(self, sheet_id: str = GOOGLE_SHEETS_ID,
                 creds_path: str = GOOGLE_CREDENTIALS_PATH):
        import gspread  # imported here so tests don't need Google libs

        if not sheet_id:
            raise RuntimeError("GOOGLE_SHEETS_ID is empty — set it in .env")
        self._gspread = gspread
        import config as _cfg
        if _cfg.GOOGLE_CREDENTIALS_JSON.strip():       # Render: whole JSON in an env var
            import json
            client = gspread.service_account_from_dict(json.loads(_cfg.GOOGLE_CREDENTIALS_JSON))
        else:
            client = gspread.service_account(filename=creds_path)
        self.book = client.open_by_key(sheet_id)

    # ── Setup ──────────────────────────────────────────────────
    def ensure_structure(self) -> list[str]:
        """Create the 3 tabs + header rows if missing. Never overwrites data."""
        actions = []
        existing = {ws.title: ws for ws in self.book.worksheets()}
        for title, headers in TABS:
            ws = existing.get(title)
            if ws is None:
                if "Sheet1" in existing:          # reuse the blank default tab
                    ws = existing.pop("Sheet1")
                    ws.update_title(title)
                else:
                    ws = self.book.add_worksheet(title=title, rows=1000, cols=len(headers))
                actions.append(f"created tab '{title}'")
            current = ws.row_values(1)
            if any(current) and current != headers and headers[:len(current)] == current:
                self._grow_headers(ws, headers)          # older version: add new columns
                actions.append(f"added new column(s) on '{title}'")
                continue
            if not any(current):
                ws.update(values=[headers], range_name="A1")
                ws.format("1:1", {"textFormat": {"bold": True}})
                ws.freeze(rows=1)
                actions.append(f"wrote headers on '{title}'")
            elif current[:len(headers)] != headers:
                raise RuntimeError(
                    f"Tab '{title}' has different headers than expected.\n"
                    f"  Found:    {current}\n  Expected: {headers}\n"
                    "Fix the header row manually — refusing to overwrite data.")
        return actions or ["structure already correct"]

    @staticmethod
    def _grow_headers(ws, headers):
        if ws.col_count < len(headers):
            ws.add_cols(len(headers) - ws.col_count)
        ws.update(values=[headers], range_name="A1")

    # ── Nurture Queue ──────────────────────────────────────────
    def get_queue(self) -> list[dict]:
        ws = self.book.worksheet(TAB_QUEUE)
        # numericise_ignore keeps '+923...' phones as text instead of turning them into ints
        rows = ws.get_all_records(numericise_ignore=["all"])
        return [row_to_record(r, i + 2) for i, r in enumerate(rows)]

    def append_queue_row(self, record: dict) -> None:
        ws = self.book.worksheet(TAB_QUEUE)
        values = [record.get(key, "") for key, _ in QUEUE_COLUMNS]
        # RAW = Sheets stores exactly what we send (no date/number auto-parsing)
        ws.append_row(values, value_input_option="RAW")

    def update_queue_cells(self, row: int, updates: dict) -> None:
        """updates = {"last_contacted": "2026-09-30", "messages_sent": 2, ...} — one API call."""
        from gspread.utils import rowcol_to_a1
        ws = self.book.worksheet(TAB_QUEUE)
        ws.batch_update([{"range": rowcol_to_a1(row, QUEUE_COL_INDEX[k]), "values": [[v]]}
                         for k, v in updates.items()], value_input_option="RAW")

    def delete_queue_rows(self, rows: list[int]) -> None:
        ws = self.book.worksheet(TAB_QUEUE)
        for r in sorted(rows, reverse=True):      # bottom-up so row numbers stay valid
            ws.delete_rows(r)

    # ── Message Log ────────────────────────────────────────────
    def _log_ws(self):
        ws = self.book.worksheet(TAB_LOG)
        if not getattr(self, "_log_checked", False):   # auto-upgrade once per process
            current = ws.row_values(1)
            if current != LOG_HEADERS and LOG_HEADERS[:len(current)] == current:
                self._grow_headers(ws, LOG_HEADERS)
            self._log_checked = True
        return ws

    def append_log_row(self, values: list) -> None:
        self._log_ws().append_row(values, value_input_option="RAW")

    def log_rows(self) -> list[list[str]]:
        return self._log_ws().get_all_values()[1:]

    def append_hot_row(self, values: list) -> None:
        self.book.worksheet(TAB_HOT).append_row(values, value_input_option="RAW")

    # ── Dashboard readers ──────────────────────────────────────
    def log_records(self) -> list[dict]:
        return self._log_ws().get_all_records(numericise_ignore=["all"])

    def hot_records(self) -> list[dict]:
        return self.book.worksheet(TAB_HOT).get_all_records(numericise_ignore=["all"])

    # ── Counters for /health ───────────────────────────────────
    def count_messages_on(self, day: date) -> int:
        rows = self.book.worksheet(TAB_LOG).get_all_values()[1:]
        return sum(1 for r in rows if r and r[0].startswith(day.isoformat())
                   and len(r) > 8 and r[8].startswith("SENT"))

    def count_hot_upgrades(self) -> int:
        return len([v for v in self.book.worksheet(TAB_HOT).col_values(1)[1:] if v.strip()])
