# Activity Logger (SQLite, Tkinter) — Technical Documentation

> **Platform:** Windows 10
> **Tech:** Python 3.x, Tkinter, SQLite, Matplotlib, Win32 global hotkeys (ctypes)
> **UI:** Main app (radios + buttons + normal clock) + **transparent overlay clock** (always-on-top, draggable)
> **Hotkeys:** Ctrl+Alt + (Home / PgUp / PgDn / End / Left) to switch activities

---

## Table of Contents

1. [Overview](#overview)
2. [Features](#features)
3. [How to Run](#how-to-run)
4. [Data Model (SQLite)](#data-model-sqlite)
5. [UI / UX Behavior](#ui--ux-behavior)
6. [Hotkeys](#hotkeys)
7. [Color & Icon Mapping](#color--icon-mapping)
8. [Configuration Constants](#configuration-constants)
9. [Class: `StopwatchApp`](#class-stopwatchapp)

   * [Constructor & Lifecycle](#constructor--lifecycle)
   * [Database Methods](#database-methods)
   * [UI Helpers](#ui-helpers)
   * [Activity Control](#activity-control)
   * [Overlay Helpers](#overlay-helpers)
   * [Transparent Overlay (Canvas)](#transparent-overlay-canvas)
   * [Clock](#clock)
   * [Dashboard](#dashboard)
   * [Global Hotkeys (Win32)](#global-hotkeys-win32)
   * [Cleanup](#cleanup)
10. [Control Flow Summary](#control-flow-summary)
11. [Extending the App](#extending-the-app)
12. [Known Limitations](#known-limitations)

---

## Overview

This app is a **time/activity logger** with a clean Tkinter UI and a **transparent, always-on-top** overlay clock.
Every activity session is saved to **SQLite**. Switching activities **stops & logs** the old session and **starts** the new one automatically.

---

## Features

* Live stopwatch clock (mm\:ss with centiseconds).
* **Activities as radio buttons**: Work, Study, Break, Waste, Projects (+ Custom).
* **Auto-start default** activity on launch.
* **Switching activity** auto-stops and logs previous session.
* **Transparent overlay clock** (movable, shadow color by activity, small icon before time).
* **“Waste” rules**: overlay becomes large, forced visible, and re-centered.
* **Global hotkeys** (Ctrl+Alt+key) to switch activities without focusing the app.
* **Dashboard**: table of sessions + total time per activity + bar chart.

---

## How to Run

```bash
pip install matplotlib
python activity_logger.py
```

> **Note:** Global hotkeys use Win32 APIs; run on **Windows**.

---

## Data Model (SQLite)

**Database file:** `activity_log.db`

### Tables

```sql
CREATE TABLE IF NOT EXISTS activities (
  id   INTEGER PRIMARY KEY,
  name TEXT UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS sessions (
  id           INTEGER PRIMARY KEY,
  activity_id  INTEGER NOT NULL,
  start_ts     TEXT NOT NULL,   -- "YYYY-MM-DD HH:MM:SS"
  end_ts       TEXT NOT NULL,
  duration_sec REAL NOT NULL,   -- e.g., 123.45
  FOREIGN KEY(activity_id) REFERENCES activities(id) ON DELETE CASCADE
);
```

* Default activities are seeded on first run: **Work, Study, Break, Waste, Projects** (+ `Custom` helper entry).

---

## UI / UX Behavior

* **Main window:**

  * Big digital clock (non-transparent).
  * Radio buttons for activity selection.
  * Buttons: **Start**, **Stop**, **Settings**, **Toggle Transparent Clock**.
  * Slider: **Overlay size** (24–120 px).
* **Transparent overlay:**

  * Black digits with a **colored shadow** (e.g., green for Work).
  * **Small icon/word** prefix (e.g., 💼 for Work).
  * Draggable; double-click to toggle **unless activity is “Waste”** (forced visible).
  * Uses `-transparentcolor` (fallback to semi-transparent alpha if unsupported).

---

## Hotkeys

> Active while the program is running (Windows only).
> **Fn** cannot be captured on Windows; combos are **Ctrl+Alt**:

| Activity | Keys (Global)           |
| -------- | ----------------------- |
| Work     | Ctrl + Alt + Home       |
| Study    | Ctrl + Alt + PageUp     |
| Break    | Ctrl + Alt + PageDown   |
| Waste    | Ctrl + Alt + End        |
| Projects | Ctrl + Alt + Left Arrow |

---

## Color & Icon Mapping

**Shadow color:**

* Work = **green**
* Study = **blue**
* Break = **gray**
* Waste = **red**
* Projects = **yellow**
* Other/unknown = gray

**Icon ahead of time (emoji with fallback):**

* Work = 💼 (fallback: WORK)
* Study = 📚 (fallback: STUDY)
* Break = 🏠 (fallback: HOME)
* Waste = 🛑 (fallback: WASTE)
* Projects = 🧩 (fallback: PROJ)

---

## Configuration Constants

```python
DB_FILE = "activity_log.db"

DEFAULT_ACTIVITIES = ["Work", "Study", "Break", "Waste", "Projects"]

COLOR_MAP = {
    "Work": "green",
    "Study": "blue",
    "Break": "gray",
    "Waste": "red",
    "Projects": "yellow",
}

NORMAL_SIZE = 36      # overlay font size for normal activities
WASTE_SIZE  = 96      # overlay font size when activity = Waste
```

---

## Class: `StopwatchApp`

### Constructor & Lifecycle

#### `__init__(self, root)`

**Purpose:** Build the UI, initialize DB/State, create overlay, start hotkeys, and start the clock loop.
**Key actions:**

* Connects to SQLite and seeds default activities.
* Sets state variables for timer and current activity.
* Creates main UI (clock label, radios, buttons, slider).
* Auto-selects first non-custom activity and **starts** it.
* Creates the **transparent overlay**.
* Starts the **Win32 hotkey** listener in a background thread.
* Registers `WM_DELETE_WINDOW` handler to clean up.

---

### Database Methods

#### `_init_db(self)`

* Creates tables `activities` and `sessions` if they do not exist.

#### `_seed_default_activities(self)`

* Inserts default activities (`DEFAULT_ACTIVITIES`) and ensures `"Custom"` exists.

#### `_load_activities(self) -> list[str]`

* Fetches activity names from DB, returns sorted list **with "Custom" last** (for UI).

#### `_get_or_create_activity(self, name) -> int`

* Ensures an activity row exists; returns its `id`.

---

### UI Helpers

#### `_build_activity_radios(self)`

* Rebuilds radio buttons from the DB list.
* Each radio button `command` → `_switch_activity`.

#### `_first_non_custom_activity(self) -> str`

* Returns the first activity that isn’t `"Custom"`.
* Fallback: `"Work"`.

---

### Activity Control

#### `_start_activity(self, name)`

**Purpose:** Stop/log the previous session and start a new one.
**Flow:**

1. `_save_previous_activity_if_running()` to finalize prior activity.
2. Set `current_activity_name/id`, `running=True`, `start_time=now`, `start_timestamp`.
3. Apply **overlay policy**:

   * If `name == "Waste"`:

     * `_ensure_overlay_visible()`
     * `_apply_overlay_size(WASTE_SIZE)`
     * `_position_overlay_default()` (top-center)
   * Else:

     * `_apply_overlay_size(NORMAL_SIZE)`
4. Re-render overlay text.

**Side effects:** Inserts into DB when switching from a running activity.

#### `_save_previous_activity_if_running(self)`

* If a session is running, computes duration and inserts a row into `sessions`.

#### `_switch_activity(self)`

* Triggered by radio selection.
* If `"Custom"` is selected:

  * Shows dialog to enter a name; creates activity; rebuilds radios; starts it.
* Otherwise, calls `_start_activity(selected)`.

#### `start(self)`

* Manual start (if not already running) for the current radio-selected activity.

#### `stop(self)`

* Manual stop; finalizes current session via `_save_previous_activity_if_running()`.

---

### Overlay Helpers

#### `_ensure_overlay_visible(self)`

* Creates the overlay window if it doesn’t exist.

#### `_position_overlay_default(self)`

* Positions overlay near the **top-center** of the primary screen.
* Called automatically when activity = **Waste**.

#### `_apply_overlay_size(self, size)`

* Updates time font size, syncs the slider, recalculates metrics, and requests re-render.

#### `_on_overlay_size_change(self, value)`

* Slider callback → calls `_apply_overlay_size()`.

---

### Transparent Overlay (Canvas)

#### `_create_overlay(self)`

**Purpose:** Create the borderless, transparent, always-on-top overlay.
**Key details:**

* Uses `-transparentcolor` if available; else fallback to `-alpha`.
* Creates a `Canvas` and binds:

  * **Drag** (`<ButtonPress-1>`, `<B1-Motion>`) → move window
  * **Double-click** to toggle (blocked if activity = Waste)
* Calls `_position_overlay_default()` and initial `_render_overlay_text()`.

#### `toggle_overlay(self)`

* Hides/shows the overlay.
* **Refuses** to hide when activity = **Waste**.

#### `_start_move(self, event)`

* Stores initial click position for dragging.

#### `_do_move(self, event)`

* Repositions overlay window during drag.

#### `_activity_shadow_color(self) -> str`

* Returns color based on `current_activity_name` using `COLOR_MAP` (default gray).

#### `_activity_icon(self) -> str`

* Returns emoji/icon string for current activity (fallback text if needed).

#### `_icon_size_for(self, time_font_size) -> int`

* Returns a smaller font size for the icon (\~40% of main time size, min 12px).

#### `_make_icon_font(self, size) -> tkfont.Font`

* Attempts to use **Segoe UI Emoji** (Windows). Falls back to **Consolas**.

#### `_render_overlay_text(self, text)`

**Purpose:** Draws the **colored shadow** + **black foreground** for the icon and time.
**Steps:**

1. Compute paddings, offsets, and the **gap** between icon and time.
2. Measure icon and time with **different fonts**.
3. Resize canvas to content.
4. Draw **shadow** at `(x+offset, y+offset)` using `_activity_shadow_color()`.
5. Draw **foreground** text in **black** at `(x, y)`.

---

### Clock

#### `_current_time_text(self) -> str`

* Formats current elapsed time as `"HH:MM:SS.CC"`.
* If not running, shows `00:00:00.00`.

#### `_update_clock(self)`

* Updates:

  * Main window clock label.
  * Transparent overlay content (via `_render_overlay_text()`).
* Reschedules itself every **10 ms** with `root.after(10, ...)`.

---

### Dashboard

#### `open_settings(self)`

* Builds a new **Toplevel** window.
* Runs a join query to fetch `sessions` with `activity` names.
* **Treeview** table (Activity, Start, End, Duration).
* **Summary** totals per activity (minutes).
* **Matplotlib bar chart** visualizing totals.

---

### Global Hotkeys (Win32)

> Implemented using `ctypes` with `RegisterHotKey` and a background message loop.

#### `_register_hotkeys(self)`

* Registers:

  * Work → Ctrl+Alt+Home
  * Study → Ctrl+Alt+PageUp
  * Break → Ctrl+Alt+PageDown
  * Waste → Ctrl+Alt+End
  * Projects → Ctrl+Alt+Left

#### `_unregister_hotkeys(self)`

* Unregisters all hotkeys (called when the thread exits).

#### `_hotkey_loop(self)`

* Runs on a **background thread**.
* Creates a Win32 **message loop** (`GetMessageW`, `DispatchMessageW`).
* On `WM_HOTKEY`, posts back to Tk’s main thread: `root.after(0, self._on_hotkey, hk_id)`.

#### `_on_hotkey(self, hk_id)`

* Maps ID → activity name, sets radio selection, and calls `_start_activity(name)`.

---

### Cleanup

#### `_on_close(self)`

* Posts `WM_QUIT` to the hotkey thread, so it can exit cleanly and **unregister** hotkeys.
* Saves any running session.
* Closes DB connection.
* Destroys Tk root window.

> The destructor also attempts to save+close as a last line of defense.

---

## Control Flow Summary

**On launch**

1. Init DB → seed activities → build UI → create overlay → start hotkey thread.
2. Select first non-custom activity, **start** it.
3. Clock updates every 10 ms.

**On radio change**

* If **Custom**: prompt, create, select, start.
* Else: **stop+log old**, **start new**.
* If new = **Waste**: enlarge overlay, force visible, **recenter**.

**On hotkey**

* Same as radio change (switch, log, start).

**On Stop**

* Finalizes and logs the running session.

**On Settings**

* Opens dashboard (table + totals + bar chart).

---

## Extending the App

* **Per-activity sizes**: Create a `settings` table and store last-used overlay size per activity.
* **Daily/weekly rollups**: Add GROUP BY day/week queries and charts.
* **CSV export**: Dump `sessions` to CSV from the dashboard.
* **Idle detection**: Pause/flag sessions after inactivity using mouse/keyboard hooks.

---

## Known Limitations

* **Windows-only hotkeys** (uses Win32). The rest of the app works cross-platform, but hotkeys will not.
* `-transparentcolor` support depends on **Tk build**. The app falls back to semi-transparent `-alpha` if needed.
* Emoji rendering depends on fonts (Windows has **Segoe UI Emoji**). Fallback text is provided.

---

