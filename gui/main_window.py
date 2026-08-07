"""
Desktop GUI for the Knotty Oil Tracker.
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

project_root = str(Path(__file__).resolve().parent.parent)
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
from app.scheduled_collection import run_scheduled_collection
from app.windows_scheduler import install_task, remove_task, repair_task, task_status
from app import companies as companies_mod

WINDOW_STATE_FILE = Path.home() / ".torn_company_assistant_window.json"
CLICK_FOR_MORE_INFO_SUFFIX = " (click for more info)"


def calculate_popup_geometry(
    parent_x: int,
    parent_y: int,
    parent_width: int,
    parent_height: int,
    popup_width: int,
    popup_height: int,
    margin: int = 12,
) -> tuple[int, int, int, int]:
    available_width = max(1, parent_width - margin * 2)
    available_height = max(1, parent_height - margin * 2)
    width = min(max(1, popup_width), available_width)
    height = min(max(1, popup_height), available_height)
    x = parent_x + margin + (available_width - width) // 2
    y = parent_y + margin + (available_height - height) // 2
    return width, height, x, y


def place_popup_within_parent(
    popup,
    parent,
    preferred_width: int | None = None,
    preferred_height: int | None = None,
):
    parent.update_idletasks()
    popup.update_idletasks()
    width, height, x, y = calculate_popup_geometry(
        parent.winfo_rootx(),
        parent.winfo_rooty(),
        max(1, parent.winfo_width()),
        max(1, parent.winfo_height()),
        preferred_width or popup.winfo_reqwidth(),
        preferred_height or popup.winfo_reqheight(),
    )
    x_part = f"+{x}" if x >= 0 else str(x)
    y_part = f"+{y}" if y >= 0 else str(y)
    popup.geometry(f"{width}x{height}{x_part}{y_part}")


def open_single_instance_popup(owner, key: str, factory):
    registry = getattr(owner, "_open_popup_windows", None)
    if registry is None:
        registry = {}
        owner._open_popup_windows = registry

    existing = registry.get(key)
    if existing is not None:
        try:
            if existing.winfo_exists():
                existing.deiconify()
                existing.lift()
                existing.focus_force()
                return existing
        except (AttributeError, tk.TclError):
            pass
        registry.pop(key, None)

    popup = factory()
    if popup is None:
        return None
    registry[key] = popup

    def forget_popup(event=None):
        if event is not None and event.widget is not popup:
            return
        if registry.get(key) is popup:
            registry.pop(key, None)

    popup.bind("<Destroy>", forget_popup, add="+")
    return popup


INTEGER_FIELDS = {
    "Stock_History": {"in_stock", "sold_amount", "created"},
}


def _safe_int_ts(val) -> int:
    try:
        return int(float(str(val).replace(",", "").strip()))
    except (TypeError, ValueError):
        return 0


def format_int(value) -> str:
    try:
        return f"{int(round(float(value))):,}"
    except (TypeError, ValueError):
        return str(value)
    

MONEY_FIELDS = {
    "Company_History": {
        "daily_income", "daily_profit", "weekly_income", "weekly_profit", "company_funds",
        "advertising_budget", "total_wage", "daily_stockcost",
        "avg_daily_profit_7day", "avg_daily_income_7day",
        "monthly_income", "monthly_profit", "income_to_reach_10_star",
        "income_buffer_before_9_star", "income_to_reach_next_star",
        "required_weekly_income_to_star_up", "income_to_drop_to_previous_star",
        "rolling_7day_income",
        "rolling_7day_change", "observed_drop_buffer", "observed_next_star_gap",
    },
    "Star_Income_Summary": {"minimum", "p10", "median", "p90", "maximum"},
    "Employees": {"wage"},
    "Employee_Effectiveness": {"wage"},
    "Stock_History": {"cost", "price", "sold_worth", "delta_sold_worth"},
    "Company_Rankings": {"daily_income", "weekly_income"},
}

PERCENT_FIELDS = {
    "Company_History": {"observed_range_position_percent"},
}

TIMESTAMP_FIELDS = {
    "Employees": {"last_action_ts"},
    "Employee_Effectiveness": {"last_action_ts"},
}

SIGNED_FIELDS = {
    "Stock_History": {"delta_in_stock", "delta_sold_amount"},
}

BOOL_FIELDS = {
    "Employee_Effectiveness": {"misplaced_flag", "wage_efficiency_flag"},
    "Stock_History": {"stockout_soon"},
}


def format_money(value) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return str(value)
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.0f}"


def format_star_progress(income_to_reach, income_to_drop, current_star=None) -> str:
    def _number(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    reach = _number(income_to_reach)
    drop = _number(income_to_drop)
    try:
        stars = int(float(current_star))
    except (TypeError, ValueError):
        stars = None

    if reach is not None and reach > 0:
        return f"Need {format_money(reach)}/wk more"
    if reach == 0 and stars is not None and stars < 10:
        return f"In the projected {stars + 1}-star income range"
    if drop is not None and stars is not None and stars > 1:
        return f"{format_money(drop)}/wk buffer before {stars - 1}-star"
    return "Not enough data yet"


def derive_star_progress(ranking_rows: list[dict], summary_rows: list[dict]) -> dict:
    own = next((row for row in ranking_rows if _is_own_company_row(row)), None)
    if not own:
        return {}
    try:
        stars = int(float(own.get("rating")))
        income = float(str(own.get("weekly_income")).replace(",", ""))
    except (TypeError, ValueError):
        return {}

    by_star = {}
    for row in summary_rows:
        try:
            by_star[int(float(row.get("stars")))] = row
        except (TypeError, ValueError):
            continue

    def amount(row, key):
        if not row:
            return None
        try:
            return float(str(row.get(key)).replace(",", ""))
        except (TypeError, ValueError):
            return None

    current_range = by_star.get(stars)
    current_minimum = amount(current_range, "minimum")
    current_maximum = amount(current_range, "maximum")
    next_minimum = amount(by_star.get(stars + 1), "minimum")
    previous_maximum = amount(by_star.get(stars - 1), "maximum")
    result = {
        "rating": own.get("rating"),
        "weekly_income": income,
    }
    if by_star.get(10):
        result["star_10_count"] = by_star[10].get("total_count", "")
    if (
        current_minimum is not None
        and current_maximum is not None
        and current_maximum > current_minimum
    ):
        result["observed_range_position_percent"] = max(
            0.0,
            min(
                100.0,
                (income - current_minimum)
                / (current_maximum - current_minimum)
                * 100,
            ),
        )
    if next_minimum is not None:
        gap = max(0.0, next_minimum - income)
        result["required_weekly_income_to_star_up"] = next_minimum
        result["income_to_reach_next_star"] = gap
        result["observed_next_star_gap"] = gap
    if previous_maximum is not None:
        buffer = max(0.0, income - previous_maximum)
        result["income_to_drop_to_previous_star"] = buffer
        result["observed_drop_buffer"] = buffer
    return result


def format_timestamp(value) -> str:
    try:
        ts = int(float(value))
    except (TypeError, ValueError):
        return str(value)
    if ts <= 0:
        return str(value)
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def format_data_freshness(value, now: int | None = None) -> str:
    try:
        ts = int(float(value))
    except (TypeError, ValueError):
        return "Unknown"
    age = max(0, int(now or time.time()) - ts)
    days = age // 86400
    if days == 0:
        return "Current"
    return f"{days} day{'s' if days != 1 else ''} stale"


def format_time_since(value) -> str:
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
    if getattr(sys, "frozen", False):
        try:
            main_module = sys.modules['__main__']
            bundle_root = Path(main_module.__file__).resolve().parent
        except Exception:
            bundle_root = Path(sys.executable).parent
    else:
        bundle_root = Path(__file__).resolve().parent.parent

    target_path = bundle_root / relative_subpath

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
    try:
        amount = int(round(float(value)))
    except (TypeError, ValueError):
        return str(value)
    if amount > 0:
        return f"+{amount:,}"
    return f"{amount:,}"


def format_bool_flag(value) -> str:
    text = str(value).strip().lower()
    return "\u26a0 Yes" if text in ("true", "1", "yes") else ""


def pretty_label(text: str) -> str:
    labels = {
        "income_buffer_before_9_star": "income to drop to 9 star",
        "income_to_reach_next_star": "income to reach next star",
        "required_weekly_income_to_star_up": "required weekly income to star up",
        "income_to_drop_to_previous_star": "income to drop to previous star",
        "rolling_7day_income": "rolling 7-day income",
        "rolling_7day_coverage": "rolling 7-day coverage",
        "rolling_7day_change": "rolling 7-day change",
        "observed_range_position_percent": "observed range position (%)",
        "observed_drop_buffer": "observed drop buffer",
        "observed_next_star_gap": "observed next-star gap",
    }
    return labels.get(text, text.replace("_", " "))


FIELD_EXPLANATIONS: dict[str, str] = {
    "effectiveness_total": (
        "Torn's total effectiveness for this employee at their CURRENT "
        "position - the sum of all 8 components below."
    ),
    "effectiveness_working_stats": (
        "The portion of effectiveness contributed by this employee's raw "
        "work stats alone."
    ),
    "effectiveness_settled_in": "Effectiveness gained from length of employment.",
    "effectiveness_director_education": "Effectiveness gained from completed education courses.",
    "effectiveness_addiction": "Effectiveness lost to current drug addiction level.",
    "effectiveness_inactivity": "Effectiveness lost to recent inactivity.",
    "effectiveness_management": "Effectiveness gained from company perks and management skill.",
    "effectiveness_book": "Effectiveness gained from company books read.",
    "effectiveness_merits": "Effectiveness gained from company-relevant merits.",
    "projected_efficiency_current_position": "Tornstats' PROJECTED efficiency for raw work stats at CURRENT position.",
    "base_effectiveness_projections": "Tornstats' work-stats-only projected efficiency for every employee at every position.",
    "total_effectiveness_projections": "Base projection plus non-work-stats effectiveness delta applied to every position.",
}

EMPLOYEE_EFFECTIVENESS_EXPLAINED_COLUMNS = (
    "effectiveness_total", "effectiveness_working_stats", "effectiveness_settled_in",
    "effectiveness_director_education", "effectiveness_addiction", "effectiveness_inactivity",
    "effectiveness_management", "effectiveness_book", "effectiveness_merits",
    "projected_efficiency_current_position",
)

EMPLOYEE_INFO_CARD_EXPLAINED_LABELS = {
    "Current Eff.": "projected_efficiency_current_position",
    "Total Eff.": "effectiveness_total",
}


def show_field_explanation(parent, title: str, key: str):
    text = FIELD_EXPLANATIONS.get(key, "No explanation available for this field.")
    messagebox.showinfo(title, text, parent=parent)


def make_info_glyph(parent, key: str, title: str | None = None):
    display_title = title or pretty_label(key).title()
    return tk.Button(
        parent,
        text="\u24d8",
        command=lambda: show_field_explanation(parent, display_title, key),
        relief="flat",
        borderwidth=0,
        font=("TkDefaultFont", 9),
        cursor="hand2",
        padx=2,
        pady=0,
    )


def select_recent_stock_history_rows(records: list[dict], count: int = 7) -> list[dict]:
    rows_by_name: dict[str, list[dict]] = {}
    for row in records:
        name = row.get("name") or ""
        rows_by_name.setdefault(name, []).append(row)

    result: list[dict] = []
    for name in sorted(rows_by_name.keys()):
        newest_first = sorted(
            rows_by_name[name],
            key=lambda r: _safe_int_ts(r.get("timestamp")),
            reverse=True,
        )
        result.extend(newest_first[:count])
    return result


def _is_own_company_row(row: dict) -> bool:
    return str(row.get("is_own_company", "")).strip().lower() in ("true", "1", "yes")


def rank_neighbors_from_sheet_rows(rows: list[dict], span: int = 5) -> list[dict]:
    ordered = sorted(rows, key=lambda r: int(r.get("rank") or 0))
    own_index = next((i for i, r in enumerate(ordered) if _is_own_company_row(r)), None)
    if own_index is None:
        return []
    start = max(0, own_index - span)
    end = min(len(ordered), own_index + span + 1)
    return ordered[start:end]


COMPANY_RANKING_NUMERIC_COLUMNS = {
    "rank", "rating", "daily_income", "weekly_income",
}


def company_ranking_sort_value(row: dict, column: str):
    value = row.get(column)
    if value in (None, ""):
        return None
    if column in COMPANY_RANKING_NUMERIC_COLUMNS:
        try:
            return float(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            return None
    return str(value).strip().casefold()


def sort_company_ranking_rows(
    rows: list[dict], column: str, reverse: bool = False
) -> list[dict]:
    populated = []
    missing = []
    for row in rows:
        value = company_ranking_sort_value(row, column)
        if value is None:
            missing.append(row)
        else:
            populated.append((value, row))
    populated.sort(key=lambda item: item[0], reverse=reverse)
    return [row for _, row in populated] + missing


def format_field(field_name: str, value, tab: str) -> str:
    if field_name in MONEY_FIELDS.get(tab, ()):
        return format_money(value)
    if field_name in PERCENT_FIELDS.get(tab, ()):
        try:
            return f"{float(value):.0f}%"
        except (TypeError, ValueError):
            return str(value)
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


def _readable_text_color(bg):
    bg = bg.lstrip("#")
    r = int(bg[0:2], 16)
    g = int(bg[2:4], 16)
    b = int(bg[4:6], 16)
    brightness = (r*299 + g*587 + b*114) / 1000
    return "#000000" if brightness > 150 else "#ffffff"


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

        self.column_order = [
            key for key in visible_keys
            if key in self.column_labels
        ]

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

        place_popup_within_parent(self, master)

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

        place_popup_within_parent(self, master)

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
                "Effectiveness grid. Don't see one that should be here?\n"
                "Add it by name below."
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

        place_popup_within_parent(self, master)

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
            self._place_within_parent()
            return

        MAX_BODY_HEIGHT = 260
        canvas = tk.Canvas(content, highlightthickness=0)
        scrollbar = ttk.Scrollbar(content, orient="vertical", command=canvas.yview)
        body = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)

        for row_index, (label, value) in enumerate(build_employee_info_card_fields(record)):
            explanation_key = EMPLOYEE_INFO_CARD_EXPLAINED_LABELS.get(label)
            if explanation_key is not None:
                label_cell = ttk.Frame(body)
                ttk.Label(label_cell, text=label, font=("Segoe UI", 9, "bold")).pack(side="left")
                make_info_glyph(label_cell, explanation_key, title=label).pack(side="left", padx=(2, 0))
                label_cell.grid(row=row_index, column=0, sticky="w", padx=(0, 12), pady=3)
            else:
                ttk.Label(body, text=label, font=("Segoe UI", 9, "bold")).grid(
                    row=row_index, column=0, sticky="w", padx=(0, 12), pady=3
                )
            ttk.Label(body, text=value).grid(row=row_index, column=1, sticky="w", pady=3)

        ttk.Button(content, text="Close", command=self.destroy).pack(pady=(12, 0))

        body.update_idletasks()
        body_width = body.winfo_reqwidth()
        body_height = body.winfo_reqheight()
        canvas.configure(width=body_width, height=min(body_height, MAX_BODY_HEIGHT))
        canvas.itemconfig(window_id, width=body_width)
        if body_height > MAX_BODY_HEIGHT:
            scrollbar.pack(side="right", fill="y")

        self._place_within_parent()

    def _place_within_parent(self):
        place_popup_within_parent(self, self.master)


class HealthScoreNeighborsCard(tk.Toplevel):
    COLUMNS = ("rank", "name", "rating", "daily_income", "weekly_income")
    LABELS = {
        "rank": "Rank", "name": "Name", "rating": "Rating",
        "daily_income": "Daily Income", "weekly_income": "Weekly Income",
    }

    def __init__(self, master, neighbor_rows: list[dict]):
        super().__init__(master)
        self.resizable(False, False)
        self.transient(master)
        self.title("Company Ranking Neighbors")

        content = ttk.Frame(self, padding=16)
        content.pack(fill="both", expand=True)

        if not neighbor_rows:
            ttk.Label(
                content,
                text=(
                    "No ranking data found for your company yet.\n"
                    "Try Refresh from Sheet or Run Snapshot Now."
                ),
                justify="left",
                wraplength=280,
            ).pack(anchor="w")
            ttk.Button(content, text="Close", command=self.destroy).pack(pady=(16, 0))
            self._place_within_parent()
            return

        body = ttk.Frame(content)
        body.pack()

        for col_index, column in enumerate(self.COLUMNS):
            ttk.Label(body, text=self.LABELS[column], font=("Segoe UI", 9, "bold")).grid(
                row=0, column=col_index, sticky="w", padx=(0, 12), pady=(0, 4)
            )

        for row_index, row in enumerate(neighbor_rows, start=1):
            is_own = _is_own_company_row(row)
            font = ("Segoe UI", 9, "bold") if is_own else ("Segoe UI", 9)
            for col_index, column in enumerate(self.COLUMNS):
                value = row.get(column, "")
                if column in ("daily_income", "weekly_income"):
                    value = format_money(value)
                ttk.Label(body, text=value, font=font).grid(
                    row=row_index, column=col_index, sticky="w", padx=(0, 12), pady=2
                )

        ttk.Button(content, text="Close", command=self.destroy).pack(pady=(12, 0))
        self._place_within_parent()

    def _place_within_parent(self):
        place_popup_within_parent(self, self.master)


class StarIncomeSummaryCard(tk.Toplevel):
    COLUMNS = (
        "stars", "total_count", "minimum", "median", "maximum",
        "coverage", "freshness", "updated_at",
    )
    LABELS = {
        "stars": "Star Level",
        "total_count": "Company Count",
        "minimum": "Minimum Weekly Income",
        "median": "Median Weekly Income",
        "maximum": "Top Performer Weekly Income",
        "coverage": "Companies Included",
        "freshness": "Data Status",
        "updated_at": "Last Updated (UTC)",
    }
    MONEY_COLUMNS = {"minimum", "median", "maximum"}
    COLUMN_GUIDE = (
        "Star Level: Projected star band represented by the row.\n\n"
        "Company Count: Number of companies assigned to that band.\n\n"
        "Minimum Weekly Income: Weekly Income at the final slot in the band. "
        "This is the income target used for promotion into that star level.\n\n"
        "Median Weekly Income: Middle Weekly Income among companies assigned "
        "to the band.\n\n"
        "Top Performer Weekly Income: Highest Weekly Income assigned to the "
        "band. For the level below a company, this is the competing income "
        "used when calculating its demotion buffer.\n\n"
        "Companies Included: Companies with usable Weekly Income data versus "
        "the total company count.\n\n"
        "Data Status and Last Updated: Whether the values are current and the "
        "UTC time of the latest collection."
    )

    def __init__(self, master, rows: list[dict]):
        super().__init__(master)
        self.title("Projected Weekly Income Ranges by Star Level")
        self.transient(master)
        self.rows = list(rows)
        self._descending = {}

        content = ttk.Frame(self, padding=12)
        content.pack(fill="both", expand=True)
        ttk.Label(
            content,
            text=(
                "Current star counts define fixed slot bands. Each daily 18:10 UTC "
                "snapshot orders every same-type company by Weekly Income and fills those "
                "slots from highest to lowest. Values are empirical indicators, not "
                "guaranteed Torn thresholds."
            ),
            wraplength=1040,
            justify="left",
        ).pack(fill="x", pady=(0, 6))
        ttk.Button(
            content, text="Column Guide", command=self._show_column_guide
        ).pack(anchor="e", pady=(0, 8))

        if not self.rows:
            ttk.Label(
                content,
                text="No range data yet. Run one successful snapshot to populate it.",
            ).pack(anchor="w")
            ttk.Button(content, text="Close", command=self.destroy).pack(pady=16)
            place_popup_within_parent(self, master, 1180, 430)
            return

        frame = ttk.Frame(content)
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            frame, columns=self.COLUMNS, show="headings", height=14
        )
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        widths = {
            "stars": 90, "total_count": 105, "minimum": 165,
            "median": 155, "maximum": 195, "coverage": 135,
            "freshness": 110, "updated_at": 155,
        }
        for column in self.COLUMNS:
            self.tree.heading(
                column,
                text=self.LABELS[column],
                command=lambda key=column: self._sort(key),
            )
            self.tree.column(
                column, width=widths[column], anchor="center", stretch=False
            )
        self._render()
        ttk.Button(content, text="Close", command=self.destroy).pack(pady=(8, 0))
        place_popup_within_parent(self, master, 1180, 430)

    def _show_column_guide(self):
        messagebox.showinfo(
            "Income Range Column Guide", self.COLUMN_GUIDE, parent=self
        )

    @staticmethod
    def _sort_value(row: dict, column: str):
        value = row.get(column, "")
        try:
            return (0, float(value))
        except (TypeError, ValueError):
            return (1, str(value).lower())

    def _sort(self, column: str):
        descending = not self._descending.get(column, False)
        self._descending[column] = descending
        self.rows.sort(
            key=lambda row: self._sort_value(row, column),
            reverse=descending,
        )
        self._render()

    def _render(self):
        self.tree.delete(*self.tree.get_children())
        for row in self.rows:
            values = []
            for column in self.COLUMNS:
                value = row.get(column, "")
                if column in self.MONEY_COLUMNS and value not in (None, ""):
                    value = format_money(value)
                elif column == "coverage" and value not in (None, ""):
                    value = str(value).replace("/", " of ", 1)
                elif column == "updated_at" and value not in (None, ""):
                    value = format_timestamp(value)
                elif column == "freshness":
                    value = format_data_freshness(row.get("updated_at"))
                values.append(value)
            self.tree.insert("", "end", values=values)


class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Torn - Company Assistant")

        self.settings = Settings.load()
        self.companies = companies_mod.load_companies()
        self._migrate_legacy_primary_company()
        self.status_var = tk.StringVar(value="Ready.")
        self.company_var = tk.StringVar(value=self.settings.last_selected_company or "")
        self.company_combos = []

        self._build_menu()
        self._build_layout()

        self._last_normal_geometry = None

        self._restore_window_state()
        self.bind("<Configure>", self._remember_normal_geometry, add="+")
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)

        self._refresh_all(silent=True)

    def _migrate_legacy_primary_company(self):
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
            pass
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
        self.update_idletasks()
        self.minsize(900, 600)

        try:
            with WINDOW_STATE_FILE.open("r", encoding="utf-8") as file:
                saved_state = json.load(file)
        except (OSError, ValueError, TypeError):
            saved_state = None

        if not isinstance(saved_state, dict):
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

        if x > screen_width - 100 or y > screen_height - 100:
            return False
        if x + width < 100 or y + height < 100:
            return False

        return True

    def _remember_normal_geometry(self, event=None):
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
            pass

    def _on_window_close(self):
        self._save_window_state()
        self.destroy()

    def display_legal_window(self, title: str, relative_path: str):
        def create_popup():
            popup = Toplevel(self)
            popup.title(title)
            popup.transient(self)

            text_box = scrolledtext.ScrolledText(
                popup,
                wrap="word",
                font=("Segoe UI", 10),
                padx=15,
                pady=15,
            )
            text_box.pack(expand=True, fill="both")

            text_content = get_legal_text(relative_path)
            text_box.insert(END, text_content)
            text_box.config(state="disabled")
            place_popup_within_parent(popup, self, 600, 500)
            return popup

        return open_single_instance_popup(
            self, f"legal:{relative_path}", create_popup
        )

    def show_privacy(self):
        self.display_legal_window("TCA - Privacy Policy", "legal/TCA_Privacy_Policy.docx")

    def show_terms(self):
        self.display_legal_window("TCA - Terms of Service", "legal/TCA_Terms_of_Service.docx")

    def _make_scrollable_tree(self, parent, columns, show="headings", height=15):
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

    def _build_menu(self):
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Run Snapshot Now", command=self.run_snapshot)
        file_menu.add_command(label="Refresh From Sheet", command=self.refresh_from_sheet)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        legal_menu = tk.Menu(menubar, tearoff=0)
        legal_menu.add_command(label="TOS", command=self.show_terms)
        legal_menu.add_command(label="Privacy Policy", command=self.show_privacy)
        menubar.add_cascade(label="Legal", menu=legal_menu)

        self.config(menu=menubar)

    def _build_layout(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        self.overview_parent_tab = ttk.Frame(self.notebook)
        self.employees_parent_tab = ttk.Frame(self.notebook)
        self.stock_trends_parent_tab = ttk.Frame(self.notebook)
        self.settings_tab = ttk.Frame(self.notebook)

        self.notebook.add(self.overview_parent_tab, text="Overview")
        self.notebook.add(self.employees_parent_tab, text="Employees")
        self.notebook.add(self.stock_trends_parent_tab, text="Stock & Profit Trends")
        self.notebook.add(self.settings_tab, text="Settings")

        self.overview_notebook = ttk.Notebook(self.overview_parent_tab)
        self.overview_notebook.pack(fill="both", expand=True)

        self.overview_tab = ttk.Frame(self.overview_notebook)
        self.company_rankings_tab = ttk.Frame(self.overview_notebook)

        self.overview_notebook.add(self.overview_tab, text="General")
        self.overview_notebook.add(self.company_rankings_tab, text="Company Rankings")

        self.employees_notebook = ttk.Notebook(self.employees_parent_tab)
        self.employees_notebook.pack(fill="both", expand=True)

        self.employee_overview_tab = ttk.Frame(self.employees_notebook)
        self.position_efficiency_parent_tab = ttk.Frame(self.employees_notebook)

        self.employees_notebook.add(self.employee_overview_tab, text="Employee Overview")
        self.employees_notebook.add(self.position_efficiency_parent_tab, text="Position Efficiency")

        self.position_efficiency_notebook = ttk.Notebook(self.position_efficiency_parent_tab)
        self.position_efficiency_notebook.pack(fill="both", expand=True)

        self.base_effectiveness_tab = ttk.Frame(self.position_efficiency_notebook)
        self.total_effectiveness_tab = ttk.Frame(self.position_efficiency_notebook)

        self.position_efficiency_notebook.add(self.base_effectiveness_tab, text="Base Effectiveness Projections")
        self.position_efficiency_notebook.add(self.total_effectiveness_tab, text="Total Effectiveness Projections")

        self.stock_trends_notebook = ttk.Notebook(self.stock_trends_parent_tab)
        self.stock_trends_notebook.pack(fill="both", expand=True)

        self.stock_sub_tab = ttk.Frame(self.stock_trends_notebook)
        self.company_trends_tab = ttk.Frame(self.stock_trends_notebook)

        self.stock_trends_notebook.add(self.stock_sub_tab, text="Stock")
        self.stock_trends_notebook.add(self.company_trends_tab, text="Company Trends")

        self._build_overview_tab()
        self._build_company_rankings_tab()
        self._build_employees_tab()
        self._build_base_effectiveness_tab()
        self._build_total_effectiveness_tab()
        self._build_stock_tab()
        self._build_trends_tab()
        self._build_settings_tab()

        status_bar = ttk.Label(self, textvariable=self.status_var, anchor="w", relief="sunken")
        status_bar.pack(fill="x", side="bottom")

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
        self.overview_tree.bind("<<TreeviewSelect>>", self._on_overview_row_selected)
        frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.after_idle(self._center_overview_columns)

    def _on_overview_row_selected(self, event=None):
        selection = self.overview_tree.selection()
        if not selection:
            return
        row_text = str(
            self.overview_tree.item(selection[0], "text")
        ).strip().lower()
        suffix = CLICK_FOR_MORE_INFO_SUFFIX.lower()
        if row_text.endswith(suffix):
            row_text = row_text[:-len(suffix)].rstrip()
        if row_text == "health score (rank by income)":
            rows = self._safe_read("Company_Rankings")
            neighbors = rank_neighbors_from_sheet_rows(rows)
            open_single_instance_popup(
                self,
                "health_score_neighbors",
                lambda: HealthScoreNeighborsCard(self, neighbors),
            )
        elif row_text == "star 10 count":
            summary = self._safe_read("Star_Income_Summary")
            open_single_instance_popup(
                self,
                "star_income_summary",
                lambda: StarIncomeSummaryCard(self, summary),
            )

    def _center_overview_columns(self, event=None):
        width = event.width if event is not None else self.overview_tree.winfo_width()
        if width <= 1:
            return
        metric_width = width // 2
        value_width = max(60, width - metric_width)
        self.overview_tree.column("#0", width=metric_width, stretch=False)
        self.overview_tree.column("value", width=value_width, stretch=False)

    def _build_company_rankings_tab(self):
        top = ttk.Frame(self.company_rankings_tab)
        top.pack(fill="x", padx=10, pady=10)
        ttk.Button(top, text="Refresh", command=self.refresh_from_sheet).pack(side="left")
        self._add_company_selector(top)
        ttk.Label(
            top,
            text="Every same-type company ranked by weekly income, from your latest snapshot. "
                 "\nYour own company is pinned above the list regardless of scroll position.",
            foreground="#555555",
            wraplength=460, justify="left",
        ).pack(side="left", padx=10)

        locked = ttk.LabelFrame(self.company_rankings_tab, text="Your Company")
        locked.pack(fill="x", padx=10, pady=(0, 6))
        self._company_rankings_locked_labels = {}
        locked_columns = (
            ("rank", "Rank"), ("daily_income", "Daily Income"),
            ("weekly_income", "Weekly Income"),
            ("next_star_gap", "Weekly Income Gap to Next Star"),
            ("range_position", "Observed Range Position"),
            ("previous_star_gap", "Weekly Income Gap to Previous Star"),
            ("daily_change", "Change Since Yesterday"),
        )
        for index, (key, label) in enumerate(locked_columns):
            col_index = index % 5
            row_index = (index // 5) * 2
            ttk.Label(locked, text=label, font=("TkDefaultFont", 9, "bold")).grid(
                row=row_index, column=col_index, sticky="w", padx=10, pady=(6, 0)
            )
            value_label = ttk.Label(locked, text="-")
            value_label.grid(
                row=row_index + 1, column=col_index,
                sticky="w", padx=10, pady=(0, 6),
            )
            self._company_rankings_locked_labels[key] = value_label

        columns = ("rank", "name", "rating", "daily_income", "weekly_income")
        self._company_rankings_rows = []
        self._company_rankings_sort_column = "rank"
        self._company_rankings_sort_reverse = False
        self._company_rankings_heading_labels = {
            column: pretty_label(column).title() for column in columns
        }
        tree_frame, self.company_rankings_tree = self._make_scrollable_tree(
            self.company_rankings_tab, columns=columns, show="headings", height=18
        )
        for column in columns:
            self.company_rankings_tree.heading(
                column,
                text=self._company_rankings_heading_labels[column],
                command=lambda selected=column: self._sort_company_rankings(selected),
            )
            self.company_rankings_tree.column(column, width=130, anchor="center")
        tree_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _render_company_rankings(self, rows: list[dict]):
        tree = self.company_rankings_tree
        tree.delete(*tree.get_children())
        active = self._company_rankings_sort_column
        arrow = " ▼" if self._company_rankings_sort_reverse else " ▲"
        for column in tree["columns"]:
            label = self._company_rankings_heading_labels[column]
            tree.heading(column, text=label + (arrow if column == active else ""))
        for row in rows:
            values = [
                format_field(c, row.get(c, ""), "Company_Rankings")
                for c in tree["columns"]
            ]
            tags = ("own_company",) if _is_own_company_row(row) else ()
            tree.insert("", "end", values=values, tags=tags)
        tree.tag_configure("own_company", font=("TkDefaultFont", 9, "bold"))

    def _sort_company_rankings(self, column: str, toggle: bool = True):
        if column not in self.company_rankings_tree["columns"]:
            return
        if toggle:
            if column == self._company_rankings_sort_column:
                self._company_rankings_sort_reverse = (
                    not self._company_rankings_sort_reverse
                )
            else:
                self._company_rankings_sort_column = column
                self._company_rankings_sort_reverse = False
        ordered = sort_company_ranking_rows(
            self._company_rankings_rows,
            self._company_rankings_sort_column,
            self._company_rankings_sort_reverse,
        )
        self._render_company_rankings(ordered)

    def _populate_company_rankings(self):
        ranking_rows = self._safe_read("Company_Rankings")
        self._company_rankings_rows = list(ranking_rows)
        self._sort_company_rankings(
            self._company_rankings_sort_column, toggle=False
        )

        history_rows = self._safe_read("Company_History")
        latest = dict(
            max(history_rows, key=lambda r: _safe_int_ts(r.get("timestamp")))
        ) if history_rows else {}
        fresh_progress = derive_star_progress(
            ranking_rows, self._safe_read("Star_Income_Summary")
        )
        if fresh_progress:
            latest.update(fresh_progress)
        labels = self._company_rankings_locked_labels
        labels["rank"]["text"] = latest.get("rank_by_income") or "-"
        labels["daily_income"]["text"] = (
            format_money(latest["daily_income"]) if latest.get("daily_income") not in (None, "") else "-"
        )
        labels["weekly_income"]["text"] = (
            format_money(latest["weekly_income"]) if latest.get("weekly_income") not in (None, "") else "-"
        )
        def money_or_dash(*keys):
            for key in keys:
                value = latest.get(key)
                if value not in (None, ""):
                    return format_money(value)
            return "-"

        labels["next_star_gap"]["text"] = money_or_dash(
            "income_to_reach_next_star", "income_to_reach_10_star"
        )
        position = latest.get("observed_range_position_percent")
        try:
            labels["range_position"]["text"] = f"{float(position):.0f}%"
        except (TypeError, ValueError):
            labels["range_position"]["text"] = "-"
        labels["previous_star_gap"]["text"] = money_or_dash(
            "income_to_drop_to_previous_star", "income_buffer_before_9_star"
        )
        labels["daily_change"]["text"] = money_or_dash("rolling_7day_change")

    def _populate_overview(self):
        self.overview_tree.delete(*self.overview_tree.get_children())
        records = self._safe_read("Company_History")
        if not records:
            self.overview_tree.insert("", "end", text="No data yet", values=("Run a snapshot to populate this",))
            self._center_overview_columns()
            return
        latest = dict(max(records, key=lambda r: _safe_int_ts(r.get("timestamp"))))
        fresh_progress = derive_star_progress(
            self._safe_read("Company_Rankings"),
            self._safe_read("Star_Income_Summary"),
        )
        if fresh_progress:
            latest.update(fresh_progress)

        capacity = latest.get("employees_capacity", "")
        rank_keys = {"rank_by_income", "rank_total_in_type", "rank_percentile", "rank_trend"}
        legacy_star_keys = {
            "income_to_reach_10_star", "income_buffer_before_9_star"
        }
        hidden_duplicate_star_keys = {
            "observed_drop_buffer", "observed_next_star_gap"
        }
        try:
            current_star = int(float(latest.get("rating")))
        except (TypeError, ValueError):
            current_star = None

        for key, value in latest.items():
            if (
                key == "employees_capacity"
                or key in rank_keys
                or key in legacy_star_keys
                or key in hidden_duplicate_star_keys
            ):
                continue
            if key in {
                "income_to_reach_next_star",
                "required_weekly_income_to_star_up",
            } and current_star == 10:
                continue
            if key == "income_to_drop_to_previous_star" and current_star == 1:
                continue
            if key == "employees_hired":
                self.overview_tree.insert(
                    "", "end", text="employees",
                    values=(f"{value}/{capacity}",),
                )
                continue

            label = pretty_label(key)
            if current_star is not None:
                if key == "income_to_reach_next_star":
                    label = f"income to reach {current_star + 1} star"
                elif key == "income_to_drop_to_previous_star":
                    label = f"income to drop to {current_star - 1} star"
            if key == "star_10_count":
                label += CLICK_FOR_MORE_INFO_SUFFIX
            self.overview_tree.insert(
                "", "end", text=label,
                values=(format_field(key, value, "Company_History"),),
            )

        rank, total, percentile, trend = (
            latest.get("rank_by_income"), latest.get("rank_total_in_type"),
            latest.get("rank_percentile"), latest.get("rank_trend"),
        )
        if rank not in (None, ""):
            arrow = {"up": " \u25b2", "down": " \u25bc", "same": " \u2192"}.get(str(trend).strip().lower(), "")
            percentile_text = f", top {100 - float(percentile):.0f}%" if percentile not in (None, "") else ""
            self.overview_tree.insert(
                "", "end",
                text="health score (rank by income)" + CLICK_FOR_MORE_INFO_SUFFIX,
                values=(f"#{rank} of {total}{percentile_text}{arrow}",),
            )
        self._center_overview_columns()

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
            self.employee_visible_columns = saved_columns
        else:
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
            header_text = self._employee_labels[column] + arrow
            if column in EMPLOYEE_EFFECTIVENESS_EXPLAINED_COLUMNS:
                header_cell = tk.Frame(self.employees_grid, background="#d9d9d9")
                tk.Button(
                    header_cell,
                    text=header_text,
                    command=lambda col=column: self._sort_employees(col, False),
                    font=("TkDefaultFont", 9, "bold"),
                    background="#d9d9d9",
                    activebackground="#c9c9c9",
                    relief="ridge",
                    borderwidth=1,
                    padx=4,
                    pady=3,
                ).pack(side="left", fill="both", expand=True)
                make_info_glyph(
                    header_cell, column, title=self._employee_labels[column].replace("\n", " ")
                ).pack(side="right", fill="y")
                header_cell.grid(row=0, column=column_index, sticky="nsew")
            else:
                tk.Button(
                    self.employees_grid,
                    text=header_text,
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

    def _build_base_effectiveness_tab(self):
        top = ttk.Frame(self.base_effectiveness_tab)
        top.pack(fill="x", padx=10, pady=10)
        ttk.Button(top, text="Update Employee Efficiency", command=self.run_employee_efficiency).pack(side="left")
        ttk.Button(top, text="Refresh from Sheet", command=self.refresh_from_sheet).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Configure Positions", command=self._configure_position_efficiency_positions).pack(side="left", padx=(6, 0))
        make_info_glyph(top, "base_effectiveness_projections", title="Base Effectiveness Projections").pack(side="left", padx=(6, 0))
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
        self._employee_info_lookup = {}
        self._position_efficiency_states = {}

    def _build_total_effectiveness_tab(self):
        top = ttk.Frame(self.total_effectiveness_tab)
        top.pack(fill="x", padx=10, pady=10)
        ttk.Button(top, text="Update Employee Efficiency", command=self.run_employee_efficiency).pack(side="left")
        ttk.Button(top, text="Refresh from Sheet", command=self.refresh_from_sheet).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Configure Positions", command=self._configure_position_efficiency_positions).pack(side="left", padx=(6, 0))
        make_info_glyph(top, "total_effectiveness_projections", title="Total Effectiveness Projections").pack(side="left", padx=(6, 0))
        self._add_company_selector(top)
        ttk.Label(
            top,
            text="Base projection plus each employee's non-work-stats effectiveness "
                 "(settled in, education, addiction, inactivity, management, book, merits) "
                 "applied to every position. "
                 "\nClick a column heading to sort. \nRead straight from "
                 "Total_Effectiveness_Projections (Update Employee Efficiency to update from Spreadsheet).",
            foreground="#555555",
            wraplength=460, justify="left",
        ).pack(side="left", padx=10)

        frame, self.total_effectiveness_canvas = self._make_scrollable_canvas(
            self.total_effectiveness_tab
        )
        frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

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
            self._populate_position_efficiency(
                sheet_name="Total_Effectiveness_Projections",
                canvas=self.total_effectiveness_canvas,
                key="total",
            )

    def _pe_state(self, key):
        return self._position_efficiency_states.setdefault(key, {
            "records": [],
            "columns": (),
            "labels": {},
            "sort_column": None,
            "sort_reverse": False,
        })

    def _populate_position_efficiency(self, sheet_name="Position_Efficiency", canvas=None, key="base"):
        canvas = canvas if canvas is not None else self.base_effectiveness_canvas
        state = self._pe_state(key)
        records = self._safe_read(sheet_name)
        state["records"] = records

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
        detected_positions = [key_ for key_ in records[0] if key_ not in meta_cols]
        company = self._active_company() or {}
        known_positions = sorted(set(detected_positions) | set(company.get("last_known_positions") or []))
        self._position_efficiency_all_positions = known_positions
        hidden = set(company.get("position_efficiency_hidden_positions") or [])
        position_names = [position for position in known_positions if position not in hidden]

        state["columns"] = ("name", "current_position", "current_efficiency", *position_names)
        state["labels"] = {
            "name": "Name" + CLICK_FOR_MORE_INFO_SUFFIX,
            "current_position": "Current Position",
            "current_efficiency": "Current Eff.",
        }
        self._sort_position_efficiency(
            state["sort_column"] or "name",
            state["sort_reverse"],
            toggle=False,
            canvas=canvas,
            key=key,
        )

    def _render_position_efficiency_rows(self, records, canvas=None, key="base"):
        canvas = canvas if canvas is not None else self.base_effectiveness_canvas
        state = self._pe_state(key)
        canvas.delete("all")
        columns = state["columns"]
        labels = state["labels"]
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
            if column == state["sort_column"]:
                arrow = " ▼" if state["sort_reverse"] else " ▲"
            width = widths[column]
            tag = f"position_efficiency_header_{key}_{column_index}"
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
                lambda event, col=column, cv=canvas, current_key=key: self._sort_position_efficiency(col, False, canvas=cv, key=current_key),
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
        tid_key = str(tid) if tid not in (None, "") else "missing"
        record = self._employee_info_lookup.get(tid_key) if tid_key != "missing" else None
        open_single_instance_popup(
            self,
            f"employee_info:{tid_key}",
            lambda: EmployeeInfoCard(self, record),
        )

    def _sort_position_efficiency(self, column, reverse, toggle=True, canvas=None, key="base"):
        state = self._pe_state(key)
        if toggle and column == state["sort_column"]:
            reverse = not state["sort_reverse"]
        elif toggle and column in {"name", "current_position"}:
            reverse = False

        records = sorted(
            state["records"],
            key=lambda record: position_efficiency_sort_value(record, column),
            reverse=reverse,
        )
        state["sort_column"] = column
        state["sort_reverse"] = reverse
        self._render_position_efficiency_rows(records, canvas=canvas, key=key)

    def _build_stock_tab(self):
        top = ttk.Frame(self.stock_sub_tab)
        top.pack(fill="x", padx=10, pady=10)
        ttk.Button(top, text="Refresh", command=self.refresh_from_sheet).pack(side="left")
        self._add_company_selector(top)
        ttk.Label(
            top,
            text="Shows each stock item's last 7 snapshots (in-stock, sold, cost, price, created) "
                 "\nso you can compare against the last week, plus a chart of total sold worth over time. ",
            foreground="#555555",
            wraplength=460, justify="left",
        ).pack(side="left", padx=10)

        paned = ttk.PanedWindow(self.stock_sub_tab, orient="vertical")
        paned.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        columns = ["name", "date", "in_stock", "delta_in_stock", "cost", "price", "sold_amount", "sold_worth", "created"]
        column_labels = {"delta_in_stock": "in_stock_difference"}
        tree_frame, self.stock_tree = self._make_scrollable_tree(paned, columns=columns, show="headings", height=18)
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

        recent_rows = select_recent_stock_history_rows(records)

        columns = self.stock_tree["columns"]
        for row in recent_rows:
            self.stock_tree.insert(
                "", "end",
                values=[format_field(c, row.get(c, ""), "Stock_History") for c in columns],
            )
        self._autosize_columns(self.stock_tree)

        totals_by_ts = {}
        label_by_ts = {}
        for row in records:
            ts = _safe_int_ts(row.get("timestamp"))
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
            "monthly_income", "monthly_profit",
        ]
        self._trend_metric_label_to_key = {pretty_label(c): c for c in numeric_cols}
        labels = list(self._trend_metric_label_to_key.keys())
        self.trend_metric_combo["values"] = labels
        if self.trend_metric_var.get() not in labels and labels:
            self.trend_metric_var.set(labels[0])
        self._draw_trend()

    def _draw_trend(self):
        records = getattr(self, "_company_history_cache", [])
        records = sorted(records, key=lambda r: _safe_int_ts(r.get("timestamp")))
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

    def _build_settings_tab(self):
        frame = ttk.Frame(self.settings_tab)
        frame.pack(fill="both", expand=True, padx=20, pady=20)

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

        row += 1
        scheduled = ttk.LabelFrame(frame, text="Scheduled Daily Collection", padding=10)
        scheduled.grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=(16, 0)
        )
        self._scheduled_enabled_var = tk.BooleanVar(
            value=self.settings.scheduled_collection_enabled
        )
        self._scheduled_wake_var = tk.BooleanVar(
            value=self.settings.scheduled_wake_computer
        )
        ttk.Checkbutton(
            scheduled,
            text="Enable Windows background collection",
            variable=self._scheduled_enabled_var,
        ).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(
            scheduled,
            text="Wake the computer when possible",
            variable=self._scheduled_wake_var,
        ).grid(row=0, column=1, sticky="w", padx=(16, 0))
        ttk.Label(
            scheduled,
            text=(
                "Runs hourly as the current Windows user, but collects only once "
                "per 18:10 UTC reporting period. Select no companies to include all."
            ),
            wraplength=720,
            justify="left",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 4))

        self._scheduled_companies_listbox = tk.Listbox(
            scheduled, height=4, selectmode="multiple", exportselection=False
        )
        self._scheduled_companies_listbox.grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=4
        )
        selected_names = set(self.settings.scheduled_company_names)
        for index, company in enumerate(self.companies):
            name = str(company.get("name") or "Unnamed")
            self._scheduled_companies_listbox.insert("end", name)
            if name in selected_names:
                self._scheduled_companies_listbox.selection_set(index)

        buttons = ttk.Frame(scheduled)
        buttons.grid(row=2, column=2, sticky="n", padx=(8, 0))
        ttk.Button(
            buttons, text="Apply Schedule", command=self._apply_scheduled_task
        ).pack(fill="x")
        ttk.Button(
            buttons, text="Run Test Now", command=self._run_scheduled_test
        ).pack(fill="x", pady=4)
        ttk.Button(
            buttons, text="Repair Task", command=self._repair_scheduled_task
        ).pack(fill="x")
        ttk.Button(
            buttons, text="Refresh Status", command=self._refresh_scheduled_status
        ).pack(fill="x", pady=(4, 0))

        self._scheduled_status_var = tk.StringVar(
            value=self.settings.scheduled_last_result or "Status not checked."
        )
        ttk.Label(
            scheduled, textvariable=self._scheduled_status_var, wraplength=720,
            justify="left",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        scheduled.columnconfigure(1, weight=1)

    def _save_settings(self):
        s = self.settings
        try:
            s.snapshot_interval_minutes = int(self._settings_vars["snapshot_interval_minutes"].get().strip() or 0)
        except ValueError:
            s.snapshot_interval_minutes = 0
        s.save()
        self.set_status("Settings saved securely for this Windows user.")
        messagebox.showinfo("Saved", "Settings were encrypted for this Windows user.")

    def _scheduled_selected_names(self) -> list[str]:
        box = self._scheduled_companies_listbox
        return [str(box.get(index)) for index in box.curselection()]

    def _apply_scheduled_task(self):
        self.settings.scheduled_collection_enabled = bool(
            self._scheduled_enabled_var.get()
        )
        self.settings.scheduled_wake_computer = bool(
            self._scheduled_wake_var.get()
        )
        self.settings.scheduled_company_names = self._scheduled_selected_names()
        try:
            if self.settings.scheduled_collection_enabled:
                install_task(
                    wake_computer=self.settings.scheduled_wake_computer
                )
            else:
                remove_task()
            self.settings.save()
            self._refresh_scheduled_status()
            self.set_status("Scheduled collection settings updated.")
        except Exception as exc:
            self._scheduled_status_var.set(f"Schedule update failed: {exc}")
            messagebox.showerror("Scheduled Collection", str(exc))

    def _refresh_scheduled_status(self):
        try:
            status = task_status()
            if not status.get("installed"):
                text = "Windows task is not installed."
            else:
                text = (
                    f"Status: {status.get('status') or 'Installed'} | "
                    f"Next: {status.get('next_run') or 'Unknown'} | "
                    f"Last: {status.get('last_run') or 'Never'} | "
                    f"Result: {status.get('last_result') or 'Unknown'}"
                )
            if self.settings.scheduled_last_result:
                text += f" | App: {self.settings.scheduled_last_result}"
            self._scheduled_status_var.set(text)
        except Exception as exc:
            self._scheduled_status_var.set(f"Could not read task status: {exc}")

    def _repair_scheduled_task(self):
        try:
            self.settings.scheduled_collection_enabled = True
            self._scheduled_enabled_var.set(True)
            self.settings.scheduled_wake_computer = bool(
                self._scheduled_wake_var.get()
            )
            self.settings.scheduled_company_names = self._scheduled_selected_names()
            repair_task(wake_computer=self.settings.scheduled_wake_computer)
            self.settings.save()
            self._refresh_scheduled_status()
        except Exception as exc:
            messagebox.showerror("Scheduled Collection", str(exc))

    def _run_scheduled_test(self):
        if not self.companies:
            messagebox.showwarning(
                "Scheduled Collection", "Add at least one company first."
            )
            return
        self.settings.scheduled_company_names = self._scheduled_selected_names()
        self.settings.scheduled_wake_computer = bool(self._scheduled_wake_var.get())
        self._scheduled_status_var.set("Running scheduled collection test...")

        def worker():
            return run_scheduled_collection(
                self.companies, self.settings, force=True, persist=True
            )

        def done(result):
            exit_code, _rows = result
            self._scheduled_status_var.set(self.settings.scheduled_last_result)
            if exit_code:
                messagebox.showerror(
                    "Scheduled Collection", self.settings.scheduled_last_result
                )
            else:
                self._refresh_all(silent=True)

        def run():
            try:
                result = worker()
                self.after(0, lambda: done(result))
            except Exception as exc:
                self.after(
                    0,
                    lambda err=str(exc): self._scheduled_status_var.set(
                        f"Test failed: {err}"
                    ),
                )

        threading.Thread(target=run, daemon=True).start()

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
        sel = self._companies_listbox.curselection()
        if not sel or sel[0] >= len(self.companies):
            return
        name = self.companies[sel[0]].get("name", "Unnamed")
        self.company_var.set(name)
        self.settings.last_selected_company = name
        self.settings.save()

    def _on_company_selected(self):
        sel = self.company_var.get()
        if sel == "(No companies configured)":
            sel = ""
        self.settings.last_selected_company = sel
        self.settings.save()
        self.refresh_from_sheet()

    def set_status(self, text: str):
        self.status_var.set(text)

    def run_snapshot(self):
        if not self.companies:
            messagebox.showinfo(
                "No companies configured",
                "Add at least one company (Torn API key required, Google Sheet ID optional) in Settings first.",
            )
            return

        self.set_status("Running snapshot...")

        def worker():
            try:
                from app.collector import run_company_snapshots, persist_companies
                results = run_company_snapshots(self.companies, base_settings=self.settings)
                try:
                    persist_companies(self.companies)
                except Exception:
                    pass

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
            except Exception as exc:
                err_msg = str(exc)
                self.after(0, lambda: self.set_status(f"Snapshot failed: {err_msg}"))
                self.after(0, lambda: messagebox.showerror("Snapshot Error", f"Snapshot failed:\n{err_msg}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_snapshot_done(self, result):
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
        if not self.companies:
            messagebox.showinfo(
                "No companies configured",
                "Add at least one company (Torn API key required, Google Sheet ID optional) in Settings first.",
            )
            return

        self.set_status("Running employee efficiency...")

        def worker():
            try:
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
            except Exception as exc:
                err_msg = str(exc)
                self.after(0, lambda: self.set_status(f"Employee efficiency failed: {err_msg}"))
                self.after(0, lambda: messagebox.showerror("Employee Efficiency Error", f"Employee efficiency failed:\n{err_msg}"))

        threading.Thread(target=worker, daemon=True).start()

    def run_everything(self):
        if not self.companies:
            messagebox.showinfo(
                "No companies configured",
                "Add at least one company (Torn API key required, Google Sheet ID optional) in Settings first.",
            )
            return

        self.set_status("Running snapshot + employee efficiency...")

        def worker():
            try:
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
            except Exception as exc:
                err_msg = str(exc)
                self.after(0, lambda: self.set_status(f"Run Everything failed: {err_msg}"))
                self.after(0, lambda: messagebox.showerror("Run Everything Error", f"Run Everything failed:\n{err_msg}"))

        threading.Thread(target=worker, daemon=True).start()

    def refresh_from_sheet(self):
        self.set_status("Refreshing from sheet...")

        def worker():
            self.after(0, lambda: self._refresh_all(silent=False))

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_all(self, silent: bool):
        try:
            self._populate_overview()
            self._populate_company_rankings()
            self._populate_employees()
            self._populate_position_efficiency()
            self._populate_position_efficiency(
                sheet_name="Total_Effectiveness_Projections",
                canvas=self.total_effectiveness_canvas,
                key="total",
            )
            self._populate_stock()
            self._populate_trends()
            if not silent:
                self.set_status("Refreshed.")
            try:
                self._update_company_selectors()
            except Exception:
                pass
        except Exception as e:
            self.set_status(f"Refresh failed: {e}")

    def _active_company(self) -> dict | None:
        sel = (self.company_var.get() or "").strip()
        for c in self.companies:
            if c.get("name") == sel:
                return c
        return self.companies[0] if self.companies else None

    def _active_company_sheet_override(self) -> tuple:
        sel = (self.company_var.get() or "").strip()
        for c in self.companies:
            if c.get("name") == sel:
                return c.get("google_sheet_id", ""), c.get("google_sheet_name", "")
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

    def _refresh_companies_list(self):
        try:
            self._companies_listbox.delete(0, tk.END)
        except Exception:
            return
        for c in self.companies:
            self._companies_listbox.insert(tk.END, c.get("name", "Unnamed"))
        scheduled_box = getattr(self, "_scheduled_companies_listbox", None)
        if scheduled_box is not None:
            selected = set(self.settings.scheduled_company_names)
            scheduled_box.delete(0, tk.END)
            for index, company in enumerate(self.companies):
                name = str(company.get("name") or "Unnamed")
                scheduled_box.insert(tk.END, name)
                if name in selected:
                    scheduled_box.selection_set(index)
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


def show_fatal_error(title: str, message: str):
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, str(message), str(title), 0x10)
        except Exception:
            pass


def launch():
    try:
        app = MainWindow()
        style = ttk.Style(app)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Treeview", rowheight=24)
        style.configure("Treeview.Heading", padding=(6, 8, 6, 8))
        app.mainloop()
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        show_fatal_error("Startup Error - Torn Company Assistant", f"An error occurred on startup:\n\n{exc}\n\nDetails:\n{tb}")
