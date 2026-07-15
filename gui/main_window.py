"""
Desktop GUI for the Knotty Oil Tracker.

Tabs:
  Overview   - latest company-level snapshot + a "Run Snapshot Now" button
  Employees  - current roster with Torn's per-employee effectiveness breakdown
  Stock      - latest stock snapshot + a sold-worth trend chart
  Trends     - pick any Company_History metric and chart it over time
  Settings   - encrypted local API keys / Google OAuth / sheet target

All data is read straight from the Google Sheet (via SheetsClient), so the
GUI is safe to close and reopen without losing anything - the Sheet is the
source of truth. "Run Snapshot Now" triggers app.collector.Collector in a
background thread so the UI never freezes on network calls.
"""

from __future__ import annotations

import datetime
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from tkinter import font as tkfont

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from app.collector import Collector
from app.config import Settings
from app.sheets_client import SheetsClient
from app.google_auth import authorize as authorize_google
from app import companies as companies_mod

# Fields that represent Torn dollars and should render as "$1,234,567" rather
# than a bare number. Keyed by the sheet-tab they come from.
MONEY_FIELDS = {
    "Company_History": {
        "daily_income", "daily_profit", "weekly_income", "weekly_profit", "company_funds",
        "advertising_budget", "total_wage", "daily_stockcost",
        "avg_daily_profit_7day", "avg_daily_income_7day",
    },
    "Employees": {"wage"},
    "Stock_History": {"cost", "price", "sold_worth", "delta_sold_worth"},
}

# Fields that are unix timestamps and should render as a readable date/time
# rather than a raw epoch number. Keyed by the sheet-tab they come from.
TIMESTAMP_FIELDS = {
    "Employees": {"last_action_ts"},
}

# Fields that are a delta vs. the previous snapshot and should render with an
# explicit +/- sign so a change is obvious at a glance. Keyed by sheet-tab.
SIGNED_FIELDS = {
    "Stock_History": {"delta_in_stock", "delta_sold_amount"},
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
    return datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M UTC")


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
    return str(value)


class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Knotty Oil Tracker")

        self.settings = Settings.load()
        # Company settings, including API keys, are DPAPI-encrypted for this user.
        self.companies = companies_mod.load_companies()
        self._migrate_legacy_primary_company()
        self.status_var = tk.StringVar(value="Ready.")
        # Active company selection - name of a company in self.companies.
        self.company_var = tk.StringVar(value=self.settings.last_selected_company or "")

        self._build_menu()
        self._build_layout()
        self._auto_size_window()
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

    def _auto_size_window(self):
        """Start at a size proportional to the actual screen instead of a
        fixed 1100x700 that clips content on smaller displays or wastes
        space on larger ones. Window stays freely resizable after this;
        per-tab tables also get scrollbars and auto-fit columns so content
        stays reachable even if the window itself is later shrunk."""
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        win_w = max(900, min(1500, int(screen_w * 0.85)))
        win_h = max(600, min(950, int(screen_h * 0.85)))
        x = (screen_w - win_w) // 2
        y = (screen_h - win_h) // 2
        self.geometry(f"{win_w}x{win_h}+{x}+{y}")
        self.minsize(900, 600)

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
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)
        self.config(menu=menubar)

    # ----------------------------------------------------------- layout --
    def _build_layout(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        self.overview_tab = ttk.Frame(self.notebook)
        self.employees_tab = ttk.Frame(self.notebook)
        self.stock_tab = ttk.Frame(self.notebook)
        self.trends_tab = ttk.Frame(self.notebook)
        self.settings_tab = ttk.Frame(self.notebook)

        self.notebook.add(self.overview_tab, text="Overview")
        self.notebook.add(self.employees_tab, text="Employees")
        self.notebook.add(self.stock_tab, text="Stock & Profit")
        self.notebook.add(self.trends_tab, text="Trends")
        self.notebook.add(self.settings_tab, text="Settings")

        self._build_overview_tab()
        self._build_employees_tab()
        self._build_stock_tab()
        self._build_trends_tab()
        self._build_settings_tab()

        status_bar = ttk.Label(self, textvariable=self.status_var, anchor="w", relief="sunken")
        status_bar.pack(fill="x", side="bottom")

    # --------------------------------------------------------- overview --
    def _build_overview_tab(self):
        top = ttk.Frame(self.overview_tab)
        top.pack(fill="x", padx=10, pady=10)

        ttk.Button(top, text="Run Snapshot Now", command=self.run_snapshot).pack(side="left")
        ttk.Button(top, text="Refresh From Sheet", command=self.refresh_from_sheet).pack(side="left", padx=6)

        # Company selector: pick which configured company to view.
        company_names = [c.get("name", "Unnamed") for c in self.companies]
        selector_values = company_names or ["(No companies configured)"]
        if self.settings.last_selected_company and self.settings.last_selected_company in selector_values:
            self.company_var.set(self.settings.last_selected_company)
        else:
            self.company_var.set(selector_values[0])
        self.company_combo = ttk.Combobox(top, textvariable=self.company_var, values=selector_values, state="readonly", width=30)
        self.company_combo.pack(side="left", padx=8)
        self.company_combo.bind("<<ComboboxSelected>>", lambda e: self._on_company_selected())

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
        for key, value in latest.items():
            if key == "employees_capacity":
                continue  # merged into the employees_hired row below
            if key == "employees_hired":
                self.overview_tree.insert(
                    "", "end", text="employees",
                    values=(f"{value}/{capacity}",),
                )
                continue
            self.overview_tree.insert("", "end", text=pretty_label(key), values=(format_field(key, value, "Company_History"),))
        self._center_overview_columns()

    # -------------------------------------------------------- employees --
    def _build_employees_tab(self):
        top = ttk.Frame(self.employees_tab)
        top.pack(fill="x", padx=10, pady=10)
        ttk.Button(top, text="Refresh", command=self.refresh_from_sheet).pack(side="left")

        columns = [
            "tId", "name", "position", "wage", "effectiveness_total",
            "effectiveness_working_stats", "effectiveness_merits",
            "effectiveness_addiction", "effectiveness_inactivity",
            "last_action_ts", "time_since_last_action",
        ]
        column_labels = {
            "effectiveness_working_stats": "E. WST",
            "effectiveness_merits": "E. MER",
            "effectiveness_addiction": "E. Add",
            "effectiveness_inactivity": "E. Inactivity",
            "time_since_last_action": "Time Since Last Action",
        }
        frame, self.employees_tree = self._make_scrollable_tree(
            self.employees_tab, columns=columns, show="headings", height=25
        )
        for col in columns:
            self.employees_tree.heading(
                col, text=pretty_label(column_labels.get(col, col)),
                command=lambda c=col: self._sort_employees(c, False),
            )
            self.employees_tree.column(col, width=140, anchor="center")
        frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._employee_records_cache = []

    def _employee_row_values(self, row, columns):
        values = []
        for c in columns:
            if c == "time_since_last_action":
                values.append(format_time_since(row.get("last_action_ts", "")))
            else:
                values.append(format_field(c, row.get(c, ""), "Employees"))
        return values

    def _populate_employees(self):
        self.employees_tree.delete(*self.employees_tree.get_children())
        records = self._safe_read("Employees")
        self._employee_records_cache = records
        columns = self.employees_tree["columns"]
        for row in records:
            self.employees_tree.insert("", "end", values=self._employee_row_values(row, columns))
        self._autosize_columns(self.employees_tree)

    def _sort_employees(self, col, reverse):
        # time_since_last_action isn't a real stored field - it's derived
        # from last_action_ts, so sort by that instead (more recent action =
        # less time elapsed, so this still orders intuitively).
        sort_key_field = "last_action_ts" if col == "time_since_last_action" else col
        try:
            data = sorted(self._employee_records_cache, key=lambda r: float(r.get(sort_key_field, 0) or 0), reverse=reverse)
        except (TypeError, ValueError):
            data = sorted(self._employee_records_cache, key=lambda r: str(r.get(sort_key_field, "")), reverse=reverse)
        self.employees_tree.delete(*self.employees_tree.get_children())
        columns = self.employees_tree["columns"]
        for row in data:
            self.employees_tree.insert("", "end", values=self._employee_row_values(row, columns))
        self._autosize_columns(self.employees_tree)
        self.employees_tree.heading(col, command=lambda: self._sort_employees(col, not reverse))

    # ------------------------------------------------------------ stock --
    def _build_stock_tab(self):
        top = ttk.Frame(self.stock_tab)
        top.pack(fill="x", padx=10, pady=10)
        ttk.Button(top, text="Refresh", command=self.refresh_from_sheet).pack(side="left")

        paned = ttk.PanedWindow(self.stock_tab, orient="vertical")
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
        top = ttk.Frame(self.trends_tab)
        top.pack(fill="x", padx=10, pady=10)

        ttk.Label(top, text="Metric:").pack(side="left")
        self.trend_metric_var = tk.StringVar(value="company_funds")
        self.trend_metric_combo = ttk.Combobox(top, textvariable=self.trend_metric_var, state="readonly", width=30)
        self.trend_metric_combo.pack(side="left", padx=6)
        self.trend_metric_combo.bind("<<ComboboxSelected>>", lambda e: self._draw_trend())
        ttk.Button(top, text="Refresh", command=self.refresh_from_sheet).pack(side="left", padx=6)

        chart_frame = ttk.Frame(self.trends_tab)
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
            "google_oauth_client_file": tk.StringVar(value=self.settings.google_oauth_client_file),
            "snapshot_interval_minutes": tk.StringVar(value=str(self.settings.snapshot_interval_minutes)),
        }

        labels = {
            "google_oauth_client_file": "Google OAuth desktop-client JSON file",
            "snapshot_interval_minutes": "Auto-refresh interval (minutes, 0 = off)",
        }

        row = 0
        for key, label in labels.items():
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=6)
            entry = ttk.Entry(frame, textvariable=self._settings_vars[key], width=50)
            entry.grid(row=row, column=1, sticky="we", pady=6, padx=6)
            if key == "google_oauth_client_file":
                ttk.Button(frame, text="Browse...", command=self._browse_oauth_client).grid(row=row, column=2)
            row += 1

        frame.columnconfigure(1, weight=1)

        ttk.Button(frame, text="Save Securely", command=self._save_settings).grid(row=row, column=0, pady=16, sticky="w")
        ttk.Button(frame, text="Sign in with Google", command=self._sign_in_google).grid(row=row, column=1, pady=16, sticky="w")

        # -- Companies management area --
        row += 1
        legacy_btn_row = ttk.Frame(frame)
        legacy_btn_row.grid(row=row, column=0, columnspan=2, pady=(0, 8), sticky="w")
        ttk.Button(legacy_btn_row, text="Remove Legacy Plaintext Files", command=self._remove_legacy_files).pack(side="left")
        ttk.Button(legacy_btn_row, text="Sort Existing Rows (One-Time)", command=self._resort_existing_history).pack(side="left", padx=(8, 0))
        row += 1
        sep = ttk.Separator(frame, orient="horizontal")
        sep.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(12, 8))
        row += 1
        ttk.Label(
            frame,
            text="Companies - each needs its own Torn API key and its own Google Sheet ID.\n"
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
        ttk.Button(btn_frame, text="Remove", command=self._remove_company).pack(fill="x")
        ttk.Button(btn_frame, text="Test Connection", command=self._test_connection).pack(fill="x", pady=6)
        frame.columnconfigure(1, weight=1)
        self._refresh_companies_list()

    def _browse_oauth_client(self):
        path = filedialog.askopenfilename(title="Select Google OAuth desktop-client JSON", filetypes=[("JSON", "*.json")])
        if path:
            self._settings_vars["google_oauth_client_file"].set(path)

    def _save_settings(self):
        s = self.settings
        s.google_oauth_client_file = self._settings_vars["google_oauth_client_file"].get().strip()
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
                authorize_google(self.settings.google_oauth_client_file)
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

    def _remove_legacy_files(self):
        from app.config import LEGACY_ENV_PATH
        legacy_paths = [LEGACY_ENV_PATH, companies_mod.COMPANIES_PATH]
        project_root = companies_mod.PROJECT_ROOT
        legacy_paths.append(project_root / "service-account.json")
        existing = [path for path in legacy_paths if path.exists()]
        if not existing:
            messagebox.showinfo("No plaintext files", "No legacy plaintext credential files were found.")
            return
        names = "\n".join(f"• {path.name}" for path in existing)
        if not messagebox.askyesno(
            "Remove plaintext files?",
            "Settings/companies saved with this version are encrypted for your Windows user.\n\n"
            f"Remove these plaintext files now?\n{names}\n\n"
            "This does not securely erase data from disk; rotate previously exposed keys.",
        ):
            return
        failures = []
        for path in existing:
            try:
                path.unlink()
            except OSError:
                failures.append(path.name)
        if failures:
            messagebox.showerror("Could not remove files", "Could not remove: " + ", ".join(failures))
        else:
            messagebox.showinfo("Removed", "Plaintext legacy files were removed.")

    def _test_connection(self):
        self._save_settings()
        sheet_id, sheet_name = self._active_company_sheet_override()
        if not sheet_id:
            messagebox.showinfo("Nothing to test", "Add a company with a Google Sheet ID first.")
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
                "Add at least one company (Torn API key + Google Sheet ID) in Settings first.",
            )
            return

        self.set_status("Running snapshot...")

        def worker():
            from app.collector import run_company_snapshots
            results = run_company_snapshots(self.companies, base_settings=self.settings)

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

    def refresh_from_sheet(self):
        self.set_status("Refreshing from sheet...")

        def worker():
            self.after(0, lambda: self._refresh_all(silent=False))

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_all(self, silent: bool):
        try:
            self._populate_overview()
            self._populate_employees()
            self._populate_stock()
            self._populate_trends()
            if not silent:
                self.set_status("Refreshed.")
            # refresh company selector values in case companies.json changed externally
            company_names = [c.get("name", "Unnamed") for c in self.companies]
            selector_values = company_names or ["(No companies configured)"]
            try:
                self.company_combo["values"] = selector_values
                if self.company_var.get() not in selector_values:
                    self.company_var.set(selector_values[0])
            except Exception:
                pass
        except Exception as e:
            self.set_status(f"Refresh failed: {e}")

    # ---------------------------------------------------------------- io --
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
            vals = [c.get("name", "Unnamed") for c in self.companies] or ["(No companies configured)"]
            self.company_combo["values"] = vals
            if self.company_var.get() not in vals:
                self.company_var.set(vals[0])
        except Exception:
            pass

    def _add_company(self):
        name = simpledialog.askstring("Company name", "Name for company", parent=self)
        if not name:
            return
        torn = simpledialog.askstring("Torn API key", "Company's limited Torn API key (required)", parent=self, show="*")
        if not (torn or "").strip():
            messagebox.showwarning("Torn API key required", "Each company needs its own Torn API key.")
            return
        tornstats = simpledialog.askstring("Tornstats API key", "Tornstats API key (optional)", parent=self, show="*")
        sheet_id = simpledialog.askstring("Google Sheet ID", "ID of the Google Sheet shared with this user (required)", parent=self)
        if not (sheet_id or "").strip():
            messagebox.showwarning("Sheet ID required", "Each company needs the ID of its own Google Sheet.")
            return
        sheet_name = simpledialog.askstring("Google Sheet name", "Optional display name", parent=self)
        entry = {
            "name": name.strip(),
            "torn_api_key": torn.strip(),
            "tornstats_api_key": (tornstats or "").strip(),
            "google_sheet_id": sheet_id.strip(),
            "google_sheet_name": (sheet_name or "").strip(),
        }
        self.companies.append(entry)
        try:
            companies_mod.save_companies(self.companies)
        except Exception:
            messagebox.showerror("Save failed", "Could not save companies to companies.json")
        self._refresh_companies_list()

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
        torn = simpledialog.askstring("Torn API key", "Company's limited Torn API key (required)", initialvalue=c.get("torn_api_key", ""), parent=self, show="*")
        if not (torn or "").strip():
            messagebox.showwarning("Torn API key required", "Each company needs its own Torn API key.")
            return
        tornstats = simpledialog.askstring("Tornstats API key", "Tornstats API key (optional)", initialvalue=c.get("tornstats_api_key", ""), parent=self, show="*")
        sheet_id = simpledialog.askstring("Google Sheet ID", "ID of the Google Sheet shared with this user (required)", initialvalue=c.get("google_sheet_id", ""), parent=self)
        if not (sheet_id or "").strip():
            messagebox.showwarning("Sheet ID required", "Each company needs the ID of its own Google Sheet.")
            return
        sheet_name = simpledialog.askstring("Google Sheet name", "Optional display name", initialvalue=c.get("google_sheet_name", ""), parent=self)
        c.update({
            "name": name.strip(),
            "torn_api_key": torn.strip(),
            "tornstats_api_key": (tornstats or "").strip(),
            "google_sheet_id": sheet_id.strip(),
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
    app.mainloop()
