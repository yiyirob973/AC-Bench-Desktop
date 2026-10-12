# AC Bench Desktop

This repository contains the desktop benchmarking tooling for AC Bench.

It includes:
- the Windows GUI and benchmark runner
- the fixed-baseline race logic
- lap processing and classification tools
- grid generation and tag writing
- the in-game CSP Lua logger

## Included components

- `ac_bench_gui.py` and `ac_*.py` — desktop benchmarking workflow
- `run_gui.bat` — Windows launcher
- `apps/lua/ac_bench/` — in-game logger for Assetto Corsa + CSP

## Quick start

On Windows:

```bat
run_gui.bat
```

Or from Python:

```bash
python ac_bench_gui.py
```

## Notes

This repo is intentionally separated from the cloud server repo and contains the desktop-side tools used to benchmark cars and prepare uploads.
