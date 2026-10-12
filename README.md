# AC Bench Desktop

This repository contains the desktop-side benchmarking tools for AC Bench. It includes the Windows GUI, the fixed-baseline benchmark runner, the lap-processing and classification scripts, and the in-game Lua logger used to collect timing data from Assetto Corsa.

The desktop app is the measurement side of the system. The AC Bench cloud server is the trust and publishing side: it validates uploads, reconciles submissions from multiple users, and publishes the class tables clients download.

## What this repo includes

- `ac_bench_gui.py` and the `ac_*.py` benchmark helpers
- `run_gui.bat` — Windows launcher
- `apps/lua/ac_bench/` — in-game CSP Lua logger for Assetto Corsa
- fixed benchmark logic for repeatable baseline testing
- local result processing, car classification, and upload preparation

## Separation of responsibilities

### Desktop app responsibilities

The desktop app is responsible for:

- benchmarking cars under a fixed, repeatable baseline
- verifying the vanilla environment and track setup
- collecting lap data from Assetto Corsa
- processing and validating benchmark results locally
- preparing upload payloads for the AC Bench server
- downloading and applying the published class table

### Server responsibilities

The cloud server is responsible for:

- validating API keys and invite-only access
- verifying environment attestation and profile rules
- recomputing score values on the server instead of trusting the client
- merging submissions from multiple users into one agreed result per car and track
- publishing versioned class tables for clients to download

This split keeps the desktop app focused on measurement, while the server focuses on trust, consistency, and shared ranking data.

## In-game logger

The Lua logger is bundled in this repo under:

```text
apps/lua/ac_bench/
```

It logs AI lap timings and writes the data needed by the desktop Python workflow. It is not a standalone project; it is part of the desktop benchmark stack.

## Benchmark workflow

A normal benchmark flow looks like this:

1. The desktop app opens the fixed benchmark profile.
2. The Lua logger records lap data while Assetto Corsa runs the benchmark.
3. The desktop Python tools process the result file and prepare validation data.
4. The result is uploaded to the AC Bench server.
5. The server checks the environment and recomputes scores.
6. Once enough independent submissions exist, the server publishes a class table.
7. The desktop app downloads the latest class table and updates local class display.

## Quick start

On Windows:

```bat
run_gui.bat
```

Or directly:

```bash
python ac_bench_gui.py
```

## Repository layout

```text
AC-Bench-Desktop/
  README.md
  ac_baseline.py
  ac_bench_gui.py
  ac_car_classifier.py
  ac_carid.py
  ac_classify_laps.py
  ac_cloud.py
  ac_grid_builder.py
  ac_input.py
  ac_lap_bench.py
  ac_rating.py
  ac_tag_writer.py
  ac_track_check.py
  apps/
    lua/
      ac_bench/
        ac_bench.lua
        manifest.ini
  run_gui.bat
```

## Relationship to the cloud server

This repo does not implement the shared rating database or server-side validation logic. Those live in the separate AC Bench server repository.

The desktop app measures and prepares data. The server validates, agrees, and publishes.

## Security and limits

- The benchmark baseline is intentionally fixed in code to reduce measurement drift.
- Track and environment checks are required before uploads.
- Shared class tables and official rating data are server-side responsibilities.
- Results are only trustworthy when the benchmark environment matches the accepted reference and the server validates the submission.

## Summary

AC Bench Desktop is the client-side measurement toolchain for the AC Bench ecosystem. It includes the GUI, benchmark runner, and Lua logger, and it works together with the separate server project to produce a trusted, shared car rating system.
