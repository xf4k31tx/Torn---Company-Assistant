#!/usr/bin/env python
"""Debug script to check stock history data in Google Sheet."""

from app.config import Settings
from app.sheets_client import SheetsClient

s = Settings.load()
try:
    sheets = SheetsClient(
        sheet_id=s.google_sheet_id,
        sheet_name=s.google_sheet_name,
    )
    
    print("Reading Stock_History from sheet...")
    records = sheets.read_records("Stock_History")
    
    if not records:
        print("  [Empty]")
    else:
        # Show last 3 rows for each stock
        by_name = {}
        for r in records:
            name = r.get("name", "Unknown")
            if name not in by_name:
                by_name[name] = []
            by_name[name].append(r)
        
        for name in sorted(by_name.keys()):
            rows = by_name[name]
            print(f"\n{name} (last 3 rows):")
            for row in rows[-3:]:
                print(f"  ts: {row.get('timestamp')}, in_stock: {row.get('in_stock')}, " +
                      f"sold_amount: {row.get('sold_amount')}, delta_in_stock: {row.get('delta_in_stock')}, " +
                      f"delta_sold_amount: {row.get('delta_sold_amount')}, created: {row.get('created')}")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
