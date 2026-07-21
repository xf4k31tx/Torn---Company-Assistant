#!/usr/bin/env python3
"""
One-off migration for Company_History:
  1. Recomputes daily_profit for every row using the current formula
     (daily_income - (daily_stockcost + advertising_budget + total_wage)).
     This is a *forced* recompute, not a "fill if blank" - the formula
     itself changed (it now includes daily_stockcost, and the old
     daily_profit_after_stock column has been removed/folded in), so any
     previously-stored daily_profit values are stale under the old formula.
  2. Backfills weekly_profit if missing (formula unchanged, so existing
     values are left alone).
  3. Recomputes avg_daily_profit_7day and avg_daily_income_7day for every
     row, since both are rolling averages and therefore cascade from step 1
     / from daily_income.
  4. Rewrites the whole tab in the current canonical column order, which
     also drops the now-removed daily_profit_after_stock column and fixes
     up the header row for any sheet still on an older schema.

Rows are processed oldest-first so the rolling averages are computed in
the same order they would have happened live.

Usage:
    python scripts/backfill_company_history.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.collector import COMPANY_HISTORY_HEADERS  # noqa: E402
from app.config import Settings  # noqa: E402
from app.profit_calc import (  # noqa: E402
    compute_avg_daily_income_7day,
    compute_avg_daily_profit_7day,
    compute_row_profit_fields,
    safe_float,
)
from app.sheets_client import SheetsClient  # noqa: E402

TAB = "Company_History"

SCHEMA_HISTORY = {
    24: "original (pre-profit columns)",
    25: "+ daily_profit (old formula)",
    26: "+ daily_profit_after_stock (now removed)",
    27: "+ weekly_profit, avg_daily_profit_7day (pre avg_daily_income_7day)",
    28: "+ avg_daily_income_7day (current)",
}


def is_blank(value) -> bool:
    return value in (None, "")


def migrate():
    settings = Settings.load()
    sheets = SheetsClient(
        sheet_id=settings.google_sheet_id,
        sheet_name=settings.google_sheet_name,
    )

    grid = sheets.read_raw_grid(TAB)
    if not grid:
        print(f"'{TAB}' tab is empty or doesn't exist yet - nothing to migrate.")
        return

    old_header, *data_rows = grid
    version_note = SCHEMA_HISTORY.get(len(old_header), f"unrecognized ({len(old_header)} columns)")
    print(f"Found {len(data_rows)} existing row(s) under schema: {version_note}")

    # Build records keyed by original header names, then sort oldest-first
    # so the rolling 7-day average is computed in the order it would have
    # happened live.
    records = []
    for raw_row in data_rows:
        padded = raw_row + [""] * (len(old_header) - len(raw_row))
        records.append(dict(zip(old_header, padded)))
    records.sort(key=lambda r: safe_float(r.get("timestamp")))

    backfilled_count = 0
    processed: list[dict] = []  # already-migrated rows, used as "prior_rows" for later ones

    for record in records:
        timestamp = int(safe_float(record.get("timestamp")))
        daily_income = safe_float(record.get("daily_income"))
        weekly_income = safe_float(record.get("weekly_income"))
        advertising_budget = safe_float(record.get("advertising_budget"))
        total_wage = safe_float(record.get("total_wage"))
        daily_stockcost = safe_float(record.get("daily_stockcost"))

        fields = compute_row_profit_fields(
            daily_income=daily_income,
            weekly_income=weekly_income,
            advertising_budget=advertising_budget,
            total_wage=total_wage,
            daily_stockcost=daily_stockcost,
        )

        changed = False

        # daily_profit: always recompute, formula changed.
        old_daily_profit = record.get("daily_profit")
        record["daily_profit"] = fields["daily_profit"]
        if is_blank(old_daily_profit) or safe_float(old_daily_profit) != fields["daily_profit"]:
            changed = True

        # weekly_profit: formula unchanged, only fill if missing.
        if is_blank(record.get("weekly_profit")):
            record["weekly_profit"] = fields["weekly_profit"]
            changed = True

        # avg_daily_profit_7day: always recompute, it cascades from daily_profit.
        old_avg = record.get("avg_daily_profit_7day")
        record["avg_daily_profit_7day"] = compute_avg_daily_profit_7day(
            prior_rows=processed,
            current_timestamp=timestamp,
            current_daily_profit=record["daily_profit"],
        )
        if is_blank(old_avg) or safe_float(old_avg) != record["avg_daily_profit_7day"]:
            changed = True

        # avg_daily_income_7day: always recompute, same rolling-window logic.
        old_avg_income = record.get("avg_daily_income_7day")
        record["avg_daily_income_7day"] = compute_avg_daily_income_7day(
            prior_rows=processed,
            current_timestamp=timestamp,
            current_daily_income=daily_income,
        )
        if is_blank(old_avg_income) or safe_float(old_avg_income) != record["avg_daily_income_7day"]:
            changed = True

        if changed:
            backfilled_count += 1

        processed.append(record)

    # Rows were processed oldest-first (needed for the rolling averages to
    # cascade correctly); write them back newest-first to match how the app
    # now orders every history tab. overwrite_worksheet() takes {header:
    # value} dicts (not positional lists) as of Phase 4/5's Sheets client
    # rework - any old-schema column no longer in COMPANY_HISTORY_HEADERS
    # (e.g. the removed upgrade_company_size) is intentionally dropped here,
    # since this script does a full-tab rewrite onto the current canonical
    # schema. That's different from the live collector's incremental
    # append path, which never drops an existing column to avoid
    # misaligning historical rows it isn't touching.
    new_rows = [
        {col: record.get(col, "") for col in COMPANY_HISTORY_HEADERS}
        for record in reversed(processed)
    ]

    sheets.overwrite_worksheet(TAB, COMPANY_HISTORY_HEADERS, new_rows)
    print(f"Recomputed/backfilled {backfilled_count} of {len(processed)} row(s).")
    print(f"'{TAB}' is now on the current {len(COMPANY_HISTORY_HEADERS)}-column schema "
          f"(daily_profit_after_stock removed, daily_profit formula updated).")
    print(f"Sheet: {sheets.url}")


if __name__ == "__main__":
    migrate()
