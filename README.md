<p align="center">
  <img src="branding/ac-bench.png" alt="AC Bench logo" width="140">
</p>

<h1 align="center">AC Bench Desktop</h1>

<p align="center">
  Benchmark your Assetto Corsa cars and see how they stack up against everyone else's.
</p>

---

AC Bench measures how fast AI drivers lap each of your installed cars under fixed conditions, uploads the times to an
[AC Bench server](https://github.com/yiyirob973/AC-Bench-Server) and gets back a performance class for every car. You can
write those classes into your car list as tags, so you can build balanced grids from a big collection of mods.

This is the Windows desktop app: the GUI, the benchmark runner, and a small in-game app for Assetto Corsa.

## Public server

The public server is **https://bench.cauch.uk**. Enter it as the server address on the Setup tab. Anyone can run their
own server instead, see [Running a server](#running-a-server).

## How it works

Every car is benchmarked under the same conditions, and the server decides what they are: the tracks, the number of
laps, the AI settings, the weather and the rest. The app fetches them from the server and none of it can be changed
here. A car's score on a track comes from the median of its timed laps, and the first lap is dropped because it's a
standing start.

Because everything is fixed by the server, times from different cars and different PCs can be compared directly. The
desktop app only measures lap times. The server recomputes the scores from everyone's uploads and decides each car's class.

## Requirements

- Windows and Assetto Corsa (Steam) with [Custom Shaders Patch](https://acstuff.club/patch/) installed
- A server address and an invite code to register with it
- Python 3, only if you run the app from source

## Getting started

Download `AC-Bench.exe` from the [Releases page](../../releases) and run it. Nothing needs installing. To run from
source instead, start `run_gui.bat`, or run `python ac_bench_gui.py`. The app only uses Python's standard library.

Then go through the tabs in order: set up the folders and register, run the vanilla check, run a benchmark, and look at
the results.

## The tabs

The bar along the bottom is always there: **Stop**, a progress bar, the current state, the server's conditions and
**Show log**.

### 1. Setup

<p align="center">
  <img src="docs/screenshots/setup.png" alt="The Setup tab" width="760">
</p>

- **Assetto Corsa folders:** the game folder and your Documents/Assetto Corsa folder.
- **Required files:** the benchmark car and the in-game app. *Install / update required files* copies both into
  Assetto Corsa. This also happens automatically before every benchmark.
- **Server:** the server address, your name and an invite code, then **Register**. You can also
  [use the same account on another device](#same-account-on-another-device).
- **In-game app options:** whether it may [update car class tags by itself](#tags-from-inside-the-game).

### 2. Vanilla check

<p align="center">
  <img src="docs/screenshots/vanilla-check.png" alt="The Vanilla check tab" width="760">
</p>

Compares the benchmark tracks and `acs.exe` with the server's environment. Benchmarks run this check first and stop if
anything differs, so everyone's times come from the same unmodified tracks. The server only keeps fingerprints, so it
can't tell you which file is different. If the check fails, verify the game files in Steam and remove any extra files
from the track folders.

### 3. Benchmark

<p align="center">
  <img src="docs/screenshots/benchmark.png" alt="The Benchmark tab" width="760">
</p>

- **Conditions:** what the server has set. They're read-only here.
- **Which cars:** filters for what to run, and what to do with cars that already have results.
- **Run options:** *Cars per pack*. A pack runs on every track before the next pack starts. One car per pack is the
  cleanest because the cars don't share the track. Bigger packs are faster. The server sets the upper limit.
- **Buttons:** start a benchmark, do a dry run that only counts the jobs, or probe specific cars.
- **Uploading:** times go to the server as each pack finishes, if you're registered. See
  [Uploading results](#uploading-results).

### 4. Cars & ratings

<p align="center">
  <img src="docs/screenshots/cars-and-ratings.png" alt="The Cars & ratings tab" width="760">
</p>

Two lists. **Local cars** shows the lap times measured on this PC, with a status per car. **Server cars** shows the
classes the server has given your installed cars. From here you can rerun selected cars (see
[Rebenchmarking](#rebenchmarking)), apply the server's classes as tags and benchmark installed cars the server doesn't
have a class for yet.

## Car classes and tags

Classes are `1A` (top class), `1B` ... `1Z`, then `2A` ... `2Z`, `3A` and so on. Tags look like `#Pride-1A`, so you can
search for a class in Content Manager. Applying tags replaces an older `#Pride-` tag on a car and leaves your other tags
alone. Each car's `ui_car.json` is backed up before it's changed.

### Applying tags

**Apply server classes as tags** on the Cars & ratings tab finds the cars installed on this PC, asks the server about
only those and writes a tag into each car that has a verified class. Provisional classes are included if you enable that
in Settings. The bundled car is skipped.

### Tags from inside the game

The in-game app can do the same thing on its own, so your tags stay current without opening the desktop app. It's off
by default. Turn it on with the option on the Setup tab.

- It only runs in offline races, never in online races or benchmark races. It starts as soon as a race has loaded, asks
  the server about your installed cars and writes the tags. A class that changed on the server is picked up the next
  time you start a race. **Check now** in the in-game window runs it again without leaving the race.
- The desktop app doesn't need to be running. It's designed to stay out of the way of your frame rate, and cars with very
  large physics files are left for the desktop app's **Apply server classes as tags**. The in-game window shows how
  many were skipped.
- It needs a Custom Shaders Patch version that provides `ac.checksumSHA256`. If it's missing, the in-game window says so.
- If you see stutter while it runs, the Custom Shaders Patch log (`Documents/Assetto Corsa/logs/custom_shaders_patch.log`)
  has lines containing `class_sync: profile` that show where the time went. Include them in a bug report.

## The in-game app

The in-game app shows up in Assetto Corsa's app bar as **AC Bench**. During a benchmark race it logs the AI lap times
for the desktop app. The rest of the time it does nothing, apart from the class tags above if you turned them on.

<p align="center">
  <img src="docs/screenshots/in-game-idle.png" alt="The in-game window while checking cars" width="380">
  &nbsp;
  <img src="docs/screenshots/in-game-tags.png" alt="The in-game window while writing tags" width="380">
</p>

## Starting races

Every race is started with Assetto Corsa's own **Start race** hotkey (the one in Content Manager > Settings > Assetto
Corsa > Controls > System > Race). A key you've already set is always used and never changed. If none is set, the app
sets one. It never clicks anything. The Setup tab has buttons to check and test the hotkey. Custom Shaders Patch handles
the hotkey in the game, so Content Manager doesn't need to be running.

## Uploading results

By default a pack's times are uploaded as soon as its cars have run on every track. The server recomputes the scores and
replies with each car's class, which is printed in the log and shows up in **Server cars**. If an upload fails (offline,
rate limit, not registered) the benchmark carries on and the times stay saved. The backup upload button on the Benchmark
tab sends everything that hasn't been uploaded yet. Uploaded results are remembered, so nothing gets sent twice.

## Rebenchmarking

**Benchmark selected cars** redoes the cars you picked, but only on the tracks where they have no valid time yet. **Redo
all tracks for selected** does every track.

## Same account on another device

On the device that's already registered, create a link code on the Setup tab. On the new device, choose the option to
use the same account, enter the code and sign in. The code works once and expires after a few minutes. Each device gets
its own key for the same account.

## Running a server

Results go to an [AC Bench Server](https://github.com/yiyirob973/AC-Bench-Server), which validates them, combines data
from several users and publishes versioned class tables. That repository has the setup instructions, including how to
create and load the track reference that the vanilla check compares against. The Vanilla check tab has a button to create
the reference from a clean install.

## Building the exe

`.github/workflows/build.yml` builds `AC-Bench.exe` with [Nuitka](https://nuitka.net/), which compiles the code to a
native program. The exe contains everything the app installs into Assetto Corsa. Settings, results and logs are written
next to the exe, or to `%LOCALAPPDATA%\AC-Bench` if that folder isn't writable.

**Antivirus warnings:** a new, unsigned program that few people have downloaded has no reputation yet, so some antivirus
products flag it. Building with Nuitka cuts the chance a lot but can't remove it. If you'd rather not run the exe, run
the app from source.

## Repository layout

```text
AC-Bench-Desktop/
  README.md
  run_gui.bat                  start the GUI from source on Windows
  ac_bench_gui.py              the GUI
  ac_lap_bench.py              builds and runs the benchmark races
  ac_baseline.py               the fixed baseline
  ac_conditions.py             benchmark conditions from the server
  ac_carid.py                  identifies cars by physics hash
  ac_car_classifier.py         reads car data
  ac_rating.py                 scores results
  ac_track_check.py            vanilla check of the tracks and acs.exe
  ac_cloud.py                  server API: register, upload, link devices
  ac_live.py                   live car lookups and tag writing
  ac_tag_writer.py             writes the class tags
  ac_input.py, ac_controls.py  the race start hotkey
  ac_paths.py                  where files live
  ac_theme.py                  window icon and logo
  branding/
    ac-bench.ico               exe and window icon
    ac-bench.png               logo
    header.png                 small logo for the window header
  docs/screenshots/            the screenshots in this README
  bundled_car/                 the TV car every race drives
  apps/lua/ac_bench/           the in-game app
    ac_bench.lua               lap logger
    class_sync.lua             in-game class tagging
    manifest.ini
    icon.png                   app bar icon
```

## Credits

The bundled TV car is by EmilioGQ: <https://www.overtake.gg/downloads/tv-car.45108/>. Every run drives it so results stay
consistent between installs. It's never benchmarked itself and is never listed or tagged.
