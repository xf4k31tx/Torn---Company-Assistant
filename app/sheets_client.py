"""Google Sheets access using the signed-in user's OAuth credentials."""

from __future__ import annotations

import random
import time
from typing import Iterable, Sequence

import gspread

from .google_auth import get_credentials


def retry_gspread(func, max_retries: int = 5, initial_delay: float = 2.0):
    """Executes func(), retrying with exponential backoff if a Google Sheets API
    429 (Quota exceeded / Rate limit) or 5xx server error occurs.
    """
    delay = initial_delay
    for attempt in range(max_retries + 1):
        try:
            return func()
        except gspread.exceptions.APIError as e:
            status_code = getattr(getattr(e, "response", None), "status_code", None)
            err_str = str(e)
            is_quota_or_server_error = (
                status_code in (429, 500, 502, 503, 504)
                or "429" in err_str
                or "Quota exceeded" in err_str
                or "RESOURCE_EXHAUSTED" in err_str
                or "Read requests" in err_str
                or "Write requests" in err_str
            )
            if is_quota_or_server_error and attempt < max_retries:
                sleep_time = delay + random.uniform(0, 0.2 * delay)
                time.sleep(sleep_time)
                delay *= 2
            else:
                raise


class SheetsClient:
    def __init__(self, sheet_id: str = "", sheet_name: str = ""):
        if not sheet_id:
            raise ValueError("Provide the shared Google Sheet ID in Settings or for the company.")
        self._gc = retry_gspread(lambda: gspread.authorize(get_credentials()))
        # pyrefly: ignore [missing-attribute]
        self._sheet = retry_gspread(lambda: self._gc.open_by_key(sheet_id))

    @classmethod
    def get_or_create(cls, sheet_id: str, company_name: str, sheet_name: str = "") -> tuple["SheetsClient", str, bool]:
        """
        Try to open `sheet_id` if one is given. If it's blank, or gspread
        reports SpreadsheetNotFound (deleted/bad ID), create a brand-new
        Sheet named exactly `company_name` instead - no prompt, no prefix.
        Any other error (auth, network, etc.) still propagates normally.

        Returns (client, resolved_sheet_id, was_created). Callers must
        persist the resolved_sheet_id back into companies.json/Settings
        immediately when was_created is True, or a new Sheet will be
        created again on every subsequent run.
        """
        gc = retry_gspread(lambda: gspread.authorize(get_credentials()))
        if sheet_id:
            try:
                # pyrefly: ignore [missing-attribute]
                sheet = retry_gspread(lambda: gc.open_by_key(sheet_id))
                client = cls.__new__(cls)
                client._gc = gc
                client._sheet = sheet
                return client, sheet_id, False
            except gspread.SpreadsheetNotFound:
                pass
        # pyrefly: ignore [missing-attribute]
        sheet = retry_gspread(lambda: gc.create(company_name))
        client = cls.__new__(cls)
        client._gc = gc
        client._sheet = sheet
        # pyrefly: ignore [missing-attribute]
        return client, sheet.id, True

    @property
    def url(self) -> str:
        # pyrefly: ignore [missing-attribute]
        return self._sheet.url

    def _get_or_create_ws(self, title: str, headers: Sequence[str]):
        """
        Returns (worksheet, actual_headers). actual_headers is the header
        row that's really on the sheet after this call - for a brand-new
        tab that's just `headers`, but for an existing tab whose header row
        doesn't match (e.g. an older app version's schema), any headers
        already present are always kept in their existing position and
        only genuinely new ones from `headers` are appended after them.

        This is deliberately non-destructive: reordering or dropping an
        existing column here would silently shift every historical row's
        values under the wrong header. Write methods below build each row
        by header *name* against this merged list, so old and new columns
        both land in the right place regardless of schema drift.
        """
        try:
            # pyrefly: ignore [missing-attribute]
            ws = retry_gspread(lambda: self._sheet.worksheet(title))
        except gspread.WorksheetNotFound:
            # pyrefly: ignore [missing-attribute]
            ws = retry_gspread(lambda: self._sheet.add_worksheet(title=title, rows=1000, cols=max(10, len(headers))))
            # pyrefly: ignore [missing-attribute]
            retry_gspread(lambda: ws.append_row(list(headers)))
            return ws, list(headers)

        # pyrefly: ignore [missing-attribute]
        existing = retry_gspread(lambda: ws.row_values(1))
        while existing and existing[-1] == "":
            existing.pop()

        if not existing:
            # pyrefly: ignore [missing-attribute]
            retry_gspread(lambda: ws.append_row(list(headers)))
            return ws, list(headers)

        missing = [h for h in headers if h not in existing]
        if missing:
            merged = existing + missing
            # pyrefly: ignore [missing-attribute]
            retry_gspread(lambda: ws.update(range_name="1:1", values=[merged]))
            return ws, merged
        return ws, existing

    def append_history_row(self, title: str, headers: Sequence[str], row: dict) -> None:
        """Add one row of history. Inserted at row 2 (just under the header)
        so the sheet reads newest-snapshot-first, oldest at the bottom.
        `row` is a {header_name: value} dict - any header not present in
        `row` (including legacy columns from an older schema) is written
        blank."""
        ws, actual_headers = self._get_or_create_ws(title, headers)
        values = [str(row.get(h, "")) for h in actual_headers]
        # pyrefly: ignore [missing-attribute]
        retry_gspread(lambda: ws.insert_row(values, index=2, value_input_option="USER_ENTERED"))

    def append_history_rows(self, title: str, headers: Sequence[str], rows: Iterable[dict]) -> None:
        """Add several rows of history from one snapshot. Inserted as a
        block starting at row 2, so this snapshot's rows sit above all
        prior ones. Each row is a {header_name: value} dict."""
        rows = list(rows)
        if not rows:
            return
        ws, actual_headers = self._get_or_create_ws(title, headers)
        payload = [[str(row.get(h, "")) for h in actual_headers] for row in rows]
        # pyrefly: ignore [missing-attribute]
        retry_gspread(lambda: ws.insert_rows(payload, row=2, value_input_option="USER_ENTERED"))

    def overwrite_current_state(self, title: str, headers: Sequence[str], rows: Iterable[dict]) -> None:
        """Wipes and rewrites a "current state" tab (e.g. Employees). Each
        row is a {header_name: value} dict."""
        ws, actual_headers = self._get_or_create_ws(title, headers)
        # pyrefly: ignore [missing-attribute]
        retry_gspread(lambda: ws.clear())
        payload = [list(actual_headers)] + [[str(row.get(h, "")) for h in actual_headers] for row in rows]
        # pyrefly: ignore [missing-attribute]
        retry_gspread(lambda: ws.update(values=payload, value_input_option="USER_ENTERED"))

    def overwrite_worksheet(self, title: str, headers: Sequence[str], rows: Iterable[dict]) -> None:
        self.overwrite_current_state(title, headers, rows)

    def sort_history_newest_first(self, title: str) -> int:
        """One-time migration helper: re-sort an existing history tab's data
        rows so the newest snapshot (highest 'timestamp' column) ends up at
        the top. Returns the number of data rows the tab has, or 0 if the
        tab doesn't exist, has no 'timestamp' column, or has <2 data rows
        (nothing meaningful to reorder either way)."""
        try:
            # pyrefly: ignore [missing-attribute]
            ws = retry_gspread(lambda: self._sheet.worksheet(title))
        except gspread.WorksheetNotFound:
            return 0
        # pyrefly: ignore [missing-attribute]
        grid = retry_gspread(lambda: ws.get_all_values())
        # pyrefly: ignore [bad-argument-type]
        if len(grid) < 3:
            # pyrefly: ignore [bad-argument-type]
            return len(grid) - 1 if len(grid) >= 1 else 0  # header + 0/1 data rows
        # pyrefly: ignore [unsupported-operation]
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
            # pyrefly: ignore [missing-attribute]
            retry_gspread(lambda: ws.clear())
            # pyrefly: ignore [missing-attribute]
            retry_gspread(lambda: ws.update([headers] + sorted_rows, value_input_option="USER_ENTERED"))
        return len(data_rows)

    def read_records(self, title: str) -> list[dict]:
        try:
            # pyrefly: ignore [missing-attribute]
            ws = retry_gspread(lambda: self._sheet.worksheet(title))
        except gspread.WorksheetNotFound:
            return []
        try:
            # pyrefly: ignore [bad-return, missing-attribute]
            return retry_gspread(lambda: ws.get_all_records())
        except gspread.exceptions.GSpreadException:
            # get_all_records() rejects a header row with blank/duplicate
            # cells (e.g. leftover trailing blanks from an older schema).
            # Fall back to building records off the raw grid, keyed by
            # header name, ignoring any blank/duplicate header columns.
            # pyrefly: ignore [missing-attribute]
            grid = retry_gspread(lambda: ws.get_all_values())
            if not grid:
                return []
            headers, data_rows = grid[0], grid[1:]
            seen = set()
            keep_idx = []
            for i, h in enumerate(headers):
                if h and h not in seen:
                    seen.add(h)
                    keep_idx.append(i)
            return [
                {headers[i]: (row[i] if i < len(row) else "") for i in keep_idx}
                for row in data_rows
            ]

    def read_raw_grid(self, title: str) -> list[list[str]]:
        try:
            # pyrefly: ignore [missing-attribute]
            ws = retry_gspread(lambda: self._sheet.worksheet(title))
            # pyrefly: ignore [bad-return, missing-attribute]
            return retry_gspread(lambda: ws.get_all_values())
        except gspread.WorksheetNotFound:
            return []
