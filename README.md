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
