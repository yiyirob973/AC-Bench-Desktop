# AC Bench Desktop

The desktop benchmarking app for rating Assetto Corsa car mods under a fixed, repeatable baseline. Includes the Windows GUI, benchmark runner, in-game Lua logger, and local result processing.

## How it works

AC Bench benchmarks cars using a standardized, fixed baseline:

- **Fixed tracks**: only vanilla Kunos tracks (Magione, Vallelunga Club Circuit)
- **Fixed AI**: 100% AI level, 0% aggression
- **Fixed conditions**: clear weather, 22°C ambient, 28°C road temp, no wind, 12:00 time
- **Repeatable scoring**: median of 3 timed laps (lap 1 is a standing start and dropped)

This isolation lets you compare car performance directly without setup, weather, or driver variation affecting the results.

## What's included

- **GUI** (`ac_bench_gui.py`): desktop app for benchmarking and uploading
- **Benchmark runner** (`ac_lap_bench.py`, `ac_baseline.py`): generates and executes fixed-baseline races
- **Car tools** (`ac_carid.py`, `ac_car_classifier.py`, `ac_rating.py`): identifies cars by physics hash and rates them
- **Track validation** (`ac_track_check.py`): verifies vanilla tracks and environment
- **Lua logger** (`apps/lua/ac_bench/`): in-game script that logs AI lap times
- **Upload client** (`ac_cloud.py`): prepares and sends results to the server
TV Car to ensure consistency in the runs across multiple instances
- TV Car by EmilioGQ https://www.overtake.gg/downloads/tv-car.45108/

## Quick start

On Windows:

```bat
run_gui.bat
```

Or from Python:

```bash
python ac_bench_gui.py
```

## Benchmark workflow

1. Select a car and benchmark profile in the GUI
2. Run a benchmark race in Assetto Corsa (the Lua logger records lap times)
3. Review the result data locally
4. Upload to the AC Bench server for validation and shared class publication

## Server and class publication

This app uploads results to the AC Bench server, which validates submissions, reconciles data from multiple users, and publishes versioned class tables. See the [AC Bench Server](https://github.com/yiyirob973/AC-Bench-Server) repository for server setup and backend documentation.

The app downloads the published class table and applies it to your local results.

## Why Kunos-only tracks and AI?

- **Vanilla guarantees**: Kunos tracks and AI are immutable baseline references. Every user benchmarks on the same setup.
- **Repeatability**: no custom tracks, no custom AI, no variables. The same car on the same system produces consistent lap times.
- **Fairness**: all cars are rated under identical conditions, making class membership meaningful and comparable.

## Repository layout

```text
AC-Bench-Desktop/
  README.md
  run_gui.bat
  ac_bench_gui.py
  ac_baseline.py
  ac_carid.py
  ac_car_classifier.py
  ac_classify_laps.py
  ac_cloud.py
  ac_grid_builder.py
  ac_input.py
  ac_lap_bench.py
  ac_rating.py
  ac_tag_writer.py
  ac_track_check.py
  apps/lua/ac_bench/
    ac_bench.lua
    manifest.ini
```

## Summary

AC Bench Desktop is a simple, repeatable benchmarking tool for rating Assetto Corsa car mods. It uses a fixed baseline, Kunos-only tracks, and standard AI settings to produce fair, comparable car ratings that you can share with the community via the AC Bench server.


## Creating the track reference (server operator)

The server's canonical environment (digests of every benchmark track folder plus the SHA-256 of `acs.exe`) is made
from a clean install: Steam > Verify integrity of game files, no extra files in the track folders.

- GUI: tab **Vanilla check** > **Create track reference (server operator)**, or
- CLI: `python ac_track_check.py create --ac-dir "<AC>" --out track_reference.json`

The track list and profile come from the server's `/v1/conditions` (no environment needed yet). Load the file on the
server with `python server.py set-env --from track_reference.json`; players then verify against it.


## Server cars (live)

The Server cars list is read live from the server: your installed cars are hashed by their physics files (cached in
`car_hash_cache.json`, only changed cars are re-hashed) and just those hashes are sent to `POST /v1/cars/lookup`.
It refreshes when the Cars tab opens (if the data is over a minute old), at start, and with **Refresh**. The ratings
are held in memory only. **Apply server classes as tags** writes the `#Pride-<class>` tags from that live data.
Needs a server that has the lookup endpoint (this version).

### Applying tags

**Apply server classes as tags** (or `python ac_live.py tag --server URL --cars-dir "<AC>/content/cars" --apply`) does
its own lookup: it finds the cars installed on this PC, asks the server about only those cars, and writes one
`#Pride-<class>` tag into each car that has a verified class (provisional too if enabled in Settings). The bundled car
is never looked up or tagged. Nothing is downloaded in bulk and no ratings file is written; backups of `ui_car.json`
are made first. The old full-download `ac_cloud.py sync` is no longer used by the app.


## Workflow (the tabs, first step to last)

1. **Setup**: Assetto Corsa folders, **Install / update required files** (the bundled benchmark car and the Lua lap
   logger; a checklist shows what is missing and what to do next), server address, name, invite code, Register.
2. **Vanilla check**: verify the benchmark tracks and `acs.exe` against the server's environment.
3. **Benchmark**: the server's conditions (read-only), choose cars, start, then **Upload my results**.
4. **Cars & ratings**: your local ratings and the live server classes; **Apply server classes as tags**;
   **Benchmark cars missing from server** (installed cars the server has no class for yet).

The app opens on step 2 when setup is complete, otherwise on step 1.


## Class labels

Classes are named `1A` (top class), `1B` ... `1Z`, then `2A` ... `2Z`, `3A` ... Two-letter codes such as `AA` are no
longer used: searching for class "A" matched cars in other classes. Tags are `#Pride-1A`, `#Pride-1B`, ... and applying
tags replaces any older `#Pride-` tag (for example `#Pride-A`). The server renames the classes of already published
tables the same way, so no migration is needed.


## Who decides the class

The desktop app only measures lap times. It never works out a class itself: **Local cars** shows the times measured on
this PC. After **Upload my results** the server recomputes the scores, classifies the cars and answers with the class of
every car just uploaded (printed in the log, then shown live in **Server cars**). Apply server classes as tags to write
them into your cars.

## Single portable exe

`build_exe.bat` (or `pyinstaller --noconfirm AC-Bench.spec`) builds `dist\AC-Bench.exe` with PyInstaller. It needs
`template_race.ini` in the folder and embeds it together with `bundled_car/` and `apps/lua/ac_bench/`.

- **Embedded, read-only:** the race template, the benchmark car and the Lua logger are read from inside the exe. The
  Setup tab's *Install / update required files* and the automatic install before each benchmark copy them from there
  into Assetto Corsa. The user never provides any of them.
- **Written next to the exe (portable):** settings, `lap_results.json`, `cloud_config.json`, the caches and logs. Copy
  the folder and everything moves with it. If that folder is not writable (for example Program Files) the app uses
  `%LOCALAPPDATA%\AC-Bench` instead. Nothing is ever written to the temporary unpack folder, which is
  deleted when the app closes.
- **Jobs:** there are no separate script files in the exe, so the app starts itself with `--ac-run <module>` to run
  the benchmark, upload, vanilla check and tagging as child processes (same window, output shown in the log).
- **Source form** still works unchanged (`run_gui.bat` / `python ac_bench_gui.py`); `ac_paths.py` is the one place that
  decides where files live.
