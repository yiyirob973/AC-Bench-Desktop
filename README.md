# AC Bench Desktop

The desktop app for benchmarking Assetto Corsa car mods against a fixed baseline. It has a Windows GUI, the benchmark
runner, an in-game Lua logger and the local result handling.

## How it works

Every car is benchmarked the same way:

- Tracks: only vanilla Kunos tracks (Magione and Vallelunga Club Circuit)
- AI: 100% level, 0% aggression
- Conditions: clear weather, 22°C air, 28°C road, no wind, 12:00
- Score: median of 3 timed laps (lap 1 is a standing start and is dropped)

Because all of that is fixed, lap times from different cars and different PCs can be compared directly.

## What's in here

- `ac_bench_gui.py`: the GUI, for benchmarking, uploading and tagging
- `ac_lap_bench.py`, `ac_baseline.py`: build and run the fixed-baseline races
- `ac_carid.py`, `ac_car_classifier.py`, `ac_rating.py`: identify cars by physics hash and rate them
- `ac_track_check.py`: checks the vanilla tracks and `acs.exe`
- `ac_cloud.py`, `ac_live.py`: talk to the server (upload, live car lookups)
- `apps/lua/ac_bench/`: the in-game Lua app. It logs AI lap times during benchmark races. Otherwise it keeps the
  `#Pride-<class>` car tags up to date (`class_sync.lua`, set up by the `config.json` the app writes during
  *Install required files*).
- `bundled_car/`: the TV Car by EmilioGQ (https://www.overtake.gg/downloads/tv-car.45108/), which every run drives so
  results stay consistent between installs

## Quick start

On Windows run `run_gui.bat`, or from Python:

```bash
python ac_bench_gui.py
```

## Workflow

The tabs go in the order you use them:

1. **Setup**: Assetto Corsa folders, *Install / update required files* (the benchmark car and the Lua logger; a
   checklist shows what's missing and what to do next), server address, name, invite code, Register.
2. **Vanilla check**: compare the benchmark tracks and `acs.exe` with the server's environment.
3. **Benchmark**: the server's conditions (read-only), pick cars, start. Each pack's times are uploaded when its cars
   finish. *Upload my results* is the backup.
4. **Cars & ratings**: your local ratings and the live server classes, **Apply server classes as tags**, and
   **Benchmark cars missing from server** (installed cars the server has no class for yet).

The app opens on step 2 when setup is complete, and on step 1 otherwise.

## The server

Results go to the [AC Bench Server](https://github.com/yiyirob973/AC-Bench-Server), which validates them, combines data
from several users and publishes versioned class tables. The repository has the server setup and backend docs.

The desktop app only measures lap times. It never works out a class itself. **Local cars** shows the times measured on
this PC. After an upload (automatic after each pack, or with the backup button) the server recomputes the scores,
classifies the cars and replies with the class of every car you just uploaded. That reply is printed in the log and then
shows up in **Server cars**.

## Server cars

The Server cars list is read live. Your installed cars are hashed by their physics files (cached in
`car_hash_cache.json`, only changed cars get re-hashed) and just those hashes are sent to `POST /v1/cars/lookup`. It
refreshes when the Cars tab opens (if the data is over a minute old), at start, and with **Refresh**. The ratings are
only kept in memory. This needs a server that has the lookup endpoint.

### Applying tags

**Apply server classes as tags** (or `python ac_live.py tag --server URL --cars-dir "<AC>/content/cars" --apply`) does
its own lookup: it finds the cars installed on this PC, asks the server about only those and writes one `#Pride-<class>`
tag into each car that has a verified class (provisional ones too, if enabled in Settings). The bundled car is skipped.
Nothing is downloaded in bulk and no ratings file is written. `ui_car.json` is backed up first. The old
`ac_cloud.py sync` download isn't used by the app any more.

### Tags from inside the game

The Lua app can do the same thing on its own. A short while after a race loads it identifies your installed cars, asks
the server about just those and writes the same `#Pride-<class>` tags, using the same backup rule.

- It never runs in online races, or in benchmark races.
- In offline races it only works while your car is stopped, and pauses when you start driving.
- The first run over a big collection takes a while because every car has to be hashed. After that, only cars that
  changed are hashed again.
- There's a checkbox in Settings to turn it off. The server address and options reach the Lua app through
  `config.json`, which is written when you press *Install / update required files*. Run that again after changing the
  server address.
- It needs a CSP version that has `ac.checksumSHA256`. If it's missing, the in-game window says so.

## Class labels

Classes are `1A` (top class), `1B` ... `1Z`, then `2A` ... `2Z`, `3A` and so on. Two-letter codes like `AA` aren't used
any more because searching for class "A" matched cars in other classes. Tags look like `#Pride-1A`, `#Pride-1B`, and
applying tags replaces any older `#Pride-` tag (for example `#Pride-A`). The server renames the classes in tables it
already published, so there's nothing to migrate.

## How each race is started

Every race is started with AC's own **Start race** hotkey. There's no other way to start one (no clicking, no
calibration). It's the same command as Content Manager > Settings > Assetto Corsa > Controls > System > Race > *Start
race*, stored in `Documents\Assetto Corsa\cfg\controls.ini` as `[__CM_START_SESSION]` with `KEY=0x7B ; F12`. Content
Manager writes the key as hex plus its name, and the app reads both hex and plain numbers. The hotkey is Ctrl + that key.

- A key you already set is always used and never changed (the log mentions it if AC uses that Ctrl+key for something
  else). F12 is only written when nothing is set. Duplicate `KEY` lines get cleaned up. Only that section is touched, a
  backup is kept (`controls.ini.acbench.bak`), and a dry run never touches the file.
- Custom Shaders Patch handles the hotkey in the game when `extension\config\data_hotkeys_supported.txt` lists
  `__CM_START_SESSION`, so Content Manager doesn't need to be running. The log says which case your install is.
- Under Setup > *Starting each race*, **Set up start hotkey** prints what controls.ini contains and **Test start hotkey**
  presses it once (open AC on the pre-race screen first). *First try after launching AC* is the delay before the first
  press. After that the app presses it every few seconds until the logger reports that the race has started. Restart AC
  after the key changes.

## Uploading results

By default a pack's times are uploaded as soon as its cars have run on every track (a pack is one car when *Cars per
pack* is 1). The server recomputes the scores and replies with each car's class, which is printed in the log. If an
upload fails (offline, rate limit, not registered) the benchmark carries on and the times stay saved. **Upload my
results (backup)** on the Benchmark tab sends everything that hasn't been uploaded yet. Untick *Upload each pack's times
automatically* to upload only with the button. Uploaded results are remembered, so nothing gets sent twice.

Job processes (benchmark, upload and so on) always write UTF-8, so car names with special characters don't crash an
upload or turn into garbage in the log.

## Rebenchmarking

**Benchmark selected cars** redoes the cars you picked, but only on the tracks where they have no valid time yet. A car
that has a time on one track and a failure on the other only reruns the failed one. **Redo all tracks for selected**
does every track. On the command line that's `--probe` (add `--all-tracks` for everything). The *Rerun* options still
redo every track of the cars they apply to.

## Same account on another device

On the device that's already registered: Setup > **Create link code for another device** (or `python ac_cloud.py link`).
On the new device: Setup > **Use the same account on another device**, enter the code and press **Sign in** (or
`python ac_cloud.py login --code=XXXX-XXXX-XXXX`). The code works once and for 10 minutes. Each device gets its own key
for the same account, saved in its own `cloud_config.json`.

## Creating the track reference (server operator)

The server's reference environment is a digest of every benchmark track folder plus the SHA-256 of `acs.exe`. Make it
from a clean install: Steam > Verify integrity of game files, with no extra files in the track folders.

- GUI: **Vanilla check** tab > **Create track reference (server operator)**, or
- CLI: `python ac_track_check.py create --ac-dir "<AC>" --out track_reference.json`

The track list and profile come from the server's `/v1/conditions`, so no environment is needed yet. Load the file on the
server with `python server.py set-env --from track_reference.json`. Players then verify against it.

## Single portable exe

`build_exe.bat` (or `pyinstaller --noconfirm AC-Bench.spec`) builds `dist\AC-Bench.exe` with PyInstaller. It needs
`template_race.ini` in the folder and embeds it together with `bundled_car/` and `apps/lua/ac_bench/`.

- **Embedded, read-only:** the race template, the benchmark car and the Lua logger are read from inside the exe. *Install
  / update required files* on the Setup tab, and the automatic install before each benchmark, copy them from there into
  Assetto Corsa. Nobody has to supply them.
- **Written next to the exe:** settings, `lap_results.json`, `cloud_config.json`, caches and logs. Copy the folder and
  everything comes along. If that folder isn't writable (Program Files, say) the app uses `%LOCALAPPDATA%\AC-Bench`
  instead. Nothing is written to the temporary unpack folder, which is deleted when the app closes.
- **Jobs:** the exe has no separate script files, so the app starts itself with `--ac-run <module>` to run the
  benchmark, upload, vanilla check and tagging as child processes (same window, output in the log).
- **From source** everything works the same (`run_gui.bat` or `python ac_bench_gui.py`). `ac_paths.py` is the one place
  that decides where files live.

## Building without antivirus false positives

PyInstaller output gets flagged by a lot of antivirus products, since every PyInstaller program carries the same
well-known bootloader. So the GitHub workflow `.github/workflows/build.yml` uses **Nuitka**, which compiles the code to C
and produces a native program:

- By default it builds one file, `AC-Bench.exe`. Every push to `dev` publishes it to the rolling `dev-latest` GitHub
  Release (direct download, with a `.sha256`). The Actions artifact holds the same file, wrapped in a zip because GitHub
  always does that.
- **Portable:** nothing is installed and nothing is left behind. While it runs, the exe unpacks itself into a temporary
  folder and deletes it when it closes. Settings, results and caches go next to the exe, so you can move or copy it
  anywhere, a USB stick for example. Only if the exe's folder is read-only does the app use `%LOCALAPPDATA%\AC-Bench`.
  A single-file Python program can't avoid unpacking itself while it runs, that's what makes it one file.
- Start the workflow by hand with **folder** ticked to get a folder build instead (for debugging).
- The old PyInstaller build is still there as `build-pyinstaller.yml` (manual start only).
- Every build checks the finished program (`--ac-selfcheck`: embedded template, car and Lua logger present, all modules
  importable) and starts a job through `--ac-run` before the artifact is uploaded.

Nuitka cuts the chance of a false positive a lot but can't remove it. A new, unsigned program that few people have
downloaded has no reputation yet. Signing it with a code-signing certificate is what fixes that for good.

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
  ac_live.py
  ac_grid_builder.py
  ac_input.py
  ac_lap_bench.py
  ac_rating.py
  ac_tag_writer.py
  ac_track_check.py
  apps/lua/ac_bench/
    ac_bench.lua
    class_sync.lua
    manifest.ini
```
