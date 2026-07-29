"""
Desktop GUI for the Knotty Oil Tracker.

Tabs (nested structure as of Phase 1):
  Overview                              - latest company-level snapshot + a "Run Snapshot Now" button
  Employees (parent)
    Employee Overview                   - current roster with Torn's per-employee effectiveness breakdown
    Position Efficiency (parent)
      Base Effectiveness Projections    - Tornstats work-stats projections per employee per position
      Total Effectiveness Projections   - placeholder; wired with real data in Phase 2
  Stock & Profit Trends (parent)
    Stock                               - latest stock snapshot + a sold-worth trend chart
    Company Trends                      - pick any Company_History metric and chart it over time
  Settings                              - encrypted local API keys / Google OAuth / sheet target

All data is read straight from the Google Sheet (via SheetsClient), so the
GUI is safe to close and reopen without losing anything - the Sheet is the
source of truth. "Run Snapshot Now" triggers app.collector.Collector in a
background thread so the UI never freezes on network calls.
"""

from __future__ import annotations

import datetime
import json
import threading
import time
import sys
import os
import tkinter as tk
import docx
from pathlib import Path
# Identify the root directory path 
project_root = str(Path(__file__).resolve().parent.parent)
# Append the root path index to Python's environment lookup tree if not already present
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from tkinter import ttk, messagebox, simpledialog
from tkinter import font as tkfont
from tkinter import Toplevel, scrolledtext, END, Button

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from app.collector import Collector
from app.config import Settings
from app.sheets_client import SheetsClient
from app.google_auth import authorize as authorize_google, pick_google_sheet
from app import companies as companies_mod

# Stores only window size, position, and maximized state.
# API keys and other sensitive settings remain in the encrypted Settings file.
WINDOW_STATE_FILE = Path.home() / ".torn_company_assistant_window.json"

# Fields that represent Torn dollars and should render as "$1,234,567" rather
# than a bare number. Keyed by the sheet-tab they come from.
INTEGER_FIELDS = {
    "Stock_History": {"in_stock", "sold_amount", "created"},
}
def format_int(value) -> str:
    """1234 / 1234.0 -> '1,234'."""
    try:
        return f"{int(round(float(value))):,}"
    except (TypeError, ValueError):
        return str(value)
    
MONEY_FIELDS = {
    "Company_History": {
        "daily_income", "daily_profit", "weekly_income", "weekly_profit", "company_funds",
        "advertising_budget", "total_wage", "daily_stockcost",
        "avg_daily_profit_7day", "avg_daily_income_7day",
    },
    "Employees": {"wage"},
    "Employee_Effectiveness": {"wage"},
    "Stock_History": {"cost", "price", "sold_worth", "delta_sold_worth"},
}

# Fields that are unix timestamps and should render as a readable date/time
# rather than a raw epoch number. Keyed by the sheet-tab they come from.
TIMESTAMP_FIELDS = {
    "Employees": {"last_action_ts"},
    "Employee_Effectiveness": {"last_action_ts"},
}

# Fields that are a delta vs. the previous snapshot and should render with an
# explicit +/- sign so a change is obvious at a glance. Keyed by sheet-tab.
SIGNED_FIELDS = {
    "Stock_History": {"delta_in_stock", "delta_sold_amount"},
}

# Fields that are TRUE/FALSE flag columns and should render as a plain-
# language yes/blank rather than the raw sheet string. Keyed by sheet-tab.
BOOL_FIELDS = {
    "Employee_Effectiveness": {"misplaced_flag", "wage_efficiency_flag"},
    "Stock_History": {"stockout_soon"},
}


def format_money(value) -> str:
    """'1234567' / '1234567.5' -> '$1,234,568' (whole dollars, comma-grouped)."""
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return str(value)
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.0f}"


def format_timestamp(value) -> str:
    """Unix timestamp (int/str/float) -> 'YYYY-MM-DD HH:MM UTC'. Falls back
    to the raw value as-is if it isn't a valid number (e.g. blank cell)."""
    try:
        ts = int(float(value))
    except (TypeError, ValueError):
        return str(value)
    if ts <= 0:
        return str(value)
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def format_time_since(value) -> str:
    """Unix timestamp -> human-readable elapsed time, e.g. '2d 4h ago',
    '5h 12m ago', '3m ago', 'just now'. Computed against wall-clock time at
    render time, so this updates naturally every time the tab refreshes."""
    try:
        ts = int(float(value))
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    delta = int(time.time() - ts)
    if delta < 0:
        return "in the future"
    if delta < 60:
        return "just now"
    days, rem = divmod(delta, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours}h ago"
    if hours > 0:
        return f"{hours}h {minutes}m ago"
    return f"{minutes}m ago"

def get_legal_text(relative_subpath: str) -> str:
    """
    Locates and extracts text paragraphs from a .docx Word document.
    Accurately preserves the nested layout across loose script runs and compiled bundles.
    """
    if getattr(sys, "frozen", False):
        # Target Nuitka's true internal temp extraction root directory
        try:
            main_module = sys.modules['__main__']
            bundle_root = Path(main_module.__file__).resolve().parent
        except Exception:
            bundle_root = Path(sys.executable).parent
    else:
        # Standard local development folder tracking (shifts up from gui/)
        bundle_root = Path(__file__).resolve().parent.parent

    # Construct the path to your structured asset target
    target_path = bundle_root / relative_subpath

    # Debug fallback check showing the absolute path tried if a crash occurs
    if not target_path.is_file():
        return f"Error: [Internal Path: {target_path}] - {relative_subpath} missing from bundle."
        
    try:
        doc = docx.Document(target_path)
        full_text = []
        for para in doc.paragraphs:
            full_text.append(para.text)
        return "\n".join(full_text)
    except Exception as e:
        return f"Error processing Word document: {str(e)}"


def build_employee_info_card_fields(record: dict | None) -> list[tuple[str, str]]:
    """Employee_Effectiveness row -> ordered (label, formatted value) pairs
    for the Position Efficiency tab's employee info card popup. Pure and
    Tk-independent so it's testable without a real widget. record is None
    (or {}) when the clicked employee's tId has no matching row in the
    Employee_Effectiveness sheet (stale cache / sheet edited externally) -
    the caller is expected to show its own "not found" message in that
    case rather than call this with no data.

    "Current Eff." reuses the same terminology/field as the Employees and
    Position Efficiency tabs' own "Current Eff." column
    (projected_efficiency_current_position, Tornstats' projection at the
    employee's current position) rather than Torn's own "Work Stats Eff."
    (effectiveness_working_stats), for consistency with the rest of the app."""
    record = record or {}
    return [
        ("Name", str(record.get("name", "") or "")),
        ("ID", str(record.get("tId", "") or "")),
        ("Last Online", format_time_since(record.get("last_action_ts")) or "Unknown"),
        ("Manual Labor", format_int(record.get("manual_labor"))),
        ("Endurance", format_int(record.get("endurance"))),
        ("Intelligence", format_int(record.get("intelligence"))),
        ("Current Position", str(record.get("current_position", "") or "")),
        ("Current Eff.", format_int(record.get("projected_efficiency_current_position"))),
        ("Total Eff.", format_int(record.get("effectiveness_total"))),
    ]


def format_signed_int(value) -> str:
    """'50' -> '+50', '-20' -> '-20', '0'/blank -> '0'. Used for day-over-day
    deltas so an increase vs. a decrease is obvious at a glance."""
    try:
        amount = int(round(float(value)))
    except (TypeError, ValueError):
        return str(value)
    if amount > 0:
        return f"+{amount:,}"
    return f"{amount:,}"


def format_bool_flag(value) -> str:
    """Sheet TRUE/FALSE (or Python True/False) -> a plain-language marker.
    Blank for False so a scanned column reads as "empty unless flagged"
    rather than a wall of repeated 'No's."""
    text = str(value).strip().lower()
    return "\u26a0 Yes" if text in ("true", "1", "yes") else ""


def pretty_label(text: str) -> str:
    """Internal snake_case field/column name -> display label.
    'daily_income' -> 'daily income', 'in_stock_difference' -> 'in stock difference'.
    Data lookups always use the original underscored name; this is display-only."""
    return text.replace("_", " ")


def format_field(field_name: str, value, tab: str) -> str:
    if field_name in MONEY_FIELDS.get(tab, ()):
        return format_money(value)
    if field_name in TIMESTAMP_FIELDS.get(tab, ()):
        return format_timestamp(value)
    if field_name in SIGNED_FIELDS.get(tab, ()):
        return format_signed_int(value)
    if field_name in BOOL_FIELDS.get(tab, ()):
        return format_bool_flag(value)
    if field_name in INTEGER_FIELDS.get(tab, ()):
        return format_int(value)
    return str(value)


def format_employee_field(field_name: str, row: dict) -> str:
    if field_name == "time_since_last_action":
        return format_time_since(row.get("last_action_ts"))
    value = row.get(field_name, "")
    formatted = format_field(field_name, value, "Employee_Effectiveness")
    if field_name in {"effectiveness_addiction", "effectiveness_inactivity", "effectiveness_director_education", "effectiveness_book", "effectiveness_management", "effectiveness_settled_in", "effectiveness_working_stats", "effectiveness_total", "effectiveness_merits"}:
        try:
            if float(value) <= -10:
                return f"\u26a0 {formatted}"
        except (TypeError, ValueError):
            pass
    return formatted


EMPLOYEE_FOOTER_TOTAL_COLUMNS = {
    "wage",
    "effectiveness_total",
    "effectiveness_working_stats",
    "projected_efficiency_current_position",
    "effectiveness_settled_in",
    "effectiveness_director_education",
    "effectiveness_addiction",
    "effectiveness_inactivity",
    "effectiveness_management",
    "effectiveness_book",
    "effectiveness_merits",
    "assigned_efficiency",
}


def employee_footer_total(records, field_name):
    total = 0.0
    found_numeric_value = False
    for row in records:
        try:
            value = row.get(field_name)
            if isinstance(value, str):
                value = value.replace(",", "").replace("$", "").strip()
            total += float(value)
            found_numeric_value = True
        except (TypeError, ValueError):
            continue
    if not found_numeric_value:
        return ""
    return f"{total:,.2f}".rstrip("0").rstrip(".")


def scroll_canvas_xview(canvas, *args):
    canvas.xview(*args)
    canvas.update_idletasks()


def company_selector_values(companies):
    names = [company.get("name", "Unnamed") for company in companies]
    return names or ["(No companies configured)"]


def employee_cell_style(field_name: str, row: dict, base_background="#ffffff"):
    if field_name == "current_position":
        current_position = str(row.get("current_position") or "").strip()
        assigned_position = str(row.get("assigned_position") or "").strip()
        if assigned_position:
            if current_position == assigned_position:
                return "#d4edda", "#155724"
            return "#f8d7da", "#721c24"
    if field_name in {"effectiveness_addiction", "effectiveness_inactivity", "effectiveness_director_education", "effectiveness_book", "effectiveness_management", "effectiveness_settled_in", "effectiveness_working_stats", "effectiveness_total", "effectiveness_merits"}:
        try:
            if float(row.get(field_name)) <= -10:
                return "#f8d7da", "#721c24"
        except (TypeError, ValueError):
            pass
    return base_background, "#000000"


def position_efficiency_score_style(value):
    if value in (None, ""):
        return "", "#e8e8e8", "#777777"
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "", "#e8e8e8", "#777777"
    rounded_score = int(round(score))
    if rounded_score < 50:
        background = "#c62828"
    elif rounded_score < 75:
        background = "#ef6c00"
    elif rounded_score < 99:
        background = "#f9c74f"
    elif rounded_score < 129:
        background = "#66bb6a"
    else:
        background = "#1b5e20"
    return str(rounded_score), background, _readable_text_color(background)


def position_efficiency_sort_value(record: dict, column: str):
    key = (record.get("current_position") or "") if column == "current_efficiency" else column
    value = record.get(key, "")
    if column in {"name", "current_position"}:
        return str(value).lower()
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("-inf")


# Work-stats-effectiveness color grading for the Position Effectiveness tab.
# Torn/Tornstats don't publish exact color/threshold values for this anywhere
# (checked - there's no documented spec, just "red is bad, green is good"
# from players' own screenshots/descriptions), so this reproduces the same
# red -> orange -> yellow -> light green -> dark green gradient the old
# position_efficiency tab already used (matplotlib's "RdYlGn" colormap) as a set of
# named, continuously-interpolated stops instead of a matplotlib dependency,
# so plain tk.Label cells can use it too. 100% = exactly meets a position's
# stat requirement; below is under-qualified, above is over-qualified.
_EFFECTIVENESS_COLOR_STOPS = [
    (0.0, (198, 40, 40)),      # deep red     - badly under-qualified
    (50.0, (239, 108, 0)),     # orange
    (70.0, (249, 199, 79)),    # yellow
    (90.0, (156, 204, 101)),   # light green
    (110.0, (46, 125, 50)),    # dark green   - meets/exceeds requirement
]


def _effectiveness_color(value):
    """
    Continuous gradient:
        0   -> Red
        50  -> Orange
        80  -> Yellow
        100 -> Light Green
        120 -> Green
        140+-> Dark Green
    """
    value = max(0, min(140, float(value)))
    stops = [
        (0,   (200,  50,  50)),   # red
        (50,  (235, 120,  40)),   # orange
        (80,  (245, 210,  60)),   # yellow
        (100, (150, 220, 100)),   # light green
        (120, ( 80, 180,  80)),   # green
        (140, ( 30, 120,  50)),   # dark green
    ]
    for i in range(len(stops)-1):
        v1, c1 = stops[i]
        v2, c2 = stops[i+1]
        if value <= v2:
            t = (value - v1) / (v2 - v1)
            r = int(c1[0] + (c2[0]-c1[0]) * t)
            g = int(c1[1] + (c2[1]-c1[1]) * t)
            b = int(c1[2] + (c2[2]-c1[2]) * t)
            return f"#{r:02x}{g:02x}{b:02x}"
    return "#1e7832"


def _readable_text_color(bg):
    bg = bg.lstrip("#")
    r = int(bg[0:2], 16)
    g = int(bg[2:4], 16)
    b = int(bg[4:6], 16)
    brightness = (r*299 + g*587 + b*114) / 1000
    return "#000000" if brightness > 150 else "#ffffff"


# Full Employees table column set, in order: (header, row_key). Headers use
# \n for explicit line breaks - ttk.Treeview headings render multi-line
# text natively (given the 'clam' theme - see launch()), unlike cell
# values, which Treeview always clips to one line.
EMPLOYEE_TABLE_COLUMNS = [
    ("Name", "name"),
    ("Position", "current_position"),
    ("Wage", "wage"),
    ("Days in\nCompany", "days_in_company"),
    ("Manual\nLabor", "manual_labor"),
    ("Intelligence", "intelligence"),
    ("Endurance", "endurance"),
    ("Total\nEff.", "effectiveness_total"),
    ("Work Stats\nEff.", "effectiveness_working_stats"),
    ("Settled In\nEff.", "effectiveness_settled_in"),
    ("Education\nEff.", "effectiveness_director_education"),
    ("Addiction\nEff.", "effectiveness_addiction"),
    ("Inactivity\nEff.", "effectiveness_inactivity"),
    ("Management\nEff.", "effectiveness_management"),
    ("Book\nEff.", "effectiveness_book"),
    ("Merits\nEff.", "effectiveness_merits"),
    ("Current\nEff.", "projected_efficiency_current_position"),
    ("Best Fit\nPosition", "best_fit_position"),
    ("Best Fit\nEff.", "best_fit_efficiency"),
    ("Assigned\nPosition", "assigned_position"),
    ("Assigned\nEff.", "assigned_efficiency"),
    ("Misplaced", "misplaced_flag"),
    ("Wage\nEfficiency", "wage_efficiency"),
    ("Wage Eff.\nOutlier", "wage_efficiency_flag"),
    ("Time Since\nLast Action", "time_since_last_action"),
    ("tId", "tId"),
]

# Shown by default; the rest are available via the "Columns..." toggle.
# Chosen to mirror the old standalone Employee Calculator's default view
# plus the new Phase 4 misplaced/wage-outlier flags, without overwhelming
# a first-time user with all 26 columns at once.
DEFAULT_VISIBLE_EMPLOYEE_COLUMNS = {
    "tId", "name", "wage", "current_position", "projected_efficiency_current_position",
    "assigned_position", "assigned_efficiency", "effectiveness_settled_in", "effectiveness_director_education",
    "effectiveness_addiction", "effectiveness_inactivity", "effectiveness_management", 
    "effectiveness_book", "effectiveness_merits", "effectiveness_total", "time_since_last_action", 
}

LEFT_ALIGNED_EMPLOYEE_COLUMNS = {"name", "current_position", "best_fit_position", "assigned_position"}
POSITION_LOCK_COLUMN = "position_lock"


def employee_position_is_locked(row, locked_employee_ids):
    employee_id = str(row.get("tId") or "")
    locked_ids = {str(value) for value in (locked_employee_ids or [])}
    return bool(employee_id and employee_id in locked_ids)


class ColumnPickerDialog(tk.Toplevel):
    """
    Modal dialog for choosing which Employees columns are visible and
    arranging their display order.

    self.result is the ordered list of selected column keys, or None when
    cancelled.
    """

    def __init__(self, master, visible_keys):
        super().__init__(master)
        self.title("Choose and Reorder Columns")
        self.resizable(False, False)
        self.result = None
        self.transient(master)
        self.grab_set()

        self.column_labels = {
            key: header.replace("\n", " ")
            for header, key in EMPLOYEE_TABLE_COLUMNS
        }

        all_keys = [key for _, key in EMPLOYEE_TABLE_COLUMNS]

        # Keep the currently saved/displayed order first.
        self.column_order = [
            key for key in visible_keys
            if key in self.column_labels
        ]

        # Add currently hidden columns after the visible columns.
        self.column_order.extend(
            key for key in all_keys
            if key not in self.column_order
        )

        self.visible_keys = set(visible_keys)

        ttk.Label(
            self,
            text=(
                "Select the columns to display. Use Move Up and Move Down\n"
                "to change their left-to-right order."
            ),
            justify="left",
        ).pack(anchor="w", padx=12, pady=(12, 8))

        content = ttk.Frame(self)
        content.pack(fill="both", expand=True, padx=12)

        self.column_list = tk.Listbox(
            content,
            width=38,
            height=min(22, len(self.column_order)),
            selectmode="browse",
            exportselection=False,
        )
        self.column_list.grid(row=0, column=0, rowspan=6, sticky="nsew")

        scrollbar = ttk.Scrollbar(
            content,
            orient="vertical",
            command=self.column_list.yview,
        )
        scrollbar.grid(row=0, column=1, rowspan=6, sticky="ns")
        self.column_list.configure(yscrollcommand=scrollbar.set)

        ttk.Button(
            content,
            text="Show / Hide",
            command=self._toggle_selected,
            width=14,
        ).grid(row=0, column=2, padx=(10, 0), pady=(0, 4), sticky="ew")

        ttk.Button(
            content,
            text="Move Up",
            command=lambda: self._move_selected(-1),
            width=14,
        ).grid(row=1, column=2, padx=(10, 0), pady=4, sticky="ew")

        ttk.Button(
            content,
            text="Move Down",
            command=lambda: self._move_selected(1),
            width=14,
        ).grid(row=2, column=2, padx=(10, 0), pady=4, sticky="ew")

        ttk.Button(
            content,
            text="Show All",
            command=self._show_all,
            width=14,
        ).grid(row=3, column=2, padx=(10, 0), pady=4, sticky="ew")

        ttk.Button(
            content,
            text="Hide All",
            command=self._hide_all,
            width=14,
        ).grid(row=4, column=2, padx=(10, 0), pady=4, sticky="ew")

        content.rowconfigure(5, weight=1)
        content.columnconfigure(0, weight=1)

        self.column_list.bind(
            "<Double-Button-1>",
            lambda event: self._toggle_selected(),
        )

        self._refresh_list()

        button_row = ttk.Frame(self)
        button_row.pack(pady=12)

        ttk.Button(
            button_row,
            text="Apply",
            command=self._apply,
        ).pack(side="left", padx=4)

        ttk.Button(
            button_row,
            text="Cancel",
            command=self.destroy,
        ).pack(side="left", padx=4)

    def _refresh_list(self, selected_index=None):
        self.column_list.delete(0, "end")

        for key in self.column_order:
            marker = "☑" if key in self.visible_keys else "☐"
            self.column_list.insert(
                "end",
                f"{marker}  {self.column_labels[key]}",
            )

        if selected_index is not None and self.column_order:
            selected_index = max(
                0,
                min(selected_index, len(self.column_order) - 1),
            )
            self.column_list.selection_clear(0, "end")
            self.column_list.selection_set(selected_index)
            self.column_list.activate(selected_index)
            self.column_list.see(selected_index)

    def _selected_index(self):
        selection = self.column_list.curselection()
        if not selection:
            return None
        return selection[0]

    def _toggle_selected(self):
        index = self._selected_index()
        if index is None:
            return

        key = self.column_order[index]

        if key in self.visible_keys:
            self.visible_keys.remove(key)
        else:
            self.visible_keys.add(key)

        self._refresh_list(index)

    def _move_selected(self, direction):
        index = self._selected_index()
        if index is None:
            return

        target = index + direction

        if not 0 <= target < len(self.column_order):
            return

        self.column_order[index], self.column_order[target] = (
            self.column_order[target],
            self.column_order[index],
        )

        self._refresh_list(target)

    def _show_all(self):
        self.visible_keys = set(self.column_order)
        self._refresh_list(self._selected_index())

    def _hide_all(self):
        self.visible_keys.clear()
        self._refresh_list(self._selected_index())

    def _apply(self):
        self.result = [
            key
            for key in self.column_order
            if key in self.visible_keys
        ]
        self.destroy()


class PositionCapacitiesDialog(tk.Toplevel):
    """
    Modal dialog configuring how "Assigned Position" fills seats for one
    company: each position's max headcount, and the priority order
    positions are filled in. Positions are listed top-to-bottom in current
    priority order (top = filled first, with the best remaining candidates,
    before moving down the list); use the up/down buttons to reorder.
    Leaving a Max Qty field blank means "no cap" for that position.

    self.result ends up as:
      - {"capacities": {position_name: int}, "priority_order": [position_name, ...]}
        - user saved settings, run priority-constrained
      - "global" - user chose to skip capacities/priority entirely
      - None     - user cancelled
    """

    def __init__(self, master, position_names, existing_capacities, existing_priority_order=None):
        super().__init__(master)
        self.title("Position Capacities && Priority")
        self.resizable(False, False)
        self.result = None
        self.transient(master)
        self.grab_set()

        existing_priority_order = existing_priority_order or []
        self.position_order = [p for p in existing_priority_order if p in position_names]
        self.position_order += [p for p in position_names if p not in self.position_order]

        self.capacity_vars = {
            pos: tk.StringVar(value=str(existing_capacities[pos]) if existing_capacities.get(pos, "") != "" else "")
            for pos in position_names
        }

        ttk.Label(
            self,
            text=(
                "Set each position's max headcount and fill priority (top = filled\n"
                "first, with the best remaining candidates). Leave Max Qty blank for\n"
                "no cap on that position."
            ),
            justify="left",
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(12, 8))

        self.rows_frame = ttk.Frame(self)
        self.rows_frame.grid(row=1, column=0, sticky="w", padx=12)
        self._render_rows()

        button_row = ttk.Frame(self)
        button_row.grid(row=2, column=0, pady=12)
        ttk.Button(button_row, text="Save && Use Priorities", command=self._save_and_run).pack(side="left", padx=4)
        ttk.Button(button_row, text="Use Global Projection Only", command=self._run_global).pack(side="left", padx=4)
        ttk.Button(button_row, text="Cancel", command=self._cancel).pack(side="left", padx=4)

    def _render_rows(self):
        for widget in self.rows_frame.winfo_children():
            widget.destroy()

        header = ttk.Frame(self.rows_frame)
        header.grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Label(header, text="", width=5).grid(row=0, column=0)
        ttk.Label(header, text="Priority", width=8).grid(row=0, column=1)
        ttk.Label(header, text="Position", width=22).grid(row=0, column=2)
        ttk.Label(header, text="Max Qty", width=8).grid(row=0, column=3)

        last = len(self.position_order) - 1
        for i, pos in enumerate(self.position_order):
            row = ttk.Frame(self.rows_frame)
            row.grid(row=i + 1, column=0, sticky="w", pady=1)

            move_frame = ttk.Frame(row, width=50)
            move_frame.grid(row=0, column=0)
            up = ttk.Button(move_frame, text="\u25b2", width=2, command=lambda idx=i: self._move(idx, -1))
            up.grid(row=0, column=0)
            up.state(["disabled"] if i == 0 else ["!disabled"])
            down = ttk.Button(move_frame, text="\u25bc", width=2, command=lambda idx=i: self._move(idx, 1))
            down.grid(row=0, column=1)
            down.state(["disabled"] if i == last else ["!disabled"])

            ttk.Label(row, text=str(i + 1), width=8, anchor="w").grid(row=0, column=1)
            ttk.Label(row, text=pos, width=22, anchor="w").grid(row=0, column=2)
            ttk.Entry(row, textvariable=self.capacity_vars[pos], width=8).grid(row=0, column=3)

    def _move(self, idx, delta):
        target = idx + delta
        if 0 <= target < len(self.position_order):
            self.position_order[idx], self.position_order[target] = (
                self.position_order[target], self.position_order[idx],
            )
            self._render_rows()

    def _save_and_run(self):
        capacities = {}
        for pos, var in self.capacity_vars.items():
            text = var.get().strip()
            if not text:
                continue
            try:
                capacities[pos] = int(text)
            except ValueError:
                messagebox.showerror("Position Capacities", f"'{text}' isn't a whole number for {pos}.")
                return
        self.result = {"capacities": capacities, "priority_order": list(self.position_order)}
        self.destroy()

    def _run_global(self):
        self.result = "global"
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


class PositionVisibilityDialog(tk.Toplevel):
    """Modal checklist for which positions show as columns on the Position
    Effectiveness grid, plus a free-text way to add a position by hand.

    This exists because there's no fully reliable automatic source for "every
    position this company type has" - Tornstats' own /efficiency response is
    the best one available, but it can omit a real position outright (seen
    firsthand: it never returned "Inspector" for this Oil Rig company even
    though it's a real, selectable position in-game). Rather than silently
    dropping a position no automatic source reports, this hands control to
    the user: check/uncheck what's already been detected, or type in
    anything missing so it always shows going forward (its cells just read
    "n/a" instead of a percentage until/unless a projection for it is ever
    found).

    self.result ends up as {"visible": [position_name, ...]} - every
    position name known (detected or manually added) that's currently
    checked - or None if cancelled."""

    def __init__(self, master, all_positions, hidden_positions):
        super().__init__(master)
        self.title("Configure Positions")
        self.resizable(False, False)
        self.result = None
        self.transient(master)
        self.grab_set()

        self.positions = list(all_positions)
        hidden = set(hidden_positions or [])
        self.vars = {pos: tk.BooleanVar(value=pos not in hidden) for pos in self.positions}

        ttk.Label(
            self,
            text=(
                "Choose which positions appear as columns on the Position\n"
                "Effectiveness grid. Don't see one that should be here (e.g. a\n"
                "position Tornstats doesn't report)? Add it by name below."
            ),
            justify="left",
        ).pack(anchor="w", padx=12, pady=(12, 8))

        self.rows_frame = ttk.Frame(self)
        self.rows_frame.pack(fill="both", expand=True, padx=12)
        self._render_rows()

        add_row = ttk.Frame(self)
        add_row.pack(fill="x", padx=12, pady=(8, 0))
        ttk.Label(add_row, text="Add position:").pack(side="left")
        self.add_var = tk.StringVar()
        entry = ttk.Entry(add_row, textvariable=self.add_var, width=24)
        entry.pack(side="left", padx=(6, 6))
        entry.bind("<Return>", lambda e: self._add_position())
        ttk.Button(add_row, text="Add", command=self._add_position).pack(side="left")

        btn_row = ttk.Frame(self)
        btn_row.pack(pady=12)
        ttk.Button(btn_row, text="Select All", command=self._select_all).pack(side="left", padx=4)
        ttk.Button(btn_row, text="Save", command=self._save).pack(side="left", padx=4)
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="left", padx=4)

    def _render_rows(self):
        for widget in self.rows_frame.winfo_children():
            widget.destroy()
        cols = 2
        for i, pos in enumerate(self.positions):
            ttk.Checkbutton(self.rows_frame, text=pos, variable=self.vars[pos]).grid(
                row=i // cols, column=i % cols, sticky="w", padx=6, pady=2
            )

    def _add_position(self):
        name = self.add_var.get().strip()
        self.add_var.set("")
        if not name or name in self.positions:
            return
        self.positions.append(name)
        self.vars[name] = tk.BooleanVar(value=True)
        self._render_rows()

    def _select_all(self):
        for var in self.vars.values():
            var.set(True)

    def _save(self):
        self.result = {"visible": [pos for pos in self.positions if self.vars[pos].get()]}
        self.destroy()


class EmployeeInfoCard(tk.Toplevel):
    """
    Small popup shown when a Name cell is clicked on the Position Efficiency
    tab: Name, ID (tId, labeled "ID" in the GUI only), Last Online, Work
    Stats (Manual Labor/Endurance/Intelligence), Current Position, Current
    Eff., and Total Eff. for that one employee.

    Non-modal by design (no grab_set()) - clicking another employee's Name
    cell while a card is already open just opens/updates a card rather than
    being blocked, so multiple employees can be looked at side by side.

    record is the raw Employee_Effectiveness row dict for the employee, or
    None if the lookup by tId came up empty (stale cache / sheet edited
    externally since the last Position Efficiency refresh) - a short
    explanatory message is shown instead of a broken/blank card in that case.
    """

    def __init__(self, master, record: dict | None):
        super().__init__(master)
        self.resizable(False, False)
        self.transient(master)

        name = (record or {}).get("name") or "Employee"
        self.title(f"{name} - Info")

        content = ttk.Frame(self, padding=16)
        content.pack(fill="both", expand=True)

        if record is None:
            ttk.Label(
                content,
                text=(
                    "No current data found for this employee.\n"
                    "Try Refresh from Sheet or Update Employee Efficiency."
                ),
                justify="left",
                wraplength=280,
            ).pack(anchor="w")
            ttk.Button(content, text="Close", command=self.destroy).pack(pady=(16, 0))
            self._center_on_screen()
            return

        # A scrollable body - the canvas/window are sized to the body's own
        # required size below (after the fields are laid out), rather than
        # a fixed guessed box, so there's no empty space next to the labels.
        # Scrolling only actually engages if the content ever outgrows
        # MAX_BODY_HEIGHT - future-proofing for more fields being added
        # later while keeping today's short field list compact.
        MAX_BODY_HEIGHT = 260
        canvas = tk.Canvas(content, highlightthickness=0)
        scrollbar = ttk.Scrollbar(content, orient="vertical", command=canvas.yview)
        body = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)

        for row_index, (label, value) in enumerate(build_employee_info_card_fields(record)):
            ttk.Label(body, text=label, font=("Segoe UI", 9, "bold")).grid(
                row=row_index, column=0, sticky="w", padx=(0, 12), pady=3
            )
            ttk.Label(body, text=value).grid(row=row_index, column=1, sticky="w", pady=3)

        ttk.Button(content, text="Close", command=self.destroy).pack(pady=(12, 0))

        # Now that the fields are laid out, size the canvas/scroll window to
        # match the body's actual required size instead of a hardcoded box.
        body.update_idletasks()
        body_width = body.winfo_reqwidth()
        body_height = body.winfo_reqheight()
        canvas.configure(width=body_width, height=min(body_height, MAX_BODY_HEIGHT))
        canvas.itemconfig(window_id, width=body_width)
        if body_height > MAX_BODY_HEIGHT:
            scrollbar.pack(side="right", fill="y")

        self._center_on_screen()

    def _center_on_screen(self):
        self.update_idletasks()
        # winfo_width()/height() report 1 until the window is actually
        # mapped by the OS window manager, which update_idletasks() alone
        # doesn't guarantee - the requested size is reliable regardless of
        # mapping state, so use that for the centering math instead.
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        x = (self.winfo_screenwidth() - width) // 2
        y = (self.winfo_screenheight() - height) // 2
        self.geometry(f"+{x}+{y}")


class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Torn - Company Assistant")

        self.settings = Settings.load()
        # Company settings, including API keys, are DPAPI-encrypted for this user.
        self.companies = companies_mod.load_companies()
        self._migrate_legacy_primary_company()
        self.status_var = tk.StringVar(value="Ready.")
        # Active company selection - name of a company in self.companies.
        self.company_var = tk.StringVar(value=self.settings.last_selected_company or "")
        self.company_combos = []

        self._build_menu()
        self._build_layout()

        # Track the most recent non-maximized geometry so it can be restored
        # even when the application is closed while maximized.
        self._last_normal_geometry = None

        self._restore_window_state()
        self.bind("<Configure>", self._remember_normal_geometry, add="+")
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)

        self._refresh_all(silent=True)

    def _migrate_legacy_primary_company(self):
        """One-time migration for installs from before Companies existed:
        if the old top-level Torn key + Sheet ID are set but no company has
        been added yet, turn them into the first company entry so existing
        data keeps working, and clear the legacy fields so they can't be
        confused with (or silently overwritten by) a new company later."""
        if self.companies or not (self.settings.torn_api_key and self.settings.google_sheet_id):
            return
        self.companies = [{
            "name": "Primary company",
            "torn_api_key": self.settings.torn_api_key,
            "tornstats_api_key": self.settings.tornstats_api_key,
            "google_sheet_id": self.settings.google_sheet_id,
            "google_sheet_name": self.settings.google_sheet_name,
        }]
        try:
            companies_mod.save_companies(self.companies)
        except Exception:
            pass  # non-fatal - worst case the migration is retried next launch
        self.settings.torn_api_key = ""
        self.settings.tornstats_api_key = ""
        self.settings.google_sheet_id = ""
        self.settings.google_sheet_name = ""
        self.settings.save()
        messagebox.showinfo(
            "Companies updated",
            "Your existing Torn API key and Sheet were moved into the new "
            "Companies list in Settings as \"Primary company\". Add any "
            "further companies there the same way.",
        )

    def _restore_window_state(self):
        """
        Restore the previous window size, position, and maximized state.

        On the first run, or if the saved state cannot be read, the window
        opens maximized. This is normal Windows maximization rather than
        borderless fullscreen, so the user can still restore and resize it.
        """
        self.update_idletasks()
        self.minsize(900, 600)

        try:
            with WINDOW_STATE_FILE.open("r", encoding="utf-8") as file:
                saved_state = json.load(file)
        except (OSError, ValueError, TypeError):
            saved_state = None

        if not isinstance(saved_state, dict):
            # First application run.
            self.after_idle(lambda: self.state("zoomed"))
            return

        geometry = saved_state.get("geometry")
        if self._valid_window_geometry(geometry):
            self.geometry(geometry)
            self._last_normal_geometry = geometry
        else:
            self._set_default_window_geometry()

        if saved_state.get("maximized", False):
            self.after_idle(lambda: self.state("zoomed"))


    def _set_default_window_geometry(self):
        """
        Set a safe fallback normal-window geometry.

        This is mainly used if the saved state file exists but contains invalid
        geometry. A true first run is opened maximized by _restore_window_state().
        """
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        window_width = max(900, min(1500, int(screen_width * 0.85)))
        window_height = max(600, min(950, int(screen_height * 0.85)))

        x = max(0, (screen_width - window_width) // 2)
        y = max(0, (screen_height - window_height) // 2)

        geometry = f"{window_width}x{window_height}+{x}+{y}"
        self.geometry(geometry)
        self._last_normal_geometry = geometry


    def _valid_window_geometry(self, geometry):
        """
        Check that a saved Tk geometry string is usable and that at least part
        of the window remains visible on the current monitor arrangement.
        """
        if not isinstance(geometry, str):
            return False

        try:
            size, x_text, y_text = geometry.replace("-", "+-").split("+", 2)
            width_text, height_text = size.split("x", 1)

            width = int(width_text)
            height = int(height_text)
            x = int(x_text)
            y = int(y_text)
        except (TypeError, ValueError):
            return False

        if width < 900 or height < 600:
            return False

        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        # Keep at least 100 pixels accessible on the current display.
        if x > screen_width - 100:
            return False
        if y > screen_height - 100:
            return False
        if x + width < 100:
            return False
        if y + height < 100:
            return False

        return True


    def _remember_normal_geometry(self, event=None):
        """
        Remember size and position changes only while the window is in its
        normal, resizable state.

        Windows reports the maximized dimensions through geometry(), so ignoring
        Configure events while maximized preserves the user's last normal size.
        """
        if event is not None and event.widget is not self:
            return

        try:
            if self.state() == "normal":
                geometry = self.geometry()
                if self._valid_window_geometry(geometry):
                    self._last_normal_geometry = geometry
        except tk.TclError:
            pass


    def _save_window_state(self):
        """Save the current normal geometry and whether the window is maximized."""
        try:
            current_state = self.state()
        except tk.TclError:
            current_state = "normal"

        maximized = current_state == "zoomed"

        if current_state == "normal":
            geometry = self.geometry()
            if self._valid_window_geometry(geometry):
                self._last_normal_geometry = geometry

        geometry = self._last_normal_geometry

        if not self._valid_window_geometry(geometry):
            geometry = None

        state_data = {
            "geometry": geometry,
            "maximized": maximized,
        }

        try:
            WINDOW_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

            temporary_file = WINDOW_STATE_FILE.with_suffix(".tmp")
            with temporary_file.open("w", encoding="utf-8") as file:
                json.dump(state_data, file, indent=2)

            temporary_file.replace(WINDOW_STATE_FILE)
        except OSError:
            # Window persistence is convenient but should never prevent closing.
            pass


    def _on_window_close(self):
        """Save the window state and then close the application."""
        self._save_window_state()
        self.destroy()

    # ----------------------------------------------------------legal docs---
    def display_legal_window(self, title: str, relative_path: str):
        """
        Creates a standalone scrollable UI display modal window.
        It handles reading the text content internally from the file path.
        """
        popup = Toplevel(self)
        popup.title(title)
        popup.geometry("600x500")

        # Build the scrollable text widget with automated word-wrapping
        text_box = scrolledtext.ScrolledText(
            popup, 
            wrap="word", 
            font=("Segoe UI", 10), 
            padx=15, 
            pady=15
            )
        text_box.pack(expand=True, fill="both")

        # 🟢 FIX: Fetch the raw markdown string safely right here using the string path
        text_content = get_legal_text(relative_path)

        # Inject the text variable string directly into the active layout framework
        text_box.insert(END, text_content)

        # Freeze editing layers so application users cannot manually alter text strings
        text_box.config(state="disabled")

    def show_privacy(self):
        """Passes the strict file path string to the window generator."""
        # 🟢 FIX: Only pass the exact path string, not loaded text data
        self.display_legal_window("TCA - Privacy Policy", "legal/TCA_Privacy_Policy.docx")

    def show_terms(self):
        """Passes the strict file path string to the window generator."""
        # 🟢 FIX: Only pass the exact path string, not loaded text data
        self.display_legal_window("TCA - Terms of Service", "legal/TCA_Terms_of_Service.docx")

    # --------------------------------------------------------- tree utils --
    def _make_scrollable_tree(self, parent, columns, show="headings", height=15):
        """Wraps a Treeview with vertical + horizontal scrollbars in its own
        frame, so content that doesn't fit the current window size is still
        reachable by scrolling instead of requiring a manual window resize.
        Returns (frame, tree) - pack/grid the frame, use the tree as usual."""
        frame = ttk.Frame(parent)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        tree = ttk.Treeview(frame, columns=columns, show=show, height=height)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        return frame, tree
    
    def _make_scrollable_grid(self, parent):
        """Canvas + inner Frame with both scrollbars, for a spreadsheet-style
        grid of arbitrary widgets. A plain ttk.Treeview can't do this - it only
        supports whole-row tag colors, not independent per-cell backgrounds,
        which the Position Effectiveness tab needs. Returns (frame, canvas,
        inner) - pack/grid the frame, then .grid() widgets into inner."""
        frame = ttk.Frame(parent)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        canvas = tk.Canvas(frame, highlightthickness=0, background="#ffffff")
        vsb = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        hsb = ttk.Scrollbar(
            frame,
            orient="horizontal",
            command=lambda *args: scroll_canvas_xview(canvas, *args),
        )
        canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        inner = tk.Frame(canvas, background="#ffffff")
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner.bind("<Configure>", _on_inner_configure)

        def _on_canvas_configure(event):
            canvas.itemconfig(window_id, width=max(event.width, inner.winfo_reqwidth()))
        canvas.bind("<Configure>", _on_canvas_configure)

        # Mouse wheel only scrolls this grid while the cursor is actually over
        # it, via bind_all/unbind_all on enter/leave - a global permanent bind
        # would hijack scrolling on every other tab's Treeview too.
        def _on_mousewheel(event):
            canvas.yview_scroll(-1 * (event.delta // 120), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        return frame, canvas, inner

    def _make_scrollable_canvas(self, parent):
        frame = ttk.Frame(parent)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        canvas = tk.Canvas(frame, highlightthickness=0, background="#ffffff")
        vsb = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        hsb = ttk.Scrollbar(
            frame,
            orient="horizontal",
            command=lambda *args: scroll_canvas_xview(canvas, *args),
        )
        canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        def _on_mousewheel(event):
            canvas.yview_scroll(-1 * (event.delta // 120), "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        return frame, canvas

    def _autosize_columns(self, tree, min_width=60, max_width=420, padding=24):
        """Fits each column's width to its widest visible content (header or
        cell), so columns aren't wider than needed or clipping text - the
        Excel-style 'auto-fit' behavior. Runs after every populate/sort so
        it stays correct as data changes."""
        f = tkfont.nametofont("TkDefaultFont")
        columns = list(tree["columns"])
        has_tree_col = tree.cget("show") in ("tree headings", "tree")
        if has_tree_col:
            columns = ["#0"] + columns
        for col in columns:
            header_text = tree.heading(col)["text"] or ""
            widest = f.measure(str(header_text))
            for item in tree.get_children():
                value = tree.item(item, "text") if col == "#0" else tree.set(item, col)
                widest = max(widest, f.measure(str(value)))
            width = max(min_width, min(widest + padding, max_width))
            tree.column(col, width=width)

    # ------------------------------------------------------------- menu --
    def _build_menu(self):
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Run Snapshot Now", command=self.run_snapshot)
        file_menu.add_command(label="Refresh From Sheet", command=self.refresh_from_sheet)
        file_menu.add_command(label="TOS", command=self.show_terms)
        file_menu.add_command(label="Privacy Policy", command=self.show_privacy)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)
        self.config(menu=menubar)

    # ----------------------------------------------------------- layout --
    def _build_layout(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        # -- Top-level tabs --
        self.overview_tab = ttk.Frame(self.notebook)
        self.employees_parent_tab = ttk.Frame(self.notebook)
        self.stock_trends_parent_tab = ttk.Frame(self.notebook)
        self.settings_tab = ttk.Frame(self.notebook)

        self.notebook.add(self.overview_tab, text="Overview")
        self.notebook.add(self.employees_parent_tab, text="Employees")
        self.notebook.add(self.stock_trends_parent_tab, text="Stock & Profit Trends")
        self.notebook.add(self.settings_tab, text="Settings")

        # -- Employees sub-notebook: Employee Overview + Position Efficiency (nested) --
        self.employees_notebook = ttk.Notebook(self.employees_parent_tab)
        self.employees_notebook.pack(fill="both", expand=True)

        self.employee_overview_tab = ttk.Frame(self.employees_notebook)
        self.position_efficiency_parent_tab = ttk.Frame(self.employees_notebook)

        self.employees_notebook.add(self.employee_overview_tab, text="Employee Overview")
        self.employees_notebook.add(self.position_efficiency_parent_tab, text="Position Efficiency")

        # -- Position Efficiency sub-notebook: Base + Total Effectiveness Projections --
        self.position_efficiency_notebook = ttk.Notebook(self.position_efficiency_parent_tab)
        self.position_efficiency_notebook.pack(fill="both", expand=True)

        self.base_effectiveness_tab = ttk.Frame(self.position_efficiency_notebook)
        self.total_effectiveness_tab = ttk.Frame(self.position_efficiency_notebook)

        self.position_efficiency_notebook.add(self.base_effectiveness_tab, text="Base Effectiveness Projections")
        self.position_efficiency_notebook.add(self.total_effectiveness_tab, text="Total Effectiveness Projections")

        # -- Stock & Profit Trends sub-notebook: Stock + Company Trends --
        self.stock_trends_notebook = ttk.Notebook(self.stock_trends_parent_tab)
        self.stock_trends_notebook.pack(fill="both", expand=True)

        self.stock_sub_tab = ttk.Frame(self.stock_trends_notebook)
        self.company_trends_tab = ttk.Frame(self.stock_trends_notebook)

        self.stock_trends_notebook.add(self.stock_sub_tab, text="Stock")
        self.stock_trends_notebook.add(self.company_trends_tab, text="Company Trends")

        # -- Build content for each tab --
        self._build_overview_tab()
        self._build_employees_tab()
        self._build_base_effectiveness_tab()
        self._build_total_effectiveness_placeholder()
        self._build_stock_tab()
        self._build_trends_tab()
        self._build_settings_tab()

        status_bar = ttk.Label(self, textvariable=self.status_var, anchor="w", relief="sunken")
        status_bar.pack(fill="x", side="bottom")

    # --------------------------------------------------------- overview --
    def _add_company_selector(self, parent):
        combo = ttk.Combobox(
            parent,
            textvariable=self.company_var,
            values=company_selector_values(self.companies),
            state="readonly",
            width=30,
        )
        combo.pack(side="left", padx=8)
        combo.bind("<<ComboboxSelected>>", lambda event: self._on_company_selected())
        self.company_combos.append(combo)
        return combo

    def _update_company_selectors(self):
        selector_values = company_selector_values(self.companies)
        for combo in self.company_combos:
            combo["values"] = selector_values
        if self.company_var.get() not in selector_values:
            self.company_var.set(selector_values[0])

    def _build_overview_tab(self):
        top = ttk.Frame(self.overview_tab)
        top.pack(fill="x", padx=10, pady=10)

        ttk.Button(top, text="Run Snapshot Now", command=self.run_snapshot).pack(side="left")
        ttk.Button(top, text="Run Everything", command=self.run_everything).pack(side="left")
        ttk.Button(top, text="Refresh From Sheet", command=self.refresh_from_sheet).pack(side="left", padx=6)

        # Company selector: pick which configured company to view.
        selector_values = company_selector_values(self.companies)
        if self.settings.last_selected_company and self.settings.last_selected_company in selector_values:
            self.company_var.set(self.settings.last_selected_company)
        else:
            self.company_var.set(selector_values[0])
        self.company_combo = self._add_company_selector(top)

        frame, self.overview_tree = self._make_scrollable_tree(
            self.overview_tab, columns=("value",), show="tree headings", height=20
        )
        self.overview_tree.heading("#0", text="Metric")
        self.overview_tree.heading("value", text="Latest Value")
        self.overview_tree.bind("<Configure>", self._center_overview_columns)
        frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.after_idle(self._center_overview_columns)

    def _center_overview_columns(self, event=None):
        """Keep the Metric/Latest Value divider centered as the table sizes."""
        width = event.width if event is not None else self.overview_tree.winfo_width()
        if width <= 1:
            return
        metric_width = width // 2
        value_width = max(60, width - metric_width)
        self.overview_tree.column("#0", width=metric_width, stretch=False)
        self.overview_tree.column("value", width=value_width, stretch=False)

    def _populate_overview(self):
        self.overview_tree.delete(*self.overview_tree.get_children())
        records = self._safe_read("Company_History")
        if not records:
            self.overview_tree.insert("", "end", text="No data yet", values=("Run a snapshot to populate this",))
            self._center_overview_columns()
            return
        latest = max(records, key=lambda r: int(r.get("timestamp") or 0))
        capacity = latest.get("employees_capacity", "")
        rank_keys = {"rank_by_income", "rank_total_in_type", "rank_percentile", "rank_trend"}
        for key, value in latest.items():
            if key == "employees_capacity" or key in rank_keys:
                continue  # employees_capacity merges below; rank_* merges into one Health Score row
            if key == "employees_hired":
                self.overview_tree.insert(
                    "", "end", text="employees",
                    values=(f"{value}/{capacity}",),
                )
                continue
            self.overview_tree.insert("", "end", text=pretty_label(key), values=(format_field(key, value, "Company_History"),))

        rank, total, percentile, trend = (
            latest.get("rank_by_income"), latest.get("rank_total_in_type"),
            latest.get("rank_percentile"), latest.get("rank_trend"),
        )
        if rank not in (None, ""):
            arrow = {"up": " \u25b2", "down": " \u25bc", "same": " \u2192"}.get(str(trend).strip().lower(), "")
            percentile_text = f", top {100 - float(percentile):.0f}%" if percentile not in (None, "") else ""
            self.overview_tree.insert(
                "", "end", text="health score (rank by income)",
                values=(f"#{rank} of {total}{percentile_text}{arrow}",),
            )
        self._center_overview_columns()

    # -------------------------------------------------------- employees --
    def _build_employees_tab(self):
        top = ttk.Frame(self.employee_overview_tab)
        top.pack(fill="x", padx=10, pady=10)
        ttk.Button(top, text="Update Employee Efficiency", command=self.run_employee_efficiency).pack(side="left")
        ttk.Button(top, text="Refresh from Sheet", command=self.refresh_from_sheet).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Columns...", command=self._choose_employee_columns).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Configure Positions...", command=self._configure_positions).pack(side="left", padx=(6, 0))
        self._add_company_selector(top)

        ttk.Label(top, text="Filter:").pack(side="left", padx=(16, 4))
        self.employee_filter_var = tk.StringVar(value="")
        filter_entry = ttk.Entry(top, textvariable=self.employee_filter_var, width=20)
        filter_entry.pack(side="left")
        filter_entry.bind("<KeyRelease>", lambda e: self._apply_employee_filter())

        legend = ttk.Label(
            self.employee_overview_tab,
            text="Current Effectiveness is from Torn API, every other eff. column is originated from Tornstats Calculations.  "
                 "Position locks apply on the next Employee Efficiency run.  "
                 "\n\u26a0 Misplaced = Assigned Position differs from current position.  "
                 "\u26a0 Wage Eff. Outlier = paid 50%+ worse than the roster average per effectiveness point.  ",
            foreground="#555555",
        )
        legend.pack(fill="x", padx=10)

        saved_columns = [
            "time_since_last_action" if key == "last_action_ts" else key
            for key in self.settings.employee_visible_columns
        ]

        valid_column_keys = {
            key for _, key in EMPLOYEE_TABLE_COLUMNS
        }

        saved_columns = [
            key for key in saved_columns
            if key in valid_column_keys
        ]

        if saved_columns:
            # Preserve the exact saved left-to-right order.
            self.employee_visible_columns = saved_columns
        else:
            # On first use, follow EMPLOYEE_TABLE_COLUMNS order while selecting
            # only the default visible columns.
            self.employee_visible_columns = [
                key
                for _, key in EMPLOYEE_TABLE_COLUMNS
                if key in DEFAULT_VISIBLE_EMPLOYEE_COLUMNS
            ]
        frame, self.employees_canvas, self.employees_grid = self._make_scrollable_grid(
            self.employee_overview_tab
        )
        frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._employee_labels = {key: header for header, key in EMPLOYEE_TABLE_COLUMNS}
        self._employee_labels[POSITION_LOCK_COLUMN] = "Lock"
        self._employee_records_cache = []
        self._employee_lock_vars = []
        self._employee_sort_column = None
        self._employee_sort_reverse = False

    def _employee_row_values(self, row, columns):
        return [format_employee_field(column, row) for column in columns]

    def _employee_row_tags(self, row):
        tags = []
        if str(row.get("misplaced_flag", "")).strip().lower() in ("true", "1", "yes"):
            tags.append("misplaced")
        if str(row.get("wage_efficiency_flag", "")).strip().lower() in ("true", "1", "yes"):
            tags.append("wage_outlier")
        return tuple(tags)

    def _populate_employees(self):
        records = self._safe_read("Employee_Effectiveness")
        if not records:
            # Fall back to the plain Employees tab (always written by
            # run_snapshot()) so there's still something to look at for a
            # company that hasn't had an Employee Efficiency run yet.
            records = self._safe_read("Employees")
        self._employee_records_cache = records
        self._apply_employee_filter()

    def _apply_employee_filter(self):
        query = (self.employee_filter_var.get() if hasattr(self, "employee_filter_var") else "").strip().lower()
        records = self._employee_records_cache
        if query:
            records = [r for r in records if query in str(r.get("name", "")).lower()]
        if self._employee_sort_column:
            self._sort_employees(
                self._employee_sort_column,
                self._employee_sort_reverse,
                toggle=False,
            )
        else:
            self._render_employee_rows(records)

    def _render_employee_rows(self, records):
        for widget in self.employees_grid.winfo_children():
            widget.destroy()

        self._employee_lock_vars = []
        columns = list(self.employee_visible_columns or ["name"])
        if "current_position" in columns:
            columns.insert(columns.index("current_position") + 1, POSITION_LOCK_COLUMN)
        formatted_rows = [self._employee_row_values(row, columns) for row in records]
        footer_values = {
            column: employee_footer_total(records, column)
            for column in columns
            if column in EMPLOYEE_FOOTER_TOTAL_COLUMNS
        }
        widths = {}
        for index, column in enumerate(columns):
            header_width = max(len(line) for line in self._employee_labels[column].split("\n"))
            value_width = max([0] + [len(str(values[index])) for values in formatted_rows])
            value_width = max(value_width, len(footer_values.get(column, "")))
            widths[column] = max(9, min(24, max(header_width, value_width)))
        if POSITION_LOCK_COLUMN in widths:
            widths[POSITION_LOCK_COLUMN] = 6

        for column_index, column in enumerate(columns):
            arrow = ""
            if column == self._employee_sort_column:
                arrow = " ▼" if self._employee_sort_reverse else " ▲"
            tk.Button(
                self.employees_grid,
                text=self._employee_labels[column] + arrow,
                command=lambda col=column: self._sort_employees(col, False),
                font=("TkDefaultFont", 9, "bold"),
                background="#d9d9d9",
                activebackground="#c9c9c9",
                relief="ridge",
                borderwidth=1,
                width=widths[column],
                padx=4,
                pady=3,
            ).grid(row=0, column=column_index, sticky="nsew")

        for row_index, (row, values) in enumerate(zip(records, formatted_rows), start=1):
            tags = self._employee_row_tags(row)
            if "wage_outlier" in tags:
                base_background = "#f8d7da"
            elif "misplaced" in tags:
                base_background = "#fff3cd"
            else:
                base_background = "#ffffff"
            for column_index, (column, value) in enumerate(zip(columns, values)):
                if column == POSITION_LOCK_COLUMN:
                    background, foreground = employee_cell_style("current_position", row, base_background)
                    lock_var = tk.BooleanVar(value=self._is_employee_position_locked(row))
                    self._employee_lock_vars.append(lock_var)
                    tk.Checkbutton(
                        self.employees_grid,
                        variable=lock_var,
                        command=lambda record=row, var=lock_var: self._set_employee_position_lock(
                            record, var
                        ),
                        background=background,
                        foreground=foreground,
                        activebackground=background,
                        selectcolor="#ffffff",
                        anchor="center",
                        relief="ridge",
                        borderwidth=1,
                        width=widths[column],
                        padx=6,
                        pady=2,
                    ).grid(row=row_index, column=column_index, sticky="nsew")
                    continue
                background, foreground = employee_cell_style(column, row, base_background)
                anchor = "w" if column in LEFT_ALIGNED_EMPLOYEE_COLUMNS else "center"
                tk.Label(
                    self.employees_grid,
                    text=value,
                    background=background,
                    foreground=foreground,
                    anchor=anchor,
                    relief="ridge",
                    borderwidth=1,
                    width=widths[column],
                    padx=6,
                    pady=4,
                ).grid(row=row_index, column=column_index, sticky="nsew")

        footer_row = len(records) + 1
        for column_index, column in enumerate(columns):
            if column in EMPLOYEE_FOOTER_TOTAL_COLUMNS:
                value = footer_values[column]
            elif column == "name":
                value = "Totals"
            else:
                value = ""
            tk.Label(
                self.employees_grid,
                text=value,
                background="#d9e2f3",
                foreground="#1f1f1f",
                anchor="w" if column == "name" else "center",
                font=("TkDefaultFont", 9, "bold"),
                relief="ridge",
                borderwidth=1,
                width=widths[column],
                padx=6,
                pady=4,
            ).grid(row=footer_row, column=column_index, sticky="nsew")

    def _sort_employees(self, col, reverse, toggle=True):
        if toggle and col == self._employee_sort_column:
            reverse = not self._employee_sort_reverse
        elif toggle:
            reverse = False
        sort_key_field = "last_action_ts" if col == "time_since_last_action" else col
        query = (self.employee_filter_var.get() if hasattr(self, "employee_filter_var") else "").strip().lower()
        records = self._employee_records_cache
        if query:
            records = [r for r in records if query in str(r.get("name", "")).lower()]
        if col == POSITION_LOCK_COLUMN:
            data = sorted(records, key=self._is_employee_position_locked, reverse=reverse)
        else:
            try:
                data = sorted(records, key=lambda r: float(r.get(sort_key_field, 0) or 0), reverse=reverse)
            except (TypeError, ValueError):
                data = sorted(records, key=lambda r: str(r.get(sort_key_field, "")), reverse=reverse)
        self._employee_sort_column = col
        self._employee_sort_reverse = reverse
        self._render_employee_rows(data)

    def _locked_employee_ids(self):
        company = self._active_company()
        if not company:
            return set()
        return {str(employee_id) for employee_id in (company.get("locked_employee_ids") or [])}

    def _is_employee_position_locked(self, row):
        return employee_position_is_locked(row, self._locked_employee_ids())

    def _set_employee_position_lock(self, row, lock_var):
        company = self._active_company()
        employee_id = str(row.get("tId") or "")
        current_position = str(row.get("current_position") or row.get("position") or "").strip()
        locked = bool(lock_var.get())
        if not company or not employee_id or not current_position:
            lock_var.set(False)
            return

        previous_locked_ids = self._locked_employee_ids()
        locked_ids = set(previous_locked_ids)
        if locked:
            locked_ids.add(employee_id)
        else:
            locked_ids.discard(employee_id)
        company["locked_employee_ids"] = sorted(locked_ids)
        try:
            companies_mod.save_companies(self.companies)
        except Exception:
            company["locked_employee_ids"] = sorted(previous_locked_ids)
            lock_var.set(not locked)
            messagebox.showerror("Position lock", "The position lock could not be saved.")
            return
        if self._employee_sort_column == POSITION_LOCK_COLUMN:
            self.after_idle(self._apply_employee_filter)

    def _choose_employee_columns(self):
        dialog = ColumnPickerDialog(self, self.employee_visible_columns)
        self.wait_window(dialog)
        if dialog.result is not None:
            self.employee_visible_columns = dialog.result
            self._apply_employee_filter()
            self.settings.employee_visible_columns = list(self.employee_visible_columns)
            try:
                self.settings.save()
            except Exception:
                messagebox.showerror(
                    "Column preferences",
                    "The selected columns were applied but could not be saved.",
                )

    def _configure_positions(self):
        company = self._active_company()
        if not company:
            messagebox.showinfo("No company selected", "Select or add a company first.")
            return
        positions = company.get("last_known_positions") or []
        if not positions:
            # Fall back to whatever positions are visible in the currently
            # loaded roster, in case a Snapshot has run but Employee
            # Efficiency hasn't (which is what populates last_known_positions).
            positions = sorted({r.get("current_position") or r.get("position") for r in self._employee_records_cache} - {None, ""})
        if not positions:
            messagebox.showinfo(
                "Configure Positions",
                "No positions detected yet for this company - run a Snapshot or "
                "Employee Efficiency pass first so positions can be read from the roster.",
            )
            return
        dialog = PositionCapacitiesDialog(
            self, positions, company.get("position_capacities") or {}, company.get("position_priority_order") or []
        )
        self.wait_window(dialog)
        if dialog.result and dialog.result != "global":
            capacities = dict(company.get("position_capacities") or {})
            capacities.update(dialog.result["capacities"])
            company["position_capacities"] = capacities
            company["position_priority_order"] = dialog.result["priority_order"]
            company["last_known_positions"] = positions
            try:
                companies_mod.save_companies(self.companies)
                messagebox.showinfo("Position Capacities", "Saved.")
            except Exception:
                messagebox.showerror("Save failed", "Could not save companies to companies.json")

    # ------------------------------------------ base effectiveness projections --
    def _build_base_effectiveness_tab(self):
        top = ttk.Frame(self.base_effectiveness_tab)
        top.pack(fill="x", padx=10, pady=10)
        ttk.Button(top, text="Update Employee Efficiency", command=self.run_employee_efficiency).pack(side="left")
        ttk.Button(top, text="Refresh from Sheet", command=self.refresh_from_sheet).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Configure Positions", command=self._configure_position_efficiency_positions).pack(side="left", padx=(6, 0))
        self._add_company_selector(top)
        ttk.Label(
            top,
            text="Tornstats-projected work-stats effectiveness for every employee and position. "
                 "\nClick a column heading to sort. \nRead straight from Position_Efficiency "
                 "(Update Employee Efficiency to update from Spreadsheet).",
            foreground="#555555",
            wraplength=460, justify="left",
        ).pack(side="left", padx=10)

        frame, self.base_effectiveness_canvas = self._make_scrollable_canvas(
            self.base_effectiveness_tab
        )
        frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._position_efficiency_records_cache = []
        self._employee_info_lookup = {}
        self._position_efficiency_columns = ()
        self._position_efficiency_labels = {}
        self._position_efficiency_sort_column = None
        self._position_efficiency_sort_reverse = False

    # ----------------------------------------- total effectiveness projections --
    def _build_total_effectiveness_placeholder(self):
        """Empty placeholder for the Total Effectiveness Projections sub-tab.
        Wired with real data in Phase 2."""
        ttk.Label(
            self.total_effectiveness_tab,
            text="Total Effectiveness Projections — coming in Phase 2.",
            foreground="#888888",
        ).pack(padx=20, pady=20, anchor="nw")

    def _configure_position_efficiency_positions(self):
        company = self._active_company()
        if not company:
            messagebox.showinfo("No company selected", "Select or add a company first.")
            return
        all_positions = sorted(set(getattr(self, "_position_efficiency_all_positions", []) or []) | set(company.get("last_known_positions") or []))
        if not all_positions:
            messagebox.showinfo(
                "Configure Positions",
                "No positions detected yet for this company - update Employee Efficiency first so "
                "positions can be read from Tornstats, then Configure Positions to add any it missed.",
            )
            return
        dialog = PositionVisibilityDialog(self, all_positions, company.get("position_efficiency_hidden_positions") or [])
        self.wait_window(dialog)
        if dialog.result:
            visible = set(dialog.result["visible"])
            company["last_known_positions"] = sorted(set(all_positions) | visible)
            company["position_efficiency_hidden_positions"] = sorted(set(all_positions) - visible)
            try:
                companies_mod.save_companies(self.companies)
            except Exception:
                messagebox.showerror("Save failed", "Could not save companies to companies.json")
                return
            self._populate_position_efficiency()

    def _populate_position_efficiency(self, sheet_name="Position_Efficiency", canvas=None):
        """Populate the position efficiency grid from *sheet_name*.

        *canvas* selects which scrollable canvas to render into; defaults to
        self.base_effectiveness_canvas. Phase 2 will pass
        self.total_effectiveness_canvas when populating the second sub-tab."""
        canvas = canvas if canvas is not None else self.base_effectiveness_canvas
        records = self._safe_read(sheet_name)
        self._position_efficiency_records_cache = records

        # Independent lookup for the employee info card popup - read fresh
        # from Employee_Effectiveness (not the Employees tab's cache/fallback,
        # which uses a different position-key name and lacks work stats).
        # Position_Efficiency and Employee_Effectiveness are always written
        # together by the same run_employee_efficiency() call, so if a
        # Position_Efficiency row exists here, its matching
        # Employee_Effectiveness row is guaranteed to exist too.
        info_records = self._safe_read("Employee_Effectiveness")
        self._employee_info_lookup = {
            str(record.get("tId")): record
            for record in info_records
            if record.get("tId") not in (None, "")
        }

        if not records:
            canvas.delete("all")
            canvas.create_text(
                10,
                10,
                text="No data yet - update Employee Efficiency first.",
                anchor="nw",
                fill="#000000",
            )
            canvas.configure(scrollregion=(0, 0, 320, 40))
            self._position_efficiency_all_positions = []
            return

        meta_cols = {"tId", "name", "current_position"}
        detected_positions = [key for key in records[0] if key not in meta_cols]
        company = self._active_company() or {}
        known_positions = sorted(set(detected_positions) | set(company.get("last_known_positions") or []))
        self._position_efficiency_all_positions = known_positions
        hidden = set(company.get("position_efficiency_hidden_positions") or [])
        position_names = [position for position in known_positions if position not in hidden]

        self._position_efficiency_columns = (
            "name", "current_position", "current_efficiency", *position_names
        )
        self._position_efficiency_labels = {
            "name": "Name",
            "current_position": "Current Position",
            "current_efficiency": "Current Eff.",
        }
        self._sort_position_efficiency(
            self._position_efficiency_sort_column or "name",
            self._position_efficiency_sort_reverse,
            toggle=False,
            canvas=canvas,
        )

    def _render_position_efficiency_rows(self, records, canvas=None):
        """Render *records* into *canvas* (defaults to self.base_effectiveness_canvas).
        Phase 2 passes self.total_effectiveness_canvas for the second sub-tab."""
        canvas = canvas if canvas is not None else self.base_effectiveness_canvas
        canvas.delete("all")
        columns = self._position_efficiency_columns
        labels = self._position_efficiency_labels
        body_font = tkfont.nametofont("TkDefaultFont")
        header_font = tkfont.Font(
            root=self,
            family=body_font.actual("family"),
            size=body_font.actual("size"),
            weight="bold",
        )
        widths = {}
        for column in columns:
            header_width = header_font.measure(labels.get(column, column)) + 24
            if column == "name":
                content_width = max(
                    [0] + [body_font.measure(str(record.get("name", ""))) for record in records]
                ) + 20
                widths[column] = max(100, min(240, max(header_width, content_width)))
            elif column == "current_position":
                content_width = max(
                    [0] + [body_font.measure(str(record.get("current_position") or "")) for record in records]
                ) + 20
                widths[column] = max(130, min(240, max(header_width, content_width)))
            else:
                widths[column] = max(100, min(190, header_width))

        header_height = 34
        row_height = 32
        x = 0
        for column_index, column in enumerate(columns):
            arrow = ""
            if column == self._position_efficiency_sort_column:
                arrow = " ▼" if self._position_efficiency_sort_reverse else " ▲"
            width = widths[column]
            tag = f"position_efficiency_header_{column_index}"
            canvas.create_rectangle(
                x, 0, x + width, header_height,
                fill="#d9d9d9", outline="#a0a0a0", width=1, tags=(tag,),
            )
            canvas.create_text(
                x + width / 2,
                header_height / 2,
                text=labels.get(column, column) + arrow,
                font=header_font,
                fill="#000000",
                tags=(tag,),
            )
            canvas.tag_bind(
                tag,
                "<Button-1>",
                lambda event, col=column, cv=canvas: self._sort_position_efficiency(col, False, canvas=cv),
            )
            x += width

        for row_index, record in enumerate(records, start=1):
            current_position = record.get("current_position") or ""
            employee_tid = record.get("tId")
            x = 0
            y = header_height + (row_index - 1) * row_height
            for column in columns:
                width = widths[column]
                if column == "current_efficiency":
                    value = record.get(current_position, "")
                else:
                    value = record.get(column, "")
                if column in {"name", "current_position"}:
                    text = "" if value in (None, "") else str(value)
                    background, foreground = "#ffffff", "#000000"
                    anchor = "w"
                else:
                    text, background, foreground = position_efficiency_score_style(value)
                    anchor = "center"
                is_current_position = column == current_position
                border_width = 3 if is_current_position else 1
                cell_tags = ()
                if column == "name":
                    # Clickable - opens the employee info card popup.
                    cell_tags = (f"pe_name_cell_{row_index}",)
                canvas.create_rectangle(
                    x,
                    y,
                    x + width,
                    y + row_height,
                    fill=background,
                    outline="#333333" if is_current_position else "#b0b0b0",
                    width=border_width,
                    tags=cell_tags,
                )
                canvas.create_text(
                    x + 6 if anchor == "w" else x + width / 2,
                    y + row_height / 2,
                    text=text,
                    fill=foreground,
                    font=body_font,
                    anchor="w" if anchor == "w" else "center",
                    tags=cell_tags,
                )
                if column == "name":
                    tag = cell_tags[0]
                    canvas.tag_bind(
                        tag,
                        "<Button-1>",
                        lambda event, tid=employee_tid: self._show_employee_info_card(tid),
                    )
                    canvas.tag_bind(tag, "<Enter>", lambda event: canvas.configure(cursor="hand2"))
                    canvas.tag_bind(tag, "<Leave>", lambda event: canvas.configure(cursor=""))
                x += width

        total_width = sum(widths.values())
        total_height = header_height + len(records) * row_height
        canvas.configure(scrollregion=(0, 0, total_width, total_height))

    def _show_employee_info_card(self, tid):
        record = self._employee_info_lookup.get(str(tid)) if tid not in (None, "") else None
        EmployeeInfoCard(self, record)

    def _sort_position_efficiency(self, column, reverse, toggle=True, canvas=None):
        """Sort and re-render the position efficiency grid.

        *canvas* is forwarded to _render_position_efficiency_rows; defaults to
        self.base_effectiveness_canvas. Phase 2 passes the total tab's canvas."""
        if toggle and column == self._position_efficiency_sort_column:
            reverse = not self._position_efficiency_sort_reverse
        elif toggle and column in {"name", "current_position"}:
            reverse = False

        records = sorted(
            self._position_efficiency_records_cache,
            key=lambda record: position_efficiency_sort_value(record, column),
            reverse=reverse,
        )
        self._position_efficiency_sort_column = column
        self._position_efficiency_sort_reverse = reverse
        self._render_position_efficiency_rows(records, canvas=canvas)

    # ------------------------------------------------------------ stock --
    def _build_stock_tab(self):
        top = ttk.Frame(self.stock_sub_tab)
        top.pack(fill="x", padx=10, pady=10)
        ttk.Button(top, text="Refresh", command=self.refresh_from_sheet).pack(side="left")
        self._add_company_selector(top)
        ttk.Label(
            top,
            text="Shows stock information (in-stock, sold, cost, price, created) \nand a chart of total sold worth over time. ",
            foreground="#555555",
            wraplength=460, justify="left",
        ).pack(side="left", padx=10)

        paned = ttk.PanedWindow(self.stock_sub_tab, orient="vertical")
        paned.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        columns = ["name", "in_stock", "delta_in_stock", "cost", "price", "sold_amount", "sold_worth", "created"]
        column_labels = {"delta_in_stock": "in_stock_difference"}
        tree_frame, self.stock_tree = self._make_scrollable_tree(paned, columns=columns, show="headings", height=10)
        for col in columns:
            self.stock_tree.heading(col, text=pretty_label(column_labels.get(col, col)))
            self.stock_tree.column(col, width=130, anchor="center")
        paned.add(tree_frame, weight=1)

        chart_frame = ttk.Frame(paned)
        paned.add(chart_frame, weight=2)
        self.stock_fig = Figure(figsize=(6, 3), dpi=100)
        self.stock_ax = self.stock_fig.add_subplot(111)
        self.stock_canvas = FigureCanvasTkAgg(self.stock_fig, master=chart_frame)
        self.stock_canvas.get_tk_widget().pack(fill="both", expand=True)

    def _populate_stock(self):
        self.stock_tree.delete(*self.stock_tree.get_children())
        records = self._safe_read("Stock_History")
        if not records:
            return

        # latest row per stock name
        latest_by_name = {}
        for row in records:
            name = row.get("name")
            ts = int(row.get("timestamp") or 0)
            if name not in latest_by_name or ts > int(latest_by_name[name].get("timestamp", 0)):
                latest_by_name[name] = row

        columns = self.stock_tree["columns"]
        for row in latest_by_name.values():
            self.stock_tree.insert(
                "", "end",
                values=[format_field(c, row.get(c, ""), "Stock_History") for c in columns],
            )
        self._autosize_columns(self.stock_tree)

        # chart: total sold_worth over time across all stocks
        totals_by_ts = {}
        label_by_ts = {}
        for row in records:
            ts = int(row.get("timestamp") or 0)
            worth = float(row.get("sold_worth") or 0)
            totals_by_ts[ts] = totals_by_ts.get(ts, 0) + worth
            label_by_ts[ts] = row.get("date") or str(ts)

        self.stock_ax.clear()
        if totals_by_ts:
            sorted_ts = sorted(totals_by_ts.keys())
            xs = [label_by_ts[t] for t in sorted_ts]
            ys = [totals_by_ts[t] for t in sorted_ts]
            self.stock_ax.plot(xs, ys, marker="o")
            self.stock_ax.set_title("Total sold worth per snapshot")
            self.stock_ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _pos: format_money(v)))
            self.stock_ax.tick_params(axis="x", rotation=45, labelsize=7)
        self.stock_fig.tight_layout()
        self.stock_canvas.draw()

    # ----------------------------------------------------------- trends --
    def _build_trends_tab(self):
        top = ttk.Frame(self.company_trends_tab)
        top.pack(fill="x", padx=10, pady=10)

        ttk.Label(top, text="Metric:").pack(side="left")
        self.trend_metric_var = tk.StringVar(value="company_funds")
        self.trend_metric_combo = ttk.Combobox(top, textvariable=self.trend_metric_var, state="readonly", width=30)
        self.trend_metric_combo.pack(side="left", padx=6)
        self.trend_metric_combo.bind("<<ComboboxSelected>>", lambda e: self._draw_trend())
        ttk.Button(top, text="Refresh", command=self.refresh_from_sheet).pack(side="left", padx=6)
        self._add_company_selector(top)

        chart_frame = ttk.Frame(self.company_trends_tab)
        chart_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.trend_fig = Figure(figsize=(8, 4), dpi=100)
        self.trend_ax = self.trend_fig.add_subplot(111)
        self.trend_canvas = FigureCanvasTkAgg(self.trend_fig, master=chart_frame)
        self.trend_canvas.get_tk_widget().pack(fill="both", expand=True)

    def _populate_trends(self):
        self._company_history_cache = self._safe_read("Company_History")
        numeric_cols = [
            "employees_hired", "daily_income", "daily_profit", "weekly_income", "weekly_profit",
            "company_funds", "popularity", "efficiency", "environment", "total_wage",
            "avg_employee_effectiveness", "daily_stockcost",
            "avg_daily_profit_7day", "avg_daily_income_7day",
        ]
        # Dropdown shows space-separated labels; keep a label->raw-field-name
        # mapping so chart data lookups still use the real column name.
        self._trend_metric_label_to_key = {pretty_label(c): c for c in numeric_cols}
        labels = list(self._trend_metric_label_to_key.keys())
        self.trend_metric_combo["values"] = labels
        if self.trend_metric_var.get() not in labels and labels:
            self.trend_metric_var.set(labels[0])
        self._draw_trend()

    def _draw_trend(self):
        records = getattr(self, "_company_history_cache", [])
        records = sorted(records, key=lambda r: int(r.get("timestamp") or 0))
        label = self.trend_metric_var.get()
        metric = getattr(self, "_trend_metric_label_to_key", {}).get(label, label)
        self.trend_ax.clear()
        if records and metric:
            xs = [r.get("date") or r.get("timestamp") for r in records]
            try:
                ys = [float(r.get(metric) or 0) for r in records]
            except ValueError:
                ys = []
            if ys:
                self.trend_ax.plot(xs, ys, marker="o", color="#2b7a3f")
                self.trend_ax.set_title(f"{label} over time")
                if metric in MONEY_FIELDS["Company_History"]:
                    self.trend_ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _pos: format_money(v)))
                self.trend_ax.tick_params(axis="x", rotation=45, labelsize=7)
        self.trend_fig.tight_layout()
        self.trend_canvas.draw()

    # --------------------------------------------------------- settings --
    def _build_settings_tab(self):
        frame = ttk.Frame(self.settings_tab)
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Account-level settings only. Torn API keys and Sheet IDs live
        # exclusively in the Companies list below - there is no separate
        # "primary company" typed in here anymore, so there's no way to
        # accidentally overwrite one company's key while trying to add
        # another one.
        self._settings_vars = {
            "snapshot_interval_minutes": tk.StringVar(value=str(self.settings.snapshot_interval_minutes)),
        }

        labels = {
            "snapshot_interval_minutes": "Auto-refresh interval (minutes, 0 = off)",
        }

        row = 0
        for key, label in labels.items():
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=6)
            entry = ttk.Entry(frame, textvariable=self._settings_vars[key], width=50)
            entry.grid(row=row, column=1, sticky="we", pady=6, padx=6)
            row += 1

        frame.columnconfigure(1, weight=1)

        ttk.Button(frame, text="Save Securely", command=self._save_settings).grid(row=row, column=0, pady=16, sticky="w")
        ttk.Button(frame, text="Sign in with Google", command=self._sign_in_google).grid(row=row, column=1, pady=16, sticky="w")

        # -- Companies management area --
        row += 1
        legacy_btn_row = ttk.Frame(frame)
        legacy_btn_row.grid(row=row, column=0, columnspan=2, pady=(0, 8), sticky="w")
        ttk.Button(legacy_btn_row, text="Sort Existing Rows (One-Time)", command=self._resort_existing_history).pack(side="left", padx=(8, 0))
        row += 1
        sep = ttk.Separator(frame, orient="horizontal")
        sep.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(12, 8))
        row += 1
        ttk.Label(
            frame,
            text="Companies - each needs its own Torn API key. Leave the Sheet blank to "
                 "auto-create one, or select a company and use Choose Google Sheet.\n"
                 "Every company here gets snapshotted when you click \"Run Snapshot Now\".",
            justify="left",
        ).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        self._companies_listbox = tk.Listbox(frame, height=6)
        self._companies_listbox.grid(row=row, column=1, sticky="we", pady=6)
        self._companies_listbox.bind("<<ListboxSelect>>", lambda e: self._on_companies_listbox_select())
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=row, column=2, sticky="n")
        ttk.Button(btn_frame, text="Add", command=self._add_company).pack(fill="x")
        ttk.Button(btn_frame, text="Edit", command=self._edit_company).pack(fill="x", pady=6)
        ttk.Button(btn_frame, text="Choose Google Sheet", command=self._choose_google_sheet).pack(fill="x")
        ttk.Button(btn_frame, text="Remove", command=self._remove_company).pack(fill="x", pady=6)
        ttk.Button(btn_frame, text="Test Connection", command=self._test_connection).pack(fill="x")
        frame.columnconfigure(1, weight=1)
        self._refresh_companies_list()

    def _save_settings(self):
        s = self.settings
        try:
            s.snapshot_interval_minutes = int(self._settings_vars["snapshot_interval_minutes"].get().strip() or 0)
        except ValueError:
            s.snapshot_interval_minutes = 0
        s.save()
        self.set_status("Settings saved securely for this Windows user.")
        messagebox.showinfo("Saved", "Settings were encrypted for this Windows user.")

    def _sign_in_google(self):
        self._save_settings()
        self.set_status("Waiting for Google sign-in in your browser...")

        def worker():
            try:
                authorize_google()
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Google sign-in failed", str(exc)))
                self.after(0, lambda: self.set_status("Google sign-in failed."))
                return
            self.after(0, lambda: messagebox.showinfo("Google connected", "Google access was authorized and saved securely."))
            self.after(0, lambda: self.set_status("Google connected."))

        threading.Thread(target=worker, daemon=True).start()

    def _resort_existing_history(self):
        if not self.companies:
            messagebox.showinfo("No companies configured", "Add a company first.")
            return
        names = ", ".join(c.get("name", "Unnamed") for c in self.companies)
        if not messagebox.askyesno(
            "Sort existing rows?",
            "This is a ONE-TIME migration: it rewrites Company_History, "
            "Stock_History, and Director_Efficiency for every configured "
            f"company ({names}) so existing rows read newest-at-top, "
            "matching how new snapshots are now written.\n\n"
            "This does not change any data values, only row order. Continue?",
        ):
            return
        self.set_status("Sorting existing history rows...")

        def worker():
            from app.collector import resort_existing_history
            results = resort_existing_history(self.companies, base_settings=self.settings)

            def finish():
                lines = []
                for name, per_tab in results:
                    if per_tab is None:
                        lines.append(f"{name}: could not reach this company's Sheet")
                        continue
                    parts = ", ".join(
                        f"{tab.replace('_', ' ')}: {count if count is not None else 'failed'} row(s)"
                        for tab, count in per_tab.items()
                    )
                    lines.append(f"{name}: {parts}")
                self.set_status("Sort complete.")
                messagebox.showinfo("Sort Results", "\n".join(lines))
            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def _test_connection(self):
        self._save_settings()
        sheet_id, sheet_name = self._active_company_sheet_override()
        if not sheet_id:
            messagebox.showinfo(
                "No Sheet ID yet",
                "This company has no Google Sheet ID configured - one will be auto-created "
                "(named after the company) the first time you run a Snapshot or Employee "
                "Efficiency pass for it. Nothing to test until then.",
            )
            return
        try:
            sheets = SheetsClient(sheet_id=sheet_id, sheet_name=sheet_name)
            messagebox.showinfo("Connected", f"Connected to sheet:\n{sheets.url}")
        except Exception as e:
            messagebox.showerror("Connection failed", str(e))

    def _on_companies_listbox_select(self):
        """Selecting a company in the Settings list also drives the Overview
        selector, so 'Test Connection' always tests whatever's highlighted."""
        sel = self._companies_listbox.curselection()
        if not sel or sel[0] >= len(self.companies):
            return
        name = self.companies[sel[0]].get("name", "Unnamed")
        self.company_var.set(name)
        self.settings.last_selected_company = name
        self.settings.save()

    def _on_company_selected(self):
        """Called when company selection changes. Persist it and refresh."""
        sel = self.company_var.get()
        if sel == "(No companies configured)":
            sel = ""
        self.settings.last_selected_company = sel
        self.settings.save()
        self.refresh_from_sheet()

    # ------------------------------------------------------------ actions --
    def set_status(self, text: str):
        self.status_var.set(text)

    def run_snapshot(self):
        """Run a snapshot for every company configured in Settings > Companies."""
        if not self.companies:
            messagebox.showinfo(
                "No companies configured",
                "Add at least one company (Torn API key required, Google Sheet ID optional) in Settings first.",
            )
            return

        self.set_status("Running snapshot...")

        def worker():
            from app.collector import run_company_snapshots, persist_companies
            results = run_company_snapshots(self.companies, base_settings=self.settings)
            # self.companies always comes from companies_mod.load_companies()
            # at startup (or the one-time legacy migration, which already
            # saves itself), so it's always safe to persist here - any
            # auto-created Sheet ID or updated Health Score rank needs to be
            # written back now, or it's silently lost (worse: a blank Sheet
            # ID would auto-create a brand-new Sheet again on every run).
            try:
                persist_companies(self.companies)
            except Exception:
                pass  # non-fatal - snapshot results still get shown either way

            def finish():
                messages = []
                for name, res in results:
                    if res.ok:
                        messages.append(f"{name}: OK ({res.employee_count} employees, {res.stock_count} stock)")
                    else:
                        messages.append(f"{name}: FAIL - {res.message}")
                self._on_snapshot_done(results[0][1] if results else None)
                messagebox.showinfo("Snapshot Results", "\n".join(messages))
            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def _on_snapshot_done(self, result):
        # result may be None when multiple results were shown directly
        if not result:
            self.set_status("Snapshot(s) complete.")
            self.refresh_from_sheet()
            return
        if result.ok:
            self.set_status(
                f"Snapshot OK: {result.company_name} "
                f"({result.employee_count} employees, {result.stock_count} stock rows)."
            )
            self.refresh_from_sheet()
        else:
            self.set_status(f"Snapshot failed: {result.message}")
            messagebox.showerror("Snapshot failed", result.message)

    def run_employee_efficiency(self):
        """Run an Employee Efficiency pass for every company configured in
        Settings > Companies. Needs each company to have both a Torn API
        key and a Tornstats API key - companies missing the latter report
        back a failure message rather than being silently skipped."""
        if not self.companies:
            messagebox.showinfo(
                "No companies configured",
                "Add at least one company (Torn API key required, Google Sheet ID optional) in Settings first.",
            )
            return

        self.set_status("Running employee efficiency...")

        def worker():
            from app.collector import run_employee_efficiency_for_companies, persist_companies
            results = run_employee_efficiency_for_companies(self.companies, base_settings=self.settings)
            try:
                persist_companies(self.companies)
            except Exception:
                pass

            def finish():
                messages = []
                for name, res in results:
                    if res.ok:
                        line = f"{name}: OK ({res.employee_count} employees, {res.misplaced_count} misplaced)"
                        if getattr(res, "verification_note", ""):
                            line += f"\n    \u26a0 {res.verification_note}"
                        messages.append(line)
                    else:
                        messages.append(f"{name}: FAIL - {res.message}")
                self.set_status("Employee efficiency update complete.")
                self.refresh_from_sheet()
                messagebox.showinfo("Employee Efficiency Results", "\n".join(messages))
            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def run_everything(self):
        """Run both a Snapshot and an Employee Efficiency pass for every
        configured company, in one click."""
        if not self.companies:
            messagebox.showinfo(
                "No companies configured",
                "Add at least one company (Torn API key required, Google Sheet ID optional) in Settings first.",
            )
            return

        self.set_status("Running snapshot + employee efficiency...")

        def worker():
            from app.collector import run_everything_for_companies, persist_companies
            results = run_everything_for_companies(self.companies, base_settings=self.settings)
            try:
                persist_companies(self.companies)
            except Exception:
                pass

            def finish():
                messages = []
                for name, res in results:
                    if res.ok:
                        s, e = res.snapshot, res.employee_efficiency
                        parts = [f"Snapshot OK ({s.employee_count} employees, {s.stock_count} stock)" if s.ok else f"Snapshot FAIL - {s.message}"]
                        if e.ok:
                            eff_part = f"Efficiency OK ({e.misplaced_count} misplaced)"
                            if getattr(e, "verification_note", ""):
                                eff_part += f" [\u26a0 {e.verification_note}]"
                            parts.append(eff_part)
                        else:
                            parts.append(f"Efficiency FAIL - {e.message}")
                        messages.append(f"{name}: " + "; ".join(parts))
                    else:
                        messages.append(f"{name}: {res.message}")
                self.set_status("Run Everything complete.")
                self.refresh_from_sheet()
                messagebox.showinfo("Run Everything Results", "\n".join(messages))
            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def refresh_from_sheet(self):
        self.set_status("Refreshing from sheet...")

        def worker():
            self.after(0, lambda: self._refresh_all(silent=False))

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_all(self, silent: bool):
        try:
            self._populate_overview()
            self._populate_employees()
            self._populate_position_efficiency()
            self._populate_stock()
            self._populate_trends()
            if not silent:
                self.set_status("Refreshed.")
            # refresh company selector values in case companies.json changed externally
            try:
                self._update_company_selectors()
            except Exception:
                pass
        except Exception as e:
            self.set_status(f"Refresh failed: {e}")

    # ---------------------------------------------------------------- io --
    def _active_company(self) -> dict | None:
        """Return the actual company dict (same object as in self.companies,
        so mutating it and calling companies_mod.save_companies(self.companies)
        persists it) for the currently selected company, or None."""
        sel = (self.company_var.get() or "").strip()
        for c in self.companies:
            if c.get("name") == sel:
                return c
        return self.companies[0] if self.companies else None

    def _active_company_sheet_override(self) -> tuple:
        """Return (sheet_id, sheet_name) for the currently selected company (or empty strings)."""
        sel = (self.company_var.get() or "").strip()
        for c in self.companies:
            if c.get("name") == sel:
                return c.get("google_sheet_id", ""), c.get("google_sheet_name", "")
        # Nothing selected yet - fall back to the first configured company, if any.
        if self.companies:
            c = self.companies[0]
            return c.get("google_sheet_id", ""), c.get("google_sheet_name", "")
        return "", ""

    def _safe_read(self, title: str) -> list[dict]:
        sheet_id, sheet_name = self._active_company_sheet_override()
        if not sheet_id:
            return []
        try:
            sheets = SheetsClient(
                sheet_id=sheet_id,
                sheet_name=sheet_name,
            )
            return sheets.read_records(title)
        except Exception:
            return []

    # ------------------------- companies UI helpers -------------------------
    def _refresh_companies_list(self):
        try:
            self._companies_listbox.delete(0, tk.END)
        except Exception:
            return
        for c in self.companies:
            self._companies_listbox.insert(tk.END, c.get("name", "Unnamed"))
        # update selector values as well
        try:
            self._update_company_selectors()
        except Exception:
            pass

    def _choose_google_sheet(self):
        sel = self._companies_listbox.curselection()
        if not sel:
            messagebox.showinfo("Select one", "Select a company first.")
            return
        company = self.companies[sel[0]]
        self.set_status(f"Choose a Google Sheet for {company.get('name', 'company')} in your browser...")

        def worker():
            try:
                sheet_id = pick_google_sheet()
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Google Picker failed", str(exc)))
                self.after(0, lambda: self.set_status("Google Sheet selection failed."))
                return

            def finish():
                if company not in self.companies:
                    return
                company["google_sheet_id"] = sheet_id
                companies_mod.save_companies(self.companies)
                idx = self.companies.index(company)
                self._refresh_companies_list()
                self._companies_listbox.selection_set(idx)
                self._companies_listbox.see(idx)
                self.set_status(f"Google Sheet selected for {company.get('name', 'company')}.")
                messagebox.showinfo("Google Sheet selected", "The selected Sheet is now assigned to this company.")

            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def _add_company(self):
        name = simpledialog.askstring("Company name", "Name for company", parent=self)
        if not name:
            return
        torn = simpledialog.askstring("Torn API key", "Company's limited-access Torn API key (required)", parent=self, show="*")
        if not (torn or "").strip():
            messagebox.showwarning("Torn API key required", "Each company needs its own Torn API key.")
            return
        torn_public = simpledialog.askstring(
            "Torn Public API key",
            "Company's Public Torn API key (optional - only needed for the Health Score "
            "ranking, which reads other companies' public listings)",
            parent=self, show="*",
        )
        tornstats = simpledialog.askstring("Tornstats API key", "Tornstats API key (optional)", parent=self, show="*")
        sheet_name = simpledialog.askstring("Google Sheet name", "Optional display name", parent=self)
        entry = {
            "name": name.strip(),
            "torn_api_key": torn.strip(),
            "torn_public_api_key": (torn_public or "").strip(),
            "tornstats_api_key": (tornstats or "").strip(),
            "google_sheet_id": "",
            "google_sheet_name": (sheet_name or "").strip(),
        }
        self.companies.append(entry)
        try:
            companies_mod.save_companies(self.companies)
        except Exception:
            messagebox.showerror("Save failed", "Could not save companies to companies.json")
        self._refresh_companies_list()
        new_index = len(self.companies) - 1
        self._companies_listbox.selection_set(new_index)
        self._companies_listbox.see(new_index)
        self._choose_google_sheet()

    def _edit_company(self):
        sel = self._companies_listbox.curselection()
        if not sel:
            messagebox.showinfo("Select one", "Select a company to edit")
            return
        idx = sel[0]
        c = self.companies[idx]
        name = simpledialog.askstring("Company name", "Name for company", initialvalue=c.get("name", ""), parent=self)
        if not name:
            return
        torn = simpledialog.askstring("Torn API key", "Company's limited-access Torn API key (required)", initialvalue=c.get("torn_api_key", ""), parent=self, show="*")
        if not (torn or "").strip():
            messagebox.showwarning("Torn API key required", "Each company needs its own Torn API key.")
            return
        torn_public = simpledialog.askstring(
            "Torn Public API key",
            "Company's Public Torn API key (optional - only needed for the Health Score "
            "ranking, which reads other companies' public listings)",
            initialvalue=c.get("torn_public_api_key", ""), parent=self, show="*",
        )
        tornstats = simpledialog.askstring("Tornstats API key", "Tornstats API key (optional)", initialvalue=c.get("tornstats_api_key", ""), parent=self, show="*")
        sheet_name = simpledialog.askstring("Google Sheet name", "Optional display name", initialvalue=c.get("google_sheet_name", ""), parent=self)
        c.update({
            "name": name.strip(),
            "torn_api_key": torn.strip(),
            "torn_public_api_key": (torn_public or "").strip(),
            "tornstats_api_key": (tornstats or "").strip(),
            "google_sheet_name": (sheet_name or "").strip(),
        })
        try:
            companies_mod.save_companies(self.companies)
        except Exception:
            messagebox.showerror("Save failed", "Could not save companies to companies.json")
        self._refresh_companies_list()

    def _remove_company(self):
        sel = self._companies_listbox.curselection()
        if not sel:
            messagebox.showinfo("Select one", "Select a company to remove")
            return
        idx = sel[0]
        name = self.companies[idx].get("name", "Unnamed")
        if not messagebox.askyesno("Confirm", f"Remove company '{name}'?"):
            return
        self.companies.pop(idx)
        try:
            companies_mod.save_companies(self.companies)
        except Exception:
            messagebox.showerror("Save failed", "Could not save companies to companies.json")
        self._refresh_companies_list()


def launch():
    app = MainWindow()
    style = ttk.Style(app)
    # The native Windows theme ('vista'/'winnative') draws column headings
    # via the OS header control, which has a fixed single-line height that
    # clips any second line regardless of padding. 'clam' draws headings
    # itself and actually expands to fit multi-line text - needed for the
    # Employees tab's full v2 column set, several of which use \n headers.
    if "clam" in style.theme_names():
        style.theme_use("clam")
    style.configure("Treeview", rowheight=24)
    style.configure("Treeview.Heading", padding=(6, 8, 6, 8))
    app.mainloop()
