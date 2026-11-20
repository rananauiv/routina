"""ROUTINA — Daily Habit Tracker UI + Analytics Dashboard

Tkinter frontend + a small SQLite database. Core application/business logic can
be connected in handle_ui_action().

JPG asset placeholders (optional):
    assets/background.jpg  -> background used on all screens
    assets/button.jpg      -> image used for menu/action buttons

The app still runs if those files or Pillow are absent; it uses a black/green
fallback theme. If running from Jupyter, the database and assets are resolved
from the current working directory. When run as a .py file, they are resolved
next to this file.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog

APP_NAME = "ROUTINA — Daily Habit Tracker"
GREEN = "#20d20d"
GREEN_DARK = "#127c08"
GREEN_LIGHT = "#5aff4c"
BLACK = "#000000"
WHITE = "#f7f7f7"
DARK = "#101010"
CARD_BG = "#161616"
CARD_BORDER = "#2c2c2c"
MUTED = "#a9a9a9"

# Placeholder asset paths: replace these JPG files with your own assets.
# JPG loading needs Pillow (`pip install pillow`). Missing assets are harmless.
if "__file__" in globals():
    APP_DIR = Path(__file__).resolve().parent
else:
    APP_DIR = Path.cwd()
ASSET_DIR = APP_DIR / "assets"
BACKGROUND_JPG = ASSET_DIR / "background.jpg"  # PLACEHOLDER asset path
BUTTON_JPG = ASSET_DIR / "button.jpg"            # PLACEHOLDER asset path
DB_PATH = APP_DIR / "routina_data.sqlite3"

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class RoutinaApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("940x760")
        self.root.minsize(700, 580)
        self.root.configure(bg=BLACK)
        self.db = sqlite3.connect(DB_PATH)
        self.db.row_factory = sqlite3.Row
        self._create_database()
        self._image_refs = []
        self._background_label = None
        self._button_image = None
        self._load_assets()
        self.show_home()
        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)

    def _create_database(self):
        """Create the external database tables if they do not already exist."""
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS habits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                schedule TEXT NOT NULL CHECK(schedule IN ('Every day','Weekdays','Weekends')),
                created_at TEXT NOT NULL
            )""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS habit_completions (
                habit_id INTEGER NOT NULL,
                completion_date TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (habit_id, completion_date),
                FOREIGN KEY (habit_id) REFERENCES habits(id) ON DELETE CASCADE
            )""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )""")

    def _load_assets(self):
        if not PIL_AVAILABLE:
            return
        try:
            if BACKGROUND_JPG.exists():
                img = Image.open(BACKGROUND_JPG).convert("RGB")
                img.thumbnail((1400, 1000))
                self._background_image = ImageTk.PhotoImage(img)
            if BUTTON_JPG.exists():
                img = Image.open(BUTTON_JPG).convert("RGB")
                self._button_image = ImageTk.PhotoImage(img.resize((280, 62)))
        except Exception as exc:
            # Placeholder fallback: if an image is invalid, use themed Tk widgets.
            print(f"Could not load optional JPG assets: {exc}")

    def _clear(self):
        for child in self.root.winfo_children():
            child.destroy()
        self._image_refs = []
        if PIL_AVAILABLE and hasattr(self, "_background_image"):
            self._background_label = tk.Label(self.root, image=self._background_image, bd=0)
            self._background_label.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._background_label.lower()

    def _button(self, parent, text, command, *, width=22, font_size=18, accent=True):
        # Uses the optional JPG button asset when provided; otherwise styled Tk button.
        if self._button_image is not None:
            btn = tk.Button(parent, text=text, image=self._button_image, compound="center",
                            command=command, fg=GREEN if accent else WHITE,
                            bg=BLACK, activebackground="#202020", activeforeground=GREEN,
                            font=("Arial", font_size, "italic"), bd=0, cursor="hand2")
        else:
            btn = tk.Button(parent, text=text, command=command, width=width,
                            fg=GREEN if accent else WHITE, bg=BLACK,
                            activebackground="#202020", activeforeground=GREEN,
                            font=("Arial", font_size, "italic"), bd=3,
                            relief="ridge", highlightthickness=0, cursor="hand2",
                            padx=16, pady=10)
        return btn

    def _title(self, parent, title, subtitle=None):
        tk.Label(parent, text=title, bg=BLACK, fg=GREEN,
                 font=("Arial", 34, "bold italic")).pack(pady=(18, 0))
        if subtitle:
            tk.Label(parent, text=subtitle, bg=BLACK, fg=GREEN,
                     font=("Arial", 14, "italic")).pack(pady=(0, 16))

    def handle_ui_action(self, action, data=None):
        """Integration placeholder for your own core Python code."""
        print(f"UI ACTION: {action} | data={data}")

    def show_home(self):
        self._clear()
        frame = tk.Frame(self.root, bg=BLACK)
        frame.place(relx=0.5, rely=0.5, anchor="center")
        self._title(frame, "ROUTINA", "Daily Habit Tracker")
        tk.Frame(frame, bg=BLACK, height=30).pack()
        self._button(frame, "📊  Dashboard", self._open_dashboard, width=22, font_size=20).pack(pady=8, ipady=5)
        self._button(frame, "✓  Habits", self._open_habits, width=22, font_size=20).pack(pady=8, ipady=5)
        self._button(frame, "📝  Tasks", self._open_tasks, width=22, font_size=20).pack(pady=8, ipady=5)
        self._button(frame, "Quit", self.quit_app, width=22, font_size=20, accent=False).pack(pady=8, ipady=5)

    def _open_dashboard(self):
        self.handle_ui_action("open_dashboard")
        self.show_dashboard()

    def _open_habits(self):
        self.handle_ui_action("open_habits")
        self.show_habits()

    def _open_tasks(self):
        self.handle_ui_action("open_tasks")
        self.show_tasks()

    # =========================================================================
    # DASHBOARD VIEW & ANALYTICS
    # =========================================================================

    def _calculate_streak(self, habit_id: int) -> int:
        """Calculate consecutive completed days for a given habit up to today/yesterday."""
        rows = self.db.execute(
            "SELECT completion_date FROM habit_completions WHERE habit_id=? AND completed=1 ORDER BY completion_date DESC",
            (habit_id,)
        ).fetchall()
        if not rows:
            return 0

        dates_done = {datetime.fromisoformat(r["completion_date"]).date() for r in rows}
        today = date.today()

        # If completed today, start counting from today; otherwise check if yesterday was completed
        current = today if today in dates_done else today - timedelta(days=1)
        streak = 0
        while current in dates_done:
            streak += 1
            current -= timedelta(days=1)
        return streak

    def _get_habits_due_today(self):
        """Returns habits scheduled for today."""
        today = date.today()
        day_schedule = ("Weekends", "Every day") if today.weekday() >= 5 else ("Weekdays", "Every day")
        placeholders = ",".join("?" for _ in day_schedule)
        return self.db.execute(
            f"SELECT * FROM habits WHERE schedule IN ({placeholders}) ORDER BY id", day_schedule
        ).fetchall()

    def show_dashboard(self):
        self._clear()

        # Top navigation
        top = tk.Frame(self.root, bg=BLACK)
        top.pack(fill="x", padx=20, pady=(12, 0))
        self._button(top, "← Home", self.show_home, width=10, font_size=12, accent=False).pack(side="left")
        
        # Shortcut buttons on the top right
        self._button(top, "+ Add habit", self.add_habit, width=12, font_size=11).pack(side="right", padx=(5, 0))
        self._button(top, "+ Add task", self.add_task, width=12, font_size=11, accent=False).pack(side="right")

        self._title(self.root, "Dashboard", "Daily progress, streaks & habit trends")

        # Scrollable container for the dashboard content
        canvas = tk.Canvas(self.root, bg=BLACK, highlightthickness=0)
        scrollbar = tk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        body = tk.Frame(canvas, bg=BLACK)

        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=body, anchor="nw")

        def _on_canvas_configure(e):
            canvas.itemconfig(canvas_window, width=e.width)
        canvas.bind("<Configure>", _on_canvas_configure)

        # Mousewheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(20, 0), pady=(0, 10))
        scrollbar.pack(side="right", fill="y", padx=(0, 10), pady=(0, 10))

        # --- DATA GATHERING ---
        today_iso = date.today().isoformat()
        all_habits = self.db.execute("SELECT * FROM habits").fetchall()
        habits_due = self._get_habits_due_today()
        
        total_due_count = len(habits_due)
        completed_habits_today = 0
        habit_status_list = []
        for h in habits_due:
            row = self.db.execute(
                "SELECT completed FROM habit_completions WHERE habit_id=? AND completion_date=?",
                (h["id"], today_iso)
            ).fetchone()
            is_done = bool(row and row["completed"])
            if is_done:
                completed_habits_today += 1
            habit_status_list.append((h, is_done))

        habit_pct = int((completed_habits_today / total_due_count) * 100) if total_due_count > 0 else 0

        # Tasks metrics
        total_tasks = self.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        completed_tasks = self.db.execute("SELECT COUNT(*) FROM tasks WHERE completed=1").fetchone()[0]
        pending_tasks = total_tasks - completed_tasks
        task_pct = int((completed_tasks / total_tasks) * 100) if total_tasks > 0 else 0

        # Streaks
        best_streak = 0
        best_habit_name = "None"
        for h in all_habits:
            st = self._calculate_streak(h["id"])
            if st > best_streak:
                best_streak = st
                best_habit_name = h["name"]

        # --- KPI SUMMARY CARDS ---
        cards_frame = tk.Frame(body, bg=BLACK)
        cards_frame.pack(fill="x", padx=10, pady=(4, 14))

        # 4 Responsive-feeling Summary Cards
        self._render_kpi_card(
            cards_frame,
            title="TODAY'S HABITS",
            value=f"{completed_habits_today}/{total_due_count}",
            subtitle=f"{habit_pct}% completed today",
            progress=habit_pct / 100.0,
            column=0
        )
        self._render_kpi_card(
            cards_frame,
            title="PENDING TASKS",
            value=f"{pending_tasks}",
            subtitle=f"{completed_tasks} completed ({task_pct}%)",
            progress=task_pct / 100.0,
            column=1
        )
        self._render_kpi_card(
            cards_frame,
            title="TOTAL HABITS",
            value=f"{len(all_habits)}",
            subtitle="Active tracked routines",
            progress=1.0 if all_habits else 0.0,
            column=2
        )
        self._render_kpi_card(
            cards_frame,
            title="BEST STREAK",
            value=f"{best_streak} Days",
            subtitle=f"Lead: {best_habit_name[:14]}",
            progress=min(best_streak / 30.0, 1.0) if best_streak else 0.0,
            column=3
        )
        for c in range(4):
            cards_frame.columnconfigure(c, weight=1)

        # --- 7-DAY ACTIVITY CHART ---
        chart_section = tk.Frame(body, bg=CARD_BG, highlightbackground=CARD_BORDER, highlightthickness=1)
        chart_section.pack(fill="x", padx=10, pady=(0, 16))

        tk.Label(
            chart_section,
            text="7-DAY HABIT COMPLETION ACTIVITY",
            bg=CARD_BG,
            fg=GREEN,
            font=("Arial", 14, "bold")
        ).pack(anchor="w", padx=16, pady=(12, 4))

        self._render_activity_chart(chart_section)

        # --- LOWER SECTION: 2 COLUMNS (Today's Check-in & Tasks Overview) ---
        bottom_frame = tk.Frame(body, bg=BLACK)
        bottom_frame.pack(fill="both", expand=True, padx=10, pady=(0, 20))
        bottom_frame.columnconfigure(0, weight=1)
        bottom_frame.columnconfigure(1, weight=1)

        # Left Column: Today's Habit Quick-Checkin
        habits_col = tk.Frame(bottom_frame, bg=CARD_BG, highlightbackground=CARD_BORDER, highlightthickness=1)
        habits_col.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=4)

        tk.Label(
            habits_col,
            text="TODAY'S HABIT CHECKLIST (Tap to toggle)",
            bg=CARD_BG,
            fg=GREEN,
            font=("Arial", 13, "bold")
        ).pack(anchor="w", padx=14, pady=(10, 6))

        if not habit_status_list:
            tk.Label(
                habits_col,
                text="No habits scheduled for today.\nAdd one with '+ Add habit'.",
                bg=CARD_BG,
                fg=MUTED,
                font=("Arial", 11),
                justify="left"
            ).pack(anchor="w", padx=14, pady=10)
        else:
            for h, is_done in habit_status_list:
                streak = self._calculate_streak(h["id"])
                prefix = "✓  " if is_done else "○  "
                streak_text = f" ({streak}d streak)" if streak > 0 else ""
                btn = tk.Button(
                    habits_col,
                    text=f"{prefix}{h['name']}{streak_text}",
                    anchor="w",
                    command=lambda hid=h["id"]: self._toggle_habit_and_refresh_dashboard(hid),
                    fg=WHITE if is_done else GREEN,
                    bg="#1e1e1e" if is_done else BLACK,
                    activebackground="#2a2a2a",
                    activeforeground=GREEN,
                    font=("Arial", 11, "bold" if not is_done else "normal"),
                    bd=1,
                    relief="solid",
                    padx=10,
                    pady=6,
                    cursor="hand2"
                )
                btn.pack(fill="x", padx=14, pady=3)

        tk.Frame(habits_col, bg=CARD_BG, height=8).pack()

        # Right Column: Tasks Overview
        tasks_col = tk.Frame(bottom_frame, bg=CARD_BG, highlightbackground=CARD_BORDER, highlightthickness=1)
        tasks_col.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=4)

        tk.Label(
            tasks_col,
            text="TASKS OVERVIEW (Tap to toggle)",
            bg=CARD_BG,
            fg=GREEN,
            font=("Arial", 13, "bold")
        ).pack(anchor="w", padx=14, pady=(10, 6))

        recent_tasks = self.db.execute(
            "SELECT * FROM tasks ORDER BY completed ASC, id DESC LIMIT 6"
        ).fetchall()

        if not recent_tasks:
            tk.Label(
                tasks_col,
                text="No tasks registered yet.\nAdd tasks to track to-dos.",
                bg=CARD_BG,
                fg=MUTED,
                font=("Arial", 11),
                justify="left"
            ).pack(anchor="w", padx=14, pady=10)
        else:
            for t in recent_tasks:
                done = bool(t["completed"])
                prefix = "✓  " if done else "○  "
                btn = tk.Button(
                    tasks_col,
                    text=f"{prefix}{t['name']}",
                    anchor="w",
                    command=lambda tid=t["id"]: self._toggle_task_and_refresh_dashboard(tid),
                    fg=MUTED if done else GREEN,
                    bg="#1e1e1e" if done else BLACK,
                    activebackground="#2a2a2a",
                    activeforeground=GREEN,
                    font=("Arial", 11),
                    bd=1,
                    relief="solid",
                    padx=10,
                    pady=6,
                    cursor="hand2"
                )
                btn.pack(fill="x", padx=14, pady=3)

        tk.Frame(tasks_col, bg=CARD_BG, height=8).pack()

    def _render_kpi_card(self, parent, title, value, subtitle, progress, column):
        card = tk.Frame(parent, bg=CARD_BG, highlightbackground=CARD_BORDER, highlightthickness=1)
        card.grid(row=0, column=column, sticky="nsew", padx=4, pady=4)

        tk.Label(card, text=title, bg=CARD_BG, fg=MUTED, font=("Arial", 10, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
        tk.Label(card, text=value, bg=CARD_BG, fg=GREEN, font=("Arial", 22, "bold")).pack(anchor="w", padx=12, pady=(0, 2))
        tk.Label(card, text=subtitle, bg=CARD_BG, fg=WHITE, font=("Arial", 9)).pack(anchor="w", padx=12, pady=(0, 8))

        # Progress bar
        bar_bg = tk.Frame(card, bg="#262626", height=6)
        bar_bg.pack(fill="x", padx=12, pady=(0, 10))
        progress = max(0.0, min(1.0, progress))
        if progress > 0:
            fill_bar = tk.Frame(bar_bg, bg=GREEN, height=6)
            fill_bar.place(relx=0, rely=0, relwidth=progress, relheight=1)

    def _render_activity_chart(self, parent):
        """Draws a responsive 7-day bar chart of habit completions using pure Tkinter Canvas."""
        days = [date.today() - timedelta(days=i) for i in range(6, -1, -1)]
        counts = []
        for d in days:
            c = self.db.execute(
                "SELECT COUNT(*) FROM habit_completions WHERE completion_date=? AND completed=1",
                (d.isoformat(),)
            ).fetchone()[0]
            counts.append(c)

        max_val = max(counts) if counts and max(counts) > 0 else 5

        chart_height = 140
        canvas = tk.Canvas(parent, bg=CARD_BG, height=chart_height, highlightthickness=0)
        canvas.pack(fill="x", expand=True, padx=16, pady=(4, 12))

        def draw_bars(event):
            canvas.delete("all")
            width = event.width
            num_bars = len(days)
            bar_spacing = width / num_bars
            bar_width = min(48, bar_spacing * 0.55)

            # Draw horizontal reference lines
            canvas.create_line(10, chart_height - 30, width - 10, chart_height - 30, fill="#2a2a2a", width=1)
            canvas.create_line(10, 15, width - 10, 15, fill="#202020", width=1, dash=(3, 3))

            for i, (d, count) in enumerate(zip(days, counts)):
                center_x = bar_spacing * i + (bar_spacing / 2)
                x1 = center_x - bar_width / 2
                x2 = center_x + bar_width / 2

                # Bar height calculation
                avail_h = chart_height - 55
                val_h = (count / max_val) * avail_h if max_val > 0 else 0
                y2 = chart_height - 30
                y1 = y2 - val_h

                is_today = (d == date.today())
                bar_color = GREEN_LIGHT if is_today else GREEN

                # Draw bar container slot (background track)
                canvas.create_rectangle(x1, 15, x2, y2, fill="#1c1c1c", outline="#272727", width=1)

                # Draw filled bar if count > 0
                if count > 0:
                    canvas.create_rectangle(x1, y1, x2, y2, fill=bar_color, outline="", width=0)

                # Number count above bar
                canvas.create_text(
                    center_x,
                    y1 - 8 if count > 0 else y2 - 8,
                    text=str(count),
                    fill=WHITE if count > 0 else MUTED,
                    font=("Arial", 9, "bold")
                )

                # Day label
                day_label = "Today" if is_today else d.strftime("%a %d")
                canvas.create_text(
                    center_x,
                    chart_height - 14,
                    text=day_label,
                    fill=GREEN if is_today else MUTED,
                    font=("Arial", 9, "bold" if is_today else "normal")
                )

        canvas.bind("<Configure>", draw_bars)

    def _toggle_habit_and_refresh_dashboard(self, habit_id):
        self.toggle_habit(habit_id)
        self.show_dashboard()

    def _toggle_task_and_refresh_dashboard(self, task_id):
        self.toggle_task(task_id)
        self.show_dashboard()

    # =========================================================================
    # HABITS VIEW
    # =========================================================================

    def show_habits(self):
        self._clear()
        top = tk.Frame(self.root, bg=BLACK)
        top.pack(fill="x", padx=18)
        self._button(top, "← Home", self.show_home, width=10, font_size=12, accent=False).pack(side="left", pady=12)
        self._button(top, "📊 Dashboard", self.show_dashboard, width=12, font_size=12, accent=False).pack(side="left", padx=10, pady=12)
        self._title(self.root, "Habits", "Tap a habit to toggle today's completion")

        controls = tk.Frame(self.root, bg=BLACK)
        controls.pack(pady=(0, 8))
        self._button(controls, "+ Add habit", self.add_habit, width=13, font_size=12).pack(side="left", padx=5)
        self._button(controls, "Remove habit", self.remove_habit, width=13, font_size=12, accent=False).pack(side="left", padx=5)

        canvas = tk.Canvas(self.root, bg=BLACK, highlightthickness=0)
        scrollbar = tk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        body = tk.Frame(canvas, bg=BLACK)
        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(22, 0), pady=8)
        scrollbar.pack(side="right", fill="y", padx=(0, 12), pady=8)

        # Habit sections
        self._habit_section(body, "WEEKDAYS", ("Weekdays", "Every day"))
        self._habit_section(body, "WEEKENDS", ("Weekends", "Every day"))

    def _habit_section(self, parent, heading, schedules):
        section = tk.Frame(parent, bg=BLACK, highlightbackground="#454545", highlightthickness=1)
        section.pack(fill="x", expand=True, padx=8, pady=7)
        tk.Label(section, text=heading, bg=BLACK, fg=GREEN,
                 font=("Arial", 16, "bold")).pack(anchor="w", padx=12, pady=(8, 3))
        placeholders = ",".join("?" for _ in schedules)
        rows = self.db.execute(
            f"SELECT * FROM habits WHERE schedule IN ({placeholders}) ORDER BY id", schedules
        ).fetchall()
        if not rows:
            tk.Label(section, text="No habits yet — use + Add habit.", bg=BLACK,
                     fg=MUTED, font=("Arial", 11)).pack(anchor="w", padx=14, pady=8)
        for habit in rows:
            done_row = self.db.execute(
                "SELECT completed FROM habit_completions WHERE habit_id=? AND completion_date=?",
                (habit["id"], date.today().isoformat())
            ).fetchone()
            done = bool(done_row and done_row["completed"])
            streak = self._calculate_streak(habit["id"])
            streak_str = f"  ({streak}d streak)" if streak > 0 else ""
            label = ("✓  " if done else "○  ") + habit["name"] + streak_str
            btn = self._button(section, label,
                               lambda hid=habit["id"]: self.toggle_habit(hid),
                               width=35, font_size=13, accent=not done)
            btn.pack(fill="x", padx=12, pady=4)
        tk.Frame(section, bg=BLACK, height=5).pack()

    def add_habit(self):
        name = simpledialog.askstring("Add habit", "Enter a name for this habit:", parent=self.root)
        if not name or not name.strip():
            return
        schedule = self._schedule_dialog()
        if schedule is None:
            return
        with self.db:
            self.db.execute("INSERT INTO habits(name, schedule, created_at) VALUES(?,?,?)",
                            (name.strip(), schedule, datetime.now().isoformat(timespec="seconds")))
        self.handle_ui_action("add_habit", {"name": name.strip(), "schedule": schedule})
        self.show_habits()

    def _schedule_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("Habit schedule")
        win.configure(bg=BLACK)
        win.transient(self.root)
        win.grab_set()
        tk.Label(win, text="Repeat this habit on:", bg=BLACK, fg=WHITE,
                 font=("Arial", 12)).pack(padx=22, pady=(18, 8))
        choice = tk.StringVar(value="Every day")
        for option in ("Every day", "Weekdays", "Weekends"):
            tk.Radiobutton(win, text=option, variable=choice, value=option,
                           bg=BLACK, fg=GREEN, selectcolor=DARK, activebackground=BLACK,
                           activeforeground=GREEN).pack(anchor="w", padx=25)
        result = {"value": None}
        def save():
            result["value"] = choice.get()
            win.destroy()
        def cancel():
            win.destroy()
        self._button(win, "Save", save, width=12, font_size=12).pack(pady=(12, 5))
        self._button(win, "Cancel", cancel, width=12, font_size=12, accent=False).pack(pady=(0, 14))
        self.root.wait_window(win)
        return result["value"]

    def toggle_habit(self, habit_id):
        today = date.today().isoformat()
        row = self.db.execute(
            "SELECT completed FROM habit_completions WHERE habit_id=? AND completion_date=?",
            (habit_id, today)
        ).fetchone()
        new_value = 0 if row and row["completed"] else 1
        with self.db:
            self.db.execute("""INSERT INTO habit_completions(habit_id, completion_date, completed)
                VALUES(?,?,?) ON CONFLICT(habit_id, completion_date)
                DO UPDATE SET completed=excluded.completed""", (habit_id, today, new_value))
        self.handle_ui_action("toggle_habit", {"habit_id": habit_id, "completed": bool(new_value)})
        self.show_habits()

    def remove_habit(self):
        rows = self.db.execute("SELECT id, name, schedule FROM habits ORDER BY id").fetchall()
        if not rows:
            messagebox.showinfo("Remove habit", "There are no habits to remove.", parent=self.root)
            return
        options = "\n".join(f"{r['id']}: {r['name']} ({r['schedule']})" for r in rows)
        raw = simpledialog.askstring("Remove habit", "Enter the ID of the habit to remove:\n\n" + options,
                                     parent=self.root)
        if raw is None:
            return
        try:
            habit_id = int(raw.strip())
        except ValueError:
            messagebox.showerror("Invalid ID", "Please enter a numeric habit ID.", parent=self.root)
            return
        row = self.db.execute("SELECT name FROM habits WHERE id=?", (habit_id,)).fetchone()
        if not row:
            messagebox.showerror("Not found", "No habit has that ID.", parent=self.root)
            return
        with self.db:
            self.db.execute("DELETE FROM habits WHERE id=?", (habit_id,))
            self.db.execute("DELETE FROM habit_completions WHERE habit_id=?", (habit_id,))
        self.handle_ui_action("remove_habit", {"habit_id": habit_id, "name": row["name"]})
        self.show_habits()

    # =========================================================================
    # TASKS VIEW
    # =========================================================================

    def show_tasks(self):
        self._clear()
        top = tk.Frame(self.root, bg=BLACK)
        top.pack(fill="x", padx=18)
        self._button(top, "← Home", self.show_home, width=10, font_size=12, accent=False).pack(side="left", pady=12)
        self._button(top, "📊 Dashboard", self.show_dashboard, width=12, font_size=12, accent=False).pack(side="left", padx=10, pady=12)
        self._title(self.root, "Tasks", "Tap any task to toggle pending / completed")
        controls = tk.Frame(self.root, bg=BLACK)
        controls.pack(pady=(0, 8))
        self._button(controls, "+ Add task", self.add_task, width=13, font_size=12).pack(side="left", padx=5)
        self._button(controls, "Remove completed", self.remove_completed_tasks, width=17, font_size=12, accent=False).pack(side="left", padx=5)

        container = tk.Frame(self.root, bg=BLACK)
        container.pack(fill="both", expand=True, padx=24, pady=6)
        pending = self.db.execute("SELECT * FROM tasks WHERE completed=0 ORDER BY id").fetchall()
        completed = self.db.execute("SELECT * FROM tasks WHERE completed=1 ORDER BY id").fetchall()
        self._task_group(container, "PENDING", pending, False)
        self._task_group(container, "COMPLETED (tap to undo)", completed, True)

    def _task_group(self, parent, heading, rows, completed):
        group = tk.Frame(parent, bg=BLACK, highlightbackground="#454545", highlightthickness=1)
        group.pack(fill="x", pady=7)
        tk.Label(group, text=heading, bg=BLACK, fg=GREEN,
                 font=("Arial", 15, "bold")).pack(anchor="w", padx=12, pady=(8, 4))
        if not rows:
            tk.Label(group, text="Nothing here.", bg=BLACK, fg=MUTED,
                     font=("Arial", 11)).pack(anchor="w", padx=14, pady=7)
        for task in rows:
            prefix = "✓  " if completed else "○  "
            btn = self._button(group, prefix + task["name"],
                               lambda tid=task["id"]: self.toggle_task(tid),
                               width=38, font_size=13, accent=not completed)
            btn.pack(fill="x", padx=12, pady=4)

    def add_task(self):
        name = simpledialog.askstring("Add task", "Enter a name for this task:", parent=self.root)
        if not name or not name.strip():
            return
        with self.db:
            self.db.execute("INSERT INTO tasks(name, completed, created_at) VALUES(?,0,?)",
                            (name.strip(), datetime.now().isoformat(timespec="seconds")))
        self.handle_ui_action("add_task", {"name": name.strip()})
        self.show_tasks()

    def toggle_task(self, task_id):
        row = self.db.execute("SELECT completed FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return
        new_value = 0 if row["completed"] else 1
        with self.db:
            self.db.execute("UPDATE tasks SET completed=? WHERE id=?", (new_value, task_id))
        self.handle_ui_action("toggle_task", {"task_id": task_id, "completed": bool(new_value)})
        self.show_tasks()

    def remove_completed_tasks(self):
        count = self.db.execute("SELECT COUNT(*) FROM tasks WHERE completed=1").fetchone()[0]
        if count == 0:
            messagebox.showinfo("Remove completed", "There are no completed tasks to remove.", parent=self.root)
            return
        if messagebox.askyesno("Remove completed", f"Permanently remove {count} completed task(s)?", parent=self.root):
            with self.db:
                self.db.execute("DELETE FROM tasks WHERE completed=1")
            self.handle_ui_action("remove_completed_tasks", {"count": count})
            self.show_tasks()

    def quit_app(self):
        self.handle_ui_action("quit")
        try:
            self.db.close()
        finally:
            self.root.destroy()


def main():
    root = tk.Tk()
    RoutinaApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
