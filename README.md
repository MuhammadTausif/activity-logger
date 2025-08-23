# Activity Logger (SQLite, Tkinter) — Technical Documentation (v10)

> **Platform:** Windows 10
> **Tech:** Python 3.x, Tkinter, SQLite, *(optional)* Matplotlib, Win32 global hotkeys (ctypes)
> **UI:** Main app (radios + buttons + normal clock) + **transparent overlay clock** (always-on-top, draggable)
> **Hotkeys:** Ctrl+Alt + (Home / PgUp / PgDn / End / Left) to switch activities

---

## What’s new in this version

* **Live sessions:** a row in `sessions` is created **as soon as an activity starts** and its `end_ts` and `duration_sec` are **updated every minute** (and at stop/switch).
* **1-minute autosave:** running activity progress is saved to a new per-day aggregate table `daily_totals` **every minute**.
* **Midnight rollover:** if the app is running across midnight, it **finalizes yesterday’s session at 00:00**, adds the exact remainder to yesterday’s `daily_totals`, and **starts a fresh session** at 00:00 for today.
* **Daily totals overlay:** a **Toggle Daily Totals** button shows a second (smaller) line under the transparent clock containing **today’s totals per activity**, displayed as **icons** + compact time (e.g., `💼 2m • 📚 0m • 🏠 1m • 🛑 0m • 🧩 17m`).
* **Icons in the totals line:** names are replaced with their icons for a compact, glanceable display.
* **Waste rules retained:** selecting *Waste* enlarges the overlay, forces it visible, and recenters it.

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
   * [Autosave & Midnight Rollover](#autosave--midnight-rollover)
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
Every session is stored in **SQLite**, and **daily totals** are maintained continuously. Switching activities **stops & saves** the old session and **starts** the new one automatically.

---

## Features

* Live stopwatch clock (HH\:MM\:SS.CC).
* **Activities as radio buttons**: Work, Study, Break, Waste, Projects (+ Custom).
* **Auto-start default** activity on launch.
* **Switch activity** → stop/log previous, start new.
* **Transparent overlay clock** with a colored shadow, **leading icon**, and a **second line** showing **today’s totals** (toggle).
* **“Waste” rules**: overlay becomes large, forced visible, and re-centered.
* **Global hotkeys** (Ctrl+Alt+key) to switch activities without focusing the app.
* **1-minute autosave** updates the *running* session and **daily totals**.
* **Midnight rollover** splits the session exactly at day boundary and continues cleanly.
* **Dashboard**: table of sessions + all-time totals + *(optional)* bar chart.

---

## How to Run

```bash
# optional chart support
pip install matplotlib

# run
python activity_logger.py
```

> **Note:** Global hotkeys rely on Win32; use on **Windows**. For silent startup, run with `pythonw.exe`.

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
  end_ts       TEXT NOT NULL,   -- updated at least every minute
  duration_sec REAL NOT NULL,   -- updated at least every minute
  FOREIGN KEY(activity_id) REFERENCES activities(id) ON DELETE CASCADE
);

-- NEW: per-day aggregate, updated every minute while an activity runs
CREATE TABLE IF NOT EXISTS daily_totals (
  date        TEXT NOT NULL,    -- "YYYY-MM-DD"
  activity_id INTEGER NOT NULL,
  seconds     REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (date, activity_id),
  FOREIGN KEY(activity_id) REFERENCES activities(id) ON DELETE CASCADE
);
```

**Behavioral notes:**

* When an activity starts, a **new row** is inserted into `sessions` with `end_ts = start_ts` and `duration_sec = 0`.
  While it runs, the same row is **updated every minute** (and on stop/switch/rollover).
* `daily_totals` is **upserted** every minute: `seconds += elapsed_since_last_autosave`.

---

## UI / UX Behavior

* **Main window**

  * Big digital clock (non-transparent).
  * Radio buttons for activity selection.
  * Buttons: **Start**, **Stop**, **Settings**, **Toggle Transparent Clock**, **Toggle Daily Totals**.
  * Slider: **Overlay size** (24–120 px).
* **Transparent overlay**

  * Black digits with a **colored shadow** reflecting the current activity.
  * A **leading icon** for the current activity (e.g., 💼 before the time).
  * **Daily totals line** (smaller font) under the time, showing **icons** + compact durations (e.g., `💼 2m • 📚 0m • 🏠 1m • 🛑 0m • 🧩 17m`) — toggled by **Toggle Daily Totals**.
  * Drag anywhere to move; **double-click** to hide/show *(hidden action is blocked when Waste is active)*.
  * Uses `-transparentcolor` (falls back to `-alpha` if unsupported by Tk build).

---

## Hotkeys

> Active while the program is running.

| Activity | Global Keys             |
| -------- | ----------------------- |
| Work     | Ctrl + Alt + Home       |
| Study    | Ctrl + Alt + PageUp     |
| Break    | Ctrl + Alt + PageDown   |
| Waste    | Ctrl + Alt + End        |
| Projects | Ctrl + Alt + Left Arrow |

*(Fn cannot be captured on Windows; combinations use Ctrl+Alt.)*

---

## Color & Icon Mapping

* **Shadow colors:** Work=green, Study=blue, Break=gray, Waste=red, Projects=yellow.
* **Icons:** Work=💼, Study=📚, Break=🏠, Waste=🛑, Projects=🧩.
  *(Windows uses “Segoe UI Emoji”; fallback text labels are used if emojis aren’t available.)*

---

## Configuration Constants

```python
DEFAULT_ACTIVITIES = ["Work", "Study", "Break", "Waste", "Projects"]

NORMAL_SIZE = 36      # overlay font size for normal activities
WASTE_SIZE  = 96      # overlay font size when activity = Waste
```

---

## Class: `StopwatchApp`

### Constructor & Lifecycle

`__init__(self, root)`
Builds the UI; initializes DB and state; creates overlay; starts the hotkey listener thread; wires `WM_DELETE_WINDOW`; kicks off the 10 ms clock loop and the **1-minute autosave loop**.

---

### Database Methods

* `_init_db(self)` — Creates `activities`, `sessions`, and **`daily_totals`** tables if missing.
* `_seed_default_activities(self)` — Inserts default activities and ensures `"Custom"` exists.
* `_load_activities(self) -> list[str]` — Returns activity names (with `"Custom"` last).
* `_get_or_create_activity(self, name) -> int` — Upserts an activity and returns its id.

---

### UI Helpers

* `_build_activity_radios(self)` — Rebuilds the radio list; each radio triggers `_switch_activity`.
* `_first_non_custom_activity(self) -> str` — Returns the first non-custom activity (fallback: `"Work"`).

---

### Activity Control

* `_start_activity(self, name)`

  * Finalizes any running session.
  * Sets state, records `start_timestamp`, and **creates a new row in `sessions`** (`end_ts=start_ts`, `duration_sec=0`), remembering its `id`.
  * Applies overlay policy (Waste=visible+big+center; others=small) and re-renders overlay.

* `_save_previous_activity_if_running(self)`

  * **Finalizes the current session row** (updates `end_ts`/`duration_sec` one last time; clears live `session_id`).

* `_switch_activity(self)`

  * Handles `"Custom"` creation or starts the selected activity (stop old, start new).

* `start(self)` / `stop(self)`

  * Manual start/stop; **stop** forces a final autosave and finalizes the session row.

---

### Autosave & Midnight Rollover

* `_schedule_autosave(self)` / `_autosave_tick(self)` / `_do_autosave(self)`

  * Every minute, compute elapsed since the last tick and:

    1. **Upsert into `daily_totals`** for *today* (`seconds += delta`).
    2. **Update the live session row** (`end_ts`, `duration_sec`).
    3. Refresh overlay (so the daily line stays current).

* `_rollover_midnight_if_needed(self, reference_dt, now_dt)`

  * If the date changed between ticks:

    * Compute **seconds to midnight**, add them to **yesterday’s** `daily_totals`.
    * **Finalize** the current session row **exactly at midnight**.
    * **Start a new session** at today’s 00:00 with the same activity and create a fresh `sessions` row.
    * Return the new “reference” timestamp (midnight) for the next autosave delta.

---

### Overlay Helpers

* `toggle_overlay(self)` — Hide/show overlay; **refuses to hide** while *Waste* is active.
* `toggle_daily_totals(self)` — Show/hide the **daily totals** second line.
* `_ensure_overlay_visible(self)`, `_position_overlay_default(self)` — Manage overlay existence/placement (top-center).
* `_apply_overlay_size(self, size)` / `_on_overlay_size_change(self, value)` — Resize main time font and rebuild the icon/daily-line fonts; re-render.

---

### Transparent Overlay (Canvas)

* `_create_overlay(self)` — Creates a **frameless** `Toplevel` with per-color transparency (fallback to alpha), packs a `Canvas`, positions it, and draws initial content. Wires drag and double-click.
* `_render_overlay_text(self, text)` — Draws:

  * **Line 1:** current activity **icon** + stopwatch time (colored shadow + black foreground).
  * **Line 2 (optional):** **today’s totals** as *icons* + compact time, separated by bullets.
* Supporting helpers:

  * `_activity_shadow_color(self)` — color by activity.
  * `_activity_icon(self)` / `_icon_for_name(self)` — emoji or fallback for current/specified activity.
  * `_icon_size_for(self, time_font_size)` — icon size relative to the main time font.
  * `_sub_size_for(self, time_font_size)` — daily totals line font size (smaller).
  * `_make_icon_font(self, size)` — uses “Segoe UI Emoji” (fallback: Consolas).
  * Dragging: `_start_move(self, event)`, `_do_move(self, event)`.

---

### Clock

* `_current_time_text(self)` — Formats elapsed time as `HH:MM:SS.CC`.
* `_update_clock(self)` — Safety-checks date flips; updates the main label and overlay text every **10 ms**.

---

### Dashboard

* `open_settings(self)` — Builds a **Toplevel** with a `Treeview` of `sessions` and **all-time totals**.
  If Matplotlib is available, shows a **bar chart**; otherwise shows a prompt to install it.

---

### Global Hotkeys (Win32)

* `_register_hotkeys(self)` / `_unregister_hotkeys(self)` — Register/unregister Ctrl+Alt global hotkeys.
* `_hotkey_loop(self)` — Win32 message loop on a background thread; forwards hotkeys into Tk’s main loop.
* `_on_hotkey(self, hk_id)` — Maps hotkey to activity and starts it.

---

### Cleanup

* `_on_close(self)` — Posts `WM_QUIT` to the hotkey thread, **forces a final autosave**, **finalizes the session**, closes DB, and destroys Tk.

---

## Control Flow Summary

**On launch**

1. Init DB → seed activities → build UI → create overlay → start hotkey thread.
2. Select first non-custom activity and **start** it (create live session row).
3. Start: 10 ms clock loop + **1-minute autosave** loop.

**While running (every minute)**

* Add elapsed seconds to `daily_totals` (today).
* Update the live session row’s `end_ts`/`duration_sec`.
* If date flips → **rollover** at midnight and continue.

**On radio change / hotkey**

* Stop & finalize old session row → start new session row.
* Apply Waste overlay rules if applicable.

**On Stop / Exit**

* Final autosave → finalize session row → close DB.

---

## Extending the App

* **Per-activity preferred sizes** (remember last overlay size per activity) via a small `settings` table.
* **Daily view in Settings**: add a date picker with per-day totals (icons + chart).
* **CSV export** for sessions and/or daily totals.
* **Idle detection** to auto-pause or mark time as Waste after inactivity.

---

## Known Limitations

* **Windows-only** global hotkeys (uses Win32).
* `-transparentcolor` depends on your Tk build (fallback to `-alpha` used when unavailable).
* Emoji rendering relies on system fonts (Windows: **Segoe UI Emoji**). Fallback labels are provided.

---
