import tkinter as tk
from tkinter import simpledialog, Toplevel, ttk
from datetime import datetime, timedelta, time as dtime
import time, sqlite3
from collections import defaultdict

# Matplotlib embed (optional)
try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import matplotlib.pyplot as plt
    HAS_MPL = True
except Exception:
    HAS_MPL = False

import tkinter.font as tkfont

# ---- Windows hotkeys (ctypes) ----
import threading, ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_HOTKEY = 0x0312
WM_QUIT   = 0x0012

MOD_ALT      = 0x0001
MOD_CONTROL  = 0x0002

VK_HOME   = 0x24  # Work
VK_PRIOR  = 0x21  # Page Up -> Study
VK_NEXT   = 0x22  # Page Down -> Break
VK_END    = 0x23  # Waste
VK_LEFT   = 0x25  # Projects

# ---------- Paths ----------
import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "activity_log.db")

# ---------- Config ----------
DEFAULT_ACTIVITIES = ["Work", "Study", "Break", "Waste", "Projects"]

COLOR_MAP = {
    "Work": "green",
    "Study": "blue",
    "Break": "gray",
    "Waste": "red",
    "Projects": "yellow",
}

ICON_MAP = {
    "Work": "💼",
    "Study": "📚",
    "Break": "🏠",
    "Waste": "🛑",
    "Projects": "🧩",
}
ICON_FALLBACK = {
    "Work": "WORK",
    "Study": "STUDY",
    "Break": "HOME",
    "Waste": "WASTE",
    "Projects": "PROJ",
}

NORMAL_SIZE = 36
WASTE_SIZE  = 96

# Hotkey IDs
HK_WORK     = 1
HK_STUDY    = 2
HK_BREAK    = 3
HK_WASTE    = 4
HK_PROJECTS = 5

class StopwatchApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Activity Logger (SQLite)")

        # --- DB setup ---
        self.conn = sqlite3.connect(DB_FILE)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.cur = self.conn.cursor()
        self._init_db()
        self._seed_default_activities()

        # --- State ---
        self.running = False
        self.start_time = None              # epoch seconds
        self.start_timestamp = None         # ISO string
        self.current_activity_id = None
        self.current_activity_name = None
        self.current_session_id = None      # <-- NEW: live session row id

        # Autosave / rollover
        self._autosave_interval_ms = 60_000  # 1 minute
        self._last_autosave_dt = datetime.now().replace(microsecond=0)

        # --- Transparent overlay config ---
        self.overlay = None
        self.overlay_canvas = None
        self.TRANSPARENT_COLOR = "#ff00ff"
        self._overlay_supports_color = True
        self.show_daily_totals = False  # toggle for second line

        # Overlay fonts
        self.overlay_font_size = 48
        self.overlay_font_tuple = ("Consolas", self.overlay_font_size, "bold")
        self.overlay_font_metrics = tkfont.Font(family="Consolas", size=self.overlay_font_size, weight="bold")

        # Icon (smaller) + daily totals (emoji-capable, smaller)
        self.overlay_icon_font_metrics = self._make_icon_font(self._icon_size_for(self.overlay_font_size))
        self.overlay_sub_font_metrics  = self._make_icon_font(self._sub_size_for(self.overlay_font_size))

        # --- Main clock (non-transparent) ---
        self.clock_label = tk.Label(root, text="00:00:00.00", font=("Consolas", 40))
        self.clock_label.pack(pady=(8,4))

        # --- Activities (radios) ---
        tk.Label(root, text="Select Activity:").pack()
        self.activity_var = tk.StringVar()
        self.radio_frame = tk.Frame(root)
        self.radio_frame.pack(pady=(0,6))
        self._build_activity_radios()

        # --- Buttons ---
        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=6)
        tk.Button(btn_frame, text="Start", command=self.start).grid(row=0, column=0, padx=6)
        tk.Button(btn_frame, text="Stop", command=self.stop).grid(row=0, column=1, padx=6)
        tk.Button(btn_frame, text="Settings", command=self.open_settings).grid(row=0, column=2, padx=6)
        tk.Button(btn_frame, text="Toggle Transparent Clock", command=self.toggle_overlay).grid(row=0, column=3, padx=6)
        tk.Button(btn_frame, text="Toggle Daily Totals", command=self.toggle_daily_totals).grid(row=0, column=4, padx=6)

        # --- Overlay size slider ---
        size_frame = tk.Frame(root)
        size_frame.pack(pady=(0,8))
        tk.Label(size_frame, text="Overlay size").pack(side=tk.LEFT, padx=(0,8))
        self.overlay_size_var = tk.DoubleVar(value=self.overlay_font_size)
        self.size_scale = tk.Scale(
            size_frame, from_=24, to=120, orient=tk.HORIZONTAL,
            variable=self.overlay_size_var, command=self._on_overlay_size_change, length=240
        )
        self.size_scale.pack(side=tk.LEFT)

        # Start default + overlay
        default_name = self._first_non_custom_activity()
        self.activity_var.set(default_name)
        self._start_activity(default_name)
        self._create_overlay()

        # Hotkeys
        self._hotkey_thread_id = None
        self._hotkey_thread = threading.Thread(target=self._hotkey_loop, daemon=True)
        self._hotkey_thread.start()

        # Cleanup on close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Kick off clock + autosave loops
        self._update_clock()
        self._schedule_autosave()

    # -------------------- DB --------------------
    def _init_db(self):
        self.cur.execute("""
            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY,
                name TEXT UNIQUE COLLATE NOCASE
            );
        """)
        self.cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id           INTEGER PRIMARY KEY,
                activity_id  INTEGER NOT NULL,
                start_ts     TEXT NOT NULL,
                end_ts       TEXT NOT NULL,
                duration_sec REAL NOT NULL,
                FOREIGN KEY(activity_id) REFERENCES activities(id) ON DELETE CASCADE
            );
        """)
        self.cur.execute("""
            CREATE TABLE IF NOT EXISTS daily_totals (
                date        TEXT NOT NULL,         -- 'YYYY-MM-DD'
                activity_id INTEGER NOT NULL,
                seconds     REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (date, activity_id),
                FOREIGN KEY(activity_id) REFERENCES activities(id) ON DELETE CASCADE
            );
        """)
        self.conn.commit()

    def _seed_default_activities(self):
        for name in DEFAULT_ACTIVITIES:
            self.cur.execute("INSERT OR IGNORE INTO activities(name) VALUES(?);", (name,))
        self.cur.execute("INSERT OR IGNORE INTO activities(name) VALUES('Custom');")
        self.conn.commit()

    def _load_activities(self):
        rows = self.cur.execute("SELECT name FROM activities ORDER BY name;").fetchall()
        names = [r[0] for r in rows if r[0] != "Custom"]
        names.append("Custom")
        return names

    def _get_or_create_activity(self, name):
        self.cur.execute("INSERT OR IGNORE INTO activities(name) VALUES(?);", (name,))
        self.conn.commit()
        row = self.cur.execute("SELECT id FROM activities WHERE name = ?;", (name,)).fetchone()
        return row[0]

    # -------------------- UI helpers --------------------
    def _build_activity_radios(self):
        for child in self.radio_frame.winfo_children():
            child.destroy()
        for name in self._load_activities():
            tk.Radiobutton(
                self.radio_frame, text=name, variable=self.activity_var, value=name,
                command=self._switch_activity
            ).pack(anchor="w")

    def _first_non_custom_activity(self):
        for n in self._load_activities():
            if n != "Custom":
                return n
        return "Work"

    # -------------------- Activity control --------------------
    def _create_new_session_row(self, start_dt: datetime):
        """Create a sessions row for the current activity and remember its id."""
        start_ts = start_dt.strftime("%Y-%m-%d %H:%M:%S")
        # initialize end_ts = start_ts and duration_sec = 0
        self.cur.execute(
            "INSERT INTO sessions(activity_id, start_ts, end_ts, duration_sec) VALUES (?,?,?,?);",
            (self.current_activity_id, start_ts, start_ts, 0.0)
        )
        self.conn.commit()
        self.current_session_id = self.cur.lastrowid

    def _update_current_session_row(self, end_dt: datetime):
        """Update end_ts + duration_sec of the current live session row."""
        if not self.running or self.current_session_id is None or self.start_time is None:
            return
        duration = max(0.0, time.mktime(end_dt.timetuple()) - self.start_time)
        self.cur.execute(
            "UPDATE sessions SET end_ts = ?, duration_sec = ? WHERE id = ?;",
            (end_dt.strftime("%Y-%m-%d %H:%M:%S"), round(duration, 2), self.current_session_id)
        )
        self.conn.commit()

    def _finalize_current_session_row(self, end_dt: datetime):
        """Finalize the current session (update row one last time, then clear id)."""
        self._update_current_session_row(end_dt)
        self.current_session_id = None

    def _start_activity(self, name):
        """Stop & log previous session (update row), then start a new session for 'name'."""
        self._save_previous_activity_if_running()
        self.current_activity_name = name
        self.current_activity_id = self._get_or_create_activity(name)
        self.running = True
        now = datetime.now()
        self.start_time = time.mktime(now.timetuple())
        self.start_timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        self._last_autosave_dt = now.replace(microsecond=0)

        # create a live session row immediately
        self._create_new_session_row(now)

        # Overlay policy
        if name == "Waste":
            self._ensure_overlay_visible()
            self._apply_overlay_size(WASTE_SIZE)
            self._position_overlay_default()
        else:
            self._apply_overlay_size(NORMAL_SIZE)

        self._render_overlay_text(self._current_time_text())

    def _save_previous_activity_if_running(self):
        """Finalize current session (update its row)."""
        if self.running and self.current_activity_id is not None and self.start_time is not None:
            end_dt = datetime.now()
            self._finalize_current_session_row(end_dt)
            self.running = False
            self.start_time = None
            self.start_timestamp = None

    # Midnight rollover support
    def _rollover_midnight_if_needed(self, reference_dt: datetime, now_dt: datetime):
        """If the day changed between reference_dt and now_dt, split at midnight:
           - add remaining seconds to yesterday's daily_totals
           - finalize yesterday's session row at 23:59:59/00:00:00 boundary
           - start a new session row at today's 00:00:00 with same activity
        """
        if not self.running or self.current_activity_id is None:
            return reference_dt

        if reference_dt.date() == now_dt.date():
            return reference_dt

        midnight = datetime.combine(reference_dt.date() + timedelta(days=1), dtime.min)
        secs_to_midnight = (midnight - reference_dt).total_seconds()
        if secs_to_midnight > 0:
            # Add to yesterday totals
            self._add_to_daily_total(reference_dt.date(), self.current_activity_id, secs_to_midnight)
            # Finalize current session row exactly at midnight
            self._finalize_current_session_row(midnight)

        # Start a fresh session from midnight with the same activity
        self.running = True
        self.start_time = time.mktime(midnight.timetuple())
        self.start_timestamp = midnight.strftime("%Y-%m-%d %H:%M:%S")
        self._create_new_session_row(midnight)

        return midnight

    # -------------------- AUTOSAVE (every minute) --------------------
    def _schedule_autosave(self):
        self.root.after(self._autosave_interval_ms, self._autosave_tick)

    def _autosave_tick(self):
        try:
            self._do_autosave()
        finally:
            self._schedule_autosave()

    def _do_autosave(self):
        """Persist progress at most once per minute.
           - Updates daily_totals for the running activity.
           - Updates the live 'sessions' row's end_ts and duration_sec.
           - Handles midnight rollover.
        """
        now_dt = datetime.now().replace(microsecond=0)
        ref = self._last_autosave_dt

        if not self.running or self.current_activity_id is None:
            self._last_autosave_dt = now_dt
            return

        # Handle day change
        ref = self._rollover_midnight_if_needed(ref, now_dt)

        # Accumulate elapsed seconds since last autosave
        delta_sec = (now_dt - ref).total_seconds()
        if delta_sec > 0:
            self._add_to_daily_total(now_dt.date(), self.current_activity_id, delta_sec)
            self._last_autosave_dt = now_dt

        # Always update the current session row's end/duration
        self._update_current_session_row(now_dt)

        # Re-render overlay (daily totals line)
        self._render_overlay_text(self._current_time_text())

    def _add_to_daily_total(self, date_obj, activity_id, seconds):
        date_str = date_obj.strftime("%Y-%m-%d")
        self.cur.execute("""
            INSERT INTO daily_totals(date, activity_id, seconds)
            VALUES(?,?,?)
            ON CONFLICT(date, activity_id) DO UPDATE SET
              seconds = seconds + excluded.seconds;
        """, (date_str, activity_id, float(seconds)))
        self.conn.commit()

    def _get_today_totals(self):
        today = datetime.now().strftime("%Y-%m-%d")
        rows = self.cur.execute("""
            SELECT a.name, dt.seconds
            FROM daily_totals dt
            JOIN activities a ON a.id = dt.activity_id
            WHERE dt.date = ?
        """, (today,)).fetchall()
        return {name: float(sec) for name, sec in rows}

    # -------------------- Switch / Start / Stop --------------------
    def _switch_activity(self):
        selected = self.activity_var.get()
        if selected == "Custom":
            prev = self.current_activity_name or self._first_non_custom_activity()
            self.activity_var.set(prev)
            custom = simpledialog.askstring("Custom Activity", "Enter activity name:")
            if custom:
                self._get_or_create_activity(custom)
                self._build_activity_radios()
                self.activity_var.set(custom)
                self._start_activity(custom)
            return
        self._start_activity(selected)

    def start(self):
        if not self.running:
            name = self.activity_var.get() or self._first_non_custom_activity()
            self._start_activity(name)

    def stop(self):
        # Final autosave increment + finalize live session row
        self._do_autosave()
        self._save_previous_activity_if_running()

    # -------------------- Overlay helpers --------------------
    def toggle_overlay(self):
        if self.current_activity_name == "Waste":
            self._ensure_overlay_visible()
            return
        if self.overlay is None or not tk.Toplevel.winfo_exists(self.overlay):
            self._create_overlay()
        else:
            self.overlay.destroy()
            self.overlay = None
            self.overlay_canvas = None

    def toggle_daily_totals(self):
        self.show_daily_totals = not self.show_daily_totals
        self._render_overlay_text(self._current_time_text())

    def _ensure_overlay_visible(self):
        if self.overlay is None or not tk.Toplevel.winfo_exists(self.overlay):
            self._create_overlay()

    def _position_overlay_default(self):
        if self.overlay is None or not tk.Toplevel.winfo_exists(self.overlay):
            return
        self.overlay.update_idletasks()
        w = self.overlay.winfo_width() or 300
        sw = self.overlay.winfo_screenwidth()
        x = (sw - w) // 2
        y = 40
        self.overlay.geometry(f"+{x}+{y}")

    def _apply_overlay_size(self, size):
        self.overlay_font_size = int(size)
        self.overlay_size_var.set(self.overlay_font_size)
        self.overlay_font_tuple = ("Consolas", self.overlay_font_size, "bold")
        self.overlay_font_metrics.configure(size=self.overlay_font_size)
        # resize subordinate fonts (use emoji-capable font for icons & daily row)
        self.overlay_icon_font_metrics = self._make_icon_font(self._icon_size_for(self.overlay_font_size))
        self.overlay_sub_font_metrics  = self._make_icon_font(self._sub_size_for(self.overlay_font_size))
        self._render_overlay_text(self._current_time_text())

    def _on_overlay_size_change(self, value):
        self._apply_overlay_size(int(float(value)))

    # -------------------- Transparent overlay (Canvas + shadow + icon + daily line) --------------------
    def _create_overlay(self):
        if self.overlay is not None and tk.Toplevel.winfo_exists(self.overlay):
            return

        self.overlay = Toplevel(self.root)
        self.overlay.overrideredirect(True)
        self.overlay.attributes("-topmost", True)
        self.overlay.configure(bg=self.TRANSPARENT_COLOR)

        try:
            self.overlay.attributes("-transparentcolor", self.TRANSPARENT_COLOR)
            self._overlay_supports_color = True
        except tk.TclError:
            self._overlay_supports_color = False
            self.overlay.attributes("-alpha", 0.5)

        self.overlay_canvas = tk.Canvas(
            self.overlay, bg=self.TRANSPARENT_COLOR, highlightthickness=0, bd=0
        )
        self.overlay_canvas.pack()

        self._position_overlay_default()
        self._render_overlay_text(self._current_time_text())

        # Drag to move
        self._drag_data = {"x": 0, "y": 0}
        self.overlay_canvas.bind("<ButtonPress-1>", self._start_move)
        self.overlay_canvas.bind("<B1-Motion>", self._do_move)
        # Double-click toggle (blocked during Waste)
        self.overlay_canvas.bind("<Double-Button-1>", lambda e: self.toggle_overlay())

    def _start_move(self, event):
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def _do_move(self, event):
        x = event.x_root - self._drag_data["x"]
        y = event.y_root - self._drag_data["y"]
        self.overlay.geometry(f"+{x}+{y}")

    def _activity_shadow_color(self):
        name = self.current_activity_name or self.activity_var.get() or ""
        return COLOR_MAP.get(name, "gray")

    def _activity_icon(self):
        name = self.current_activity_name or self.activity_var.get() or ""
        return ICON_MAP.get(name, ICON_FALLBACK.get(name, ""))

    def _icon_for_name(self, name: str) -> str:
        return ICON_MAP.get(name, ICON_FALLBACK.get(name, name))

    def _icon_size_for(self, time_font_size: int) -> int:
        # keep your larger main icon near the clock (0.9x as in your v9)
        return max(int(time_font_size * 0.90), 12)

    def _sub_size_for(self, time_font_size: int) -> int:
        # daily totals line a bit smaller
        return max(int(time_font_size * 0.30), 8)

    def _make_icon_font(self, size: int) -> tkfont.Font:
        try:
            return tkfont.Font(family="Segoe UI Emoji", size=size, weight="bold")
        except Exception:
            return tkfont.Font(family="Consolas", size=size, weight="bold")

    def _render_overlay_text(self, text):
        if self.overlay_canvas is None:
            return

        pad = 8
        offset = 2        # shadow px
        gap = 8           # space between icon and time
        line_gap = 2      # gap between main line and daily totals line

        icon_text = self._activity_icon()

        # --- Fonts ---
        icon_font = self.overlay_icon_font_metrics
        time_font = self.overlay_font_metrics
        sub_font  = self.overlay_sub_font_metrics

        # --- Measurements (line 1) ---
        icon_w = icon_font.measure(icon_text) if icon_text else 0
        icon_h = icon_font.metrics("linespace") if icon_text else 0
        time_w = time_font.measure(text)
        time_h = time_font.metrics("linespace")
        line1_w = icon_w + (gap if icon_text else 0) + time_w
        line1_h = max(icon_h, time_h)

        # --- Daily totals string (line 2) — USE ICONS ---
        daily_line = ""
        if self.show_daily_totals:
            totals = self._get_today_totals()
            entries = []
            for name in DEFAULT_ACTIVITIES:
                secs = int(totals.get(name, 0))
                entries.append(f"{self._icon_for_name(name)} {self._fmt_short(secs)}")
            daily_line = "  •  ".join(entries)

        line2_w = sub_font.measure(daily_line) if daily_line else 0
        line2_h = sub_font.metrics("linespace") if daily_line else 0

        # --- Canvas size ---
        total_w = max(line1_w, line2_w) + 2*pad + offset
        total_h = line1_h + (line_gap + line2_h if daily_line else 0) + 2*pad + offset
        self.overlay_canvas.config(width=total_w, height=total_h)
        self.overlay_canvas.delete("all")

        # --- Baselines ---
        x0 = pad
        y0 = pad

        # ---- Draw line 1 (shadow) ----
        if icon_text:
            self.overlay_canvas.create_text(
                x0 + offset, y0 + offset, text=icon_text,
                font=(icon_font.cget("family"), icon_font.cget("size"), "bold"),
                fill=self._activity_shadow_color(), anchor="nw"
            )
        self.overlay_canvas.create_text(
            x0 + (icon_w + gap if icon_text else 0) + offset, y0 + offset, text=text,
            font=(time_font.cget("family"), time_font.cget("size"), "bold"),
            fill=self._activity_shadow_color(), anchor="nw"
        )

        # ---- Draw line 1 (foreground) ----
        if icon_text:
            self.overlay_canvas.create_text(
                x0, y0, text=icon_text,
                font=(icon_font.cget("family"), icon_font.cget("size"), "bold"),
                fill="black", anchor="nw"
            )
        self.overlay_canvas.create_text(
            x0 + (icon_w + gap if icon_text else 0), y0, text=text,
            font=(time_font.cget("family"), time_font.cget("size"), "bold"),
            fill="black", anchor="nw"
        )

        # ---- Draw line 2 (daily totals) ----
        if daily_line:
            y2 = y0 + line1_h + line_gap
            # shadow
            self.overlay_canvas.create_text(
                x0 + offset, y2 + offset, text=daily_line,
                font=(sub_font.cget("family"), sub_font.cget("size"), "bold"),
                fill=self._activity_shadow_color(), anchor="nw"
            )
            # foreground
            self.overlay_canvas.create_text(
                x0, y2, text=daily_line,
                font=(sub_font.cget("family"), sub_font.cget("size"), "bold"),
                fill="black", anchor="nw"
            )

    def _fmt_short(self, secs: int) -> str:
        h = secs // 3600
        m = (secs % 3600) // 60
        if h and m:
            return f"{h}h {m}m"
        if h:
            return f"{h}h"
        return f"{m}m"

    # -------------------- Clock --------------------
    def _current_time_text(self):
        if self.running and self.start_time is not None:
            elapsed = time.time() - self.start_time
        else:
            elapsed = 0.0
        mins, secs = divmod(elapsed, 60)
        hrs, mins = divmod(mins, 60)
        cs = int((elapsed - int(elapsed)) * 100)
        return f"{int(hrs):02}:{int(mins):02}:{int(secs):02}.{cs:02}"

    def _update_clock(self):
        # Safety net for day change between autosaves
        now_dt = datetime.now()
        if self.running:
            if now_dt.date() != self._last_autosave_dt.date():
                self._do_autosave()  # handles rollover + update
        text = self._current_time_text()
        self.clock_label.config(text=text)
        self._render_overlay_text(text)
        self.root.after(10, self._update_clock)

    # -------------------- Dashboard --------------------
    def open_settings(self):
        rows = self.cur.execute("""
            SELECT a.name, s.start_ts, s.end_ts, s.duration_sec
            FROM sessions s
            JOIN activities a ON s.activity_id = a.id
            ORDER BY s.start_ts DESC;
        """).fetchall()

        dashboard = Toplevel(self.root)
        dashboard.title("Activity Dashboard")
        dashboard.geometry("780x540")

        columns = ("Activity", "Start", "End", "Duration (sec)")
        tree = ttk.Treeview(dashboard, columns=columns, show="headings")
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=190 if col != "Duration (sec)" else 130, stretch=True)
        tree.pack(fill=tk.BOTH, expand=True)

        totals = defaultdict(float)
        for name, start_ts, end_ts, dur in rows:
            tree.insert("", tk.END, values=(name, start_ts, end_ts, dur))
            totals[name] += float(dur or 0)

        summary_frame = tk.Frame(dashboard)
        summary_frame.pack(fill=tk.X, pady=6)

        if HAS_MPL and totals:
            summary_lines = [f"{name}: {round(sec/60, 2)} min" for name, sec in sorted(totals.items())]
            tk.Label(summary_frame,
                     text="Total Time per Activity (all-time):\n" + "\n".join(summary_lines),
                     justify="left").pack(side=tk.LEFT, padx=10)

            fig, ax = plt.subplots(figsize=(4.8, 3.2))
            activities = list(totals.keys())
            durations_min = [sec/60 for sec in totals.values()]
            ax.bar(activities, durations_min)
            ax.set_title("Time Spent per Activity (all-time)")
            ax.set_ylabel("Minutes")
            ax.set_xlabel("Activity")
            plt.xticks(rotation=45, ha="right")

            canvas = FigureCanvasTkAgg(fig, master=summary_frame)
            canvas.draw()
            canvas.get_tk_widget().pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        else:
            tk.Label(summary_frame, text="No sessions logged yet.").pack(pady=8)
            if not HAS_MPL:
                tk.Label(summary_frame, text="Install matplotlib to see the chart.").pack(side=tk.RIGHT, padx=10)

    # -------------------- Global hotkeys --------------------
    def _register_hotkeys(self):
        combos = [
            (HK_WORK,     MOD_CONTROL | MOD_ALT, VK_HOME),
            (HK_STUDY,    MOD_CONTROL | MOD_ALT, VK_PRIOR),
            (HK_BREAK,    MOD_CONTROL | MOD_ALT, VK_NEXT),
            (HK_WASTE,    MOD_CONTROL | MOD_ALT, VK_END),
            (HK_PROJECTS, MOD_CONTROL | MOD_ALT, VK_LEFT),
        ]
        for _id, mod, vk in combos:
            try:
                user32.RegisterHotKey(None, _id, mod, vk)
            except Exception:
                pass

    def _unregister_hotkeys(self):
        for _id in (HK_WORK, HK_STUDY, HK_BREAK, HK_WASTE, HK_PROJECTS):
            try:
                user32.UnregisterHotKey(None, _id)
            except Exception:
                pass

    def _hotkey_loop(self):
        self._hotkey_thread_id = kernel32.GetCurrentThreadId()
        self._register_hotkeys()

        msg = wintypes.MSG()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:  # WM_QUIT or error
                break
            if msg.message == WM_HOTKEY:
                hk_id = msg.wParam
                self.root.after(0, self._on_hotkey, hk_id)
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        self._unregister_hotkeys()

    def _on_hotkey(self, hk_id):
        mapping = {
            HK_WORK: "Work",
            HK_STUDY: "Study",
            HK_BREAK: "Break",
            HK_WASTE: "Waste",
            HK_PROJECTS: "Projects",
        }
        name = mapping.get(int(hk_id))
        if not name:
            return
        self.activity_var.set(name)
        self._start_activity(name)

    # -------------------- Cleanup --------------------
    def _on_close(self):
        try:
            if self._hotkey_thread_id:
                user32.PostThreadMessageW(self._hotkey_thread_id, WM_QUIT, 0, 0)
        except Exception:
            pass
        # final autosave & finalize session
        self._do_autosave()
        self._save_previous_activity_if_running()
        try:
            self.conn.close()
        except Exception:
            pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = StopwatchApp(root)
    root.mainloop()
