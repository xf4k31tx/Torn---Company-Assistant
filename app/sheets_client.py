"""Google Sheets access using the signed-in user's OAuth credentials."""

from __future__ import annotations

from typing import Iterable, Sequence

import gspread

from .google_auth import get_credentials


class SheetsClient:
    def __init__(self, sheet_id: str = "", sheet_name: str = ""):
        if not sheet_id:
            raise ValueError("Provide the shared Google Sheet ID in Settings or for the company.")
        self._gc = gspread.authorize(get_credentials())
        self._sheet = self._gc.open_by_key(sheet_id)

    @property
    def url(self) -> str:
        return self._sheet.url

    def _get_or_create_ws(self, title: str, headers: Sequence[str]):
        try:
            ws = self._sheet.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = self._sheet.add_worksheet(title=title, rows=1000, cols=max(10, len(headers)))
            ws.append_row(list(headers))
            return ws
        if not ws.row_values(1):
            ws.append_row(list(headers))
        return ws

    def append_history_row(self, title: str, headers: Sequence[str], row: Sequence) -> None:
        """Add one row of history. Inserted at row 2 (just under the header)
        so the sheet reads newest-snapshot-first, oldest at the bottom."""
        ws = self._get_or_create_ws(title, headers)
        ws.insert_row([str(v) for v in row], index=2, value_input_option="USER_ENTERED")

    def append_history_rows(self, title: str, headers: Sequence[str], rows: Iterable[Sequence]) -> None:
        """Add several rows of history from one snapshot. Inserted as a block
        starting at row 2, so this snapshot's rows sit above all prior ones."""
        payload = [[str(v) for v in row] for row in rows]
        if payload:
            ws = self._get_or_create_ws(title, headers)
            ws.insert_rows(payload, row=2, value_input_option="USER_ENTERED")

    def overwrite_current_state(self, title: str, headers: Sequence[str], rows: Iterable[Sequence]) -> None:
        ws = self._get_or_create_ws(title, headers)
        ws.clear()
        ws.update([list(headers)] + [[str(v) for v in row] for row in rows], value_input_option="USER_ENTERED")

    def overwrite_worksheet(self, title: str, headers: Sequence[str], rows: Iterable[Sequence]) -> None:
        self.overwrite_current_state(title, headers, rows)

    def sort_history_newest_first(self, title: str) -> int:
        """One-time migration helper: re-sort an existing history tab's data
        rows so the newest snapshot (highest 'timestamp' column) ends up at
        the top. Returns the number of data rows the tab has, or 0 if the
        tab doesn't exist, has no 'timestamp' column, or has <2 data rows
        (nothing meaningful to reorder either way)."""
        try:
            ws = self._sheet.worksheet(title)
        except gspread.WorksheetNotFound:
            return 0
        grid = ws.get_all_values()
        if len(grid) < 3:
            return len(grid) - 1 if len(grid) >= 1 else 0  # header + 0/1 data rows
        headers, data_rows = grid[0], grid[1:]
        if "timestamp" not in headers:
            return 0
        ts_idx = headers.index("timestamp")

        def sort_key(row):
            try:
                return -float(row[ts_idx]) if ts_idx < len(row) else 0.0
            except (ValueError, IndexError):
                return 0.0

        sorted_rows = sorted(data_rows, key=sort_key)
        if sorted_rows != data_rows:
            ws.clear()
            ws.update([headers] + sorted_rows, value_input_option="USER_ENTERED")
        return len(data_rows)

    def read_records(self, title: str) -> list[dict]:
        try:
            return self._sheet.worksheet(title).get_all_records()
        except gspread.WorksheetNotFound:
            return []

    def read_raw_grid(self, title: str) -> list[list[str]]:
        try:
            return self._sheet.worksheet(title).get_all_values()
        except gspread.WorksheetNotFound:
            return []
