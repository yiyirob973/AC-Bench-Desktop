#!/usr/bin/env python3
"""
Automated lap benchmark for Assetto Corsa (Windows, Steam running, CSP installed).

Runs short AI races: several test cars per launch (a "batch"), the in-game
logger app writes their lap times to result.json, this script reads them, kills
AC and starts the next batch. Results are saved after every batch.

BASELINE: tracks, laps, AI level/aggression and all race conditions (weather, temperature, grip,
wind, time) are pinned in ac_baseline.py and written into every race, whatever the template says.
A car's score is the MEDIAN of its timed laps (lap 1 dropped); best_ms is only the fastest timed lap.
Results are tagged with the baseline profile and the batch size. --batch 1 (default) means no
other car shares the track: the cleanest baseline.

Cars that already have a valid result for a track are SKIPPED. Use --rerun to
force: bare `--rerun` redoes every selected car, `--rerun car_a car_b` only those.

SETUP (once)
 1. Copy apps/lua/ac_bench into <AC>/apps/lua/ (so it has ac_bench.lua + manifest.ini).
 2. In Content Manager set up a Quick Drive RACE: any player car, exactly 1 AI
    opponent, then press Drive once (conditions are pinned by the tool). Copy
    Documents/Assetto Corsa/cfg/race.ini to template_race.ini.
 3. Probe (all tracks):  python ac_lap_bench.py --template template_race.ini --probe ks_mazda_mx5_cup ks_abarth_500_assetto_corsa
 4. Full:   python ac_lap_bench.py --template template_race.ini --batch 10 --group-by car_classes.csv

Order: cars are grouped into PACKS of --batch cars; a pack runs on EVERY track before the next pack
starts, so cars get fully rated pack by pack.
Speed: --batch N puts N test cars in one race (capped by the track's pit boxes).
Cars in a batch can bump into each other, so --group-by sorts them so similar-pace
cars share a batch (use the estimate CSV from ac_car_classifier.py; for later
tracks, times already measured on earlier tracks are used instead).

Then: python ac_classify_laps.py lap_results.json CARS_DIR
"""
import argparse, configparser, csv, json, os, re, shutil, statistics, subprocess, sys, time
from pathlib import Path

DEFAULT_AC = r"C:\Program Files (x86)\Steam\steamapps\common\assettocorsa"
import ac_baseline as bl      # tracks, laps, AI settings and race conditions are pinned there
import ac_rating as rating    # lap scoring: lap 1 dropped, median of the timed laps
import ac_paths               # where user data lives (beside the exe) vs files shipped inside it
import ac_carid               # car identity (hash of the physics files), used by the cloud upload


# ---------- files ----------
def read_ini(path):
    cp = configparser.ConfigParser(strict=False, interpolation=None, delimiters=("=",))
    cp.optionxform = str
    with open(path, encoding="utf-8", errors="ignore") as f:
        cp.read_file(f)
    return cp


def write_ini(cp, path):
    with open(path, "w", encoding="utf-8") as f:
        cp.write(f, space_around_delimiters=False)


def load_results(p):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_results(p, data):
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(p)


# ---------- tracks / cars ----------
def check_tracks(ac, specs):
    for spec in specs:
        track, _, layout = spec.partition("/")
        tdir = ac / "content" / "tracks" / track
        if not tdir.is_dir():
            sys.exit(f"Track '{track}' not found in {tdir.parent}")
        if layout and not (tdir / "ui" / layout).is_dir():
            have = [d.name for d in (tdir / "ui").iterdir() if d.is_dir()]
            sys.exit(f"Layout '{layout}' not found for {track}. Available: {have}")


def pitboxes(ac, spec):
    track, _, layout = spec.partition("/")
    base = ac / "content" / "tracks" / track / "ui"
    for p in ([base / layout / "ui_track.json"] if layout else []) + [base / "ui_track.json"]:
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig", errors="replace"), strict=False)
            m = re.search(r"\d+", str(d.get("pitboxes", "")))
            if m:
                return int(m.group())
        except Exception:
            pass
    return None


def first_skin(car_dir):
    skins = car_dir / "skins"
    names = sorted(d.name for d in skins.iterdir() if d.is_dir()) if skins.is_dir() else []
    return names[0] if names else None


# ---------- race.ini ----------
def apply_batch(cp, base_car, batch, spec, laps):
    track, _, layout = spec.partition("/")
    cp["RACE"]["TRACK"] = track
    cp["RACE"]["CONFIG_TRACK"] = layout
    cp["RACE"]["RACE_LAPS"] = str(laps)
    cp["RACE"]["CARS"] = str(len(batch) + 1)
    for s in list(cp.sections()):
        if re.fullmatch(r"CAR_\d+", s) and s != "CAR_0":
            cp.remove_section(s)
    for i, (car, skin) in enumerate(batch, 1):
        sec = f"CAR_{i}"
        cp.add_section(sec)
        cp[sec].update(base_car)
        cp[sec].update(bl.AI_CAR)
        cp[sec].update({"MODEL": car, "SKIN": skin,
                        "DRIVER_NAME": f"ACBENCH {i}"})   # marker: the in-game logger only acts in these races
    for s in cp.sections():
        if s.startswith("SESSION_") and cp.get(s, "TYPE", fallback="") == "3":
            cp[s]["LAPS"] = str(laps)
    cp["RACE"]["AI_LEVEL"] = bl.AI_LEVEL
    for sec, kv in bl.CONDITIONS.items():           # pinned conditions, whatever the template says
        if sec not in cp:
            cp.add_section(sec)
        cp[sec].update(kv)
    if "ASSISTS" in cp:
        cp["ASSISTS"].update(bl.ASSISTS)


def kill_ac(proc):
    try:
        proc.kill()
    except Exception:
        pass
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/IM", "acs.exe", "/T"], capture_output=True)
    time.sleep(3)


# ---------- running ----------
def _identity(args, ac, car, entry):
    """Tie a result to the exact car files and the verified environment it was driven in."""
    try:
        entry["car_hash"] = ac_carid.car_hash(ac / "content" / "cars" / car)
    except Exception:
        entry["car_hash"] = None
    if getattr(args, "env_id", None):
        entry["env"] = args.env_id


def run_batch(args, ac, race_ini, result_file, cp, base_car, batch, spec):
    apply_batch(cp, base_car, batch, spec, bl.RACE_LENGTH_LAPS)   # race never ends by itself, see ac_baseline.py
    write_ini(cp, race_ini)
    try:      # copy next to the results so you can see exactly what was run
        shutil.copy2(race_ini, Path(getattr(args, "results", "lap_results.json")).with_name("last_race.ini"))
    except Exception:
        pass
    if result_file.exists():
        result_file.unlink()

    expected = {i: car for i, (car, _) in enumerate(batch, 1)}
    proc = subprocess.Popen([str(ac / "acs.exe")], cwd=str(ac))
    start = time.time()
    deadline = start + args.timeout + 30 * len(batch)
    last_change, seen, laps, reason = start, 0, {}, "timeout"
    started, attempts, last_try, warned = False, 0, 0.0, False
    race_t0 = None                       # when the race actually got going
    still, out_set = set(), set()        # cars standing still / retired or vanished, as reported by the logger
    lap_n, lap_t = {}, {}                # laps logged per car and when that count last changed
    still_since, out_since = {}, {}
    gave_up = {}                         # car index -> why we stopped waiting for it (retired, stuck, ...)
    stuck_s = getattr(args, "stuck", 30)
    first_lap = getattr(args, "first_lap", 240)
    lap_min = getattr(args, "lap_wait_min", 60)
    lap_factor = getattr(args, "lap_wait_factor", 2.5)
    try:
        while time.time() < deadline:
            time.sleep(2)
            now = time.time()
            if args.stop_file and Path(args.stop_file).exists():
                reason = "stopped"
                break
            if result_file.exists():
                try:
                    d = json.loads(result_file.read_text(encoding="utf-8"))
                except Exception:
                    d = None                      # file mid-write
                if d:
                    cur = {e["idx"]: e.get("laps_ms", []) for e in d.get("cars", [])
                           if expected.get(e.get("idx")) == e.get("car")}
                    total = sum(len(v) for v in cur.values())
                    if total != seen:
                        seen, last_change = total, now
                    laps = cur
                    still = set(d.get("still", []))
                    out_set = set(d.get("out", []))
                    started = started or bool(d.get("started")) or total > 0
                    if started and race_t0 is None:
                        race_t0 = now
                    for i in expected:
                        n_i = len(laps.get(i, []))
                        if n_i != lap_n.get(i, 0):
                            lap_n[i], lap_t[i] = n_i, now
                    if all(len(laps.get(i, [])) >= args.laps for i in expected):
                        reason = ""
                        break
            if not warned and not result_file.exists() and now - start > 120:
                warned = True
                print("    note: the in-game logger has not reported yet. Open the \"AC Bench\" app in the "
                      "apps sidebar and check its status, or see custom_shaders_patch.log for lines with ac_bench. If AC is "
                      "sitting on the pre-race screen, change how races are started (Setup tab).", flush=True)
            if args.auto and not started and attempts < args.click_max:
                if now - start > args.click_delay and now - last_try > args.click_interval:
                    last_try, attempts = now, attempts + 1
                    try:
                        found = args.auto[0](args.auto[1], args.auto[2], args.auto[3])
                    except Exception as e:
                        found = False
                        print(f"    auto-start error: {e}", flush=True)
                    if attempts == 1:
                        print("    auto-start: " + ("sent" if found else "AC window not found yet"), flush=True)

            # Retired / stuck / vanished cars: stop waiting for them so the run moves on.
            if started and race_t0 is not None:
                known = [laps[i][-1] / 1000 for i in laps if len(laps[i]) >= 2]
                ref_s = statistics.median(known) if known else None
                for i in expected:
                    n_i = len(laps.get(i, []))
                    if n_i >= args.laps or i in gave_up:
                        continue
                    (still_since.setdefault(i, now) if i in still else still_since.pop(i, None))
                    (out_since.setdefault(i, now) if i in out_set else out_since.pop(i, None))
                    since_lap = now - lap_t.get(i, race_t0)
                    if n_i:
                        limit = max(lap_min, lap_factor * laps[i][-1] / 1000)
                    else:
                        limit = min(first_lap, max(90.0, 3 * ref_s)) if ref_s else first_lap
                    why = None
                    if i in out_since and now - out_since[i] >= 5:
                        why = "retired"
                    elif i in still_since and now - still_since[i] > stuck_s:
                        why = "stuck"
                    elif since_lap > limit:
                        why = f"no lap for {since_lap:.0f}s"
                    if why:
                        gave_up[i] = why
                        print(f"    {expected[i]}: giving up ({why})", flush=True)
                waiting = [i for i in expected if len(laps.get(i, [])) < args.laps and i not in gave_up]
                if gave_up and not waiting:
                    reason = "retired"
                    break
            if seen and now - last_change > args.stall:
                reason = "stalled"
                break
            if proc.poll() is not None:
                reason = "AC exited early"
                break
    finally:
        kill_ac(proc)
    if reason == "stopped":
        raise KeyboardInterrupt      # unfinished batch is not recorded

    out = {}
    for i, car in expected.items():
        l = laps.get(i, [])
        if len(l) >= args.laps:
            l = l[:args.laps]            # score exactly the same laps for every car, whatever the leaders did after
            flying = l[1:] if len(l) > 1 else l          # drop standing-start lap
            score, n_timed = rating.lap_score({"laps_ms": l, "best_ms": min(flying)})
            out[car] = {"status": "ok", "best_ms": min(flying), "score_ms": score, "timed_laps": n_timed,
                        "laps_ms": l, "profile": bl.PROFILE_ID, "batch": len(batch)}
            _identity(args, ac, car, out[car])
        else:
            why = gave_up.get(i) or reason or "incomplete"
            out[car] = {"status": "failed", "reason": f"{why} ({len(l)}/{args.laps} laps)",
                        "laps_ms": l, "profile": bl.PROFILE_ID, "batch": len(batch)}
    return out


def main():
    ac_paths.utf8_output()
    ap = argparse.ArgumentParser()
    ap.add_argument("--ac-dir", default=DEFAULT_AC)
    ap.add_argument("--docs-dir", default=str(Path.home() / "Documents" / "Assetto Corsa"))
    ap.add_argument("--template", required=True, help="race.ini saved from a CM quick drive race")
    ap.add_argument("--batch", type=int, default=1, help="test cars per launch (default 1)")
    ap.add_argument("--group-by", help="car_classes.csv (id, gap_pct) used to batch similar-pace cars")
    ap.add_argument("--timeout", type=int, default=900, help="base seconds per launch; +30s per car")
    ap.add_argument("--stuck", type=int, default=30,
                    help="seconds a car may stand still before it counts as retired/stuck and is given up on (default 30)")
    ap.add_argument("--first-lap", type=int, default=240,
                    help="give up on a car that has not completed its first lap this many seconds after the start (default 240)")
    ap.add_argument("--lap-wait-min", type=int, default=60,
                    help="a car with no new lap for max(this, 2.5 x its last lap time) seconds is given up on (default 60)")
    ap.add_argument("--lap-wait-factor", type=float, default=2.5, help="see --lap-wait-min")
    ap.add_argument("--stall", type=int, default=300, help="give up on stragglers after this many seconds without a new lap")
    ap.add_argument("--results", default="lap_results.json")
    ap.add_argument("--include", help="regex on car id")
    ap.add_argument("--exclude", help="regex on car id")
    ap.add_argument("--ids-file", help="text file with one car id per line: only these cars (see the cloud tab)")
    ap.add_argument("--retry-failed", action="store_true", help="also redo cars that failed before")
    ap.add_argument("--rerun", nargs="*", default=None, metavar="CAR_ID",
                    help="redo cars that already have results: all selected cars, or only the ids given")
    ap.add_argument("--probe", nargs="+", metavar="CAR_ID", help="test run: these cars as one batch on every track (always runs, even if already rated)")
    ap.add_argument("--dry-run", action="store_true", help="only count jobs")
    ap.add_argument("--start-hotkey", action="store_true",
                    help="start races with AC's own 'Start race' hotkey (controls.ini [__CM_START_SESSION]; set up "
                         "automatically): no clicking and no calibration")
    ap.add_argument("--click-drive", action="store_true",
                    help="auto-click the Drive button at the position saved by ac_input.py calibrate")
    ap.add_argument("--click-pos", help="fx,fy (0-1 fractions of the AC window) instead of drive_click.json")
    ap.add_argument("--press-key", help="key to press to start (enter, space, esc, f1-f12, a letter)")
    ap.add_argument("--click-delay", type=int, default=25, help="seconds after launch before the first start attempt")
    ap.add_argument("--click-interval", type=int, default=6, help="seconds between start attempts")
    ap.add_argument("--click-max", type=int, default=40, help="max start attempts per launch")
    ap.add_argument("--reference", default=str(ac_paths.DATA / "track_reference.json"),
                    help="vanilla track reference made by ac_track_check.py create")
    ap.add_argument("--skip-track-check", action="store_true",
                    help="do NOT verify the tracks are vanilla (ratings may not be comparable)")
    ap.add_argument("--ignore-ui-files", action="store_true",
                    help="vanilla check: ignore files under each track's ui/ folder")
    ap.add_argument("--stop-file", help="graceful stop: if this file appears, kill AC, keep results, exit")
    args = ap.parse_args()

    if args.probe:
        args.batch = max(args.batch, len(args.probe))     # probe = one launch per track

    args.tracks, args.laps = list(bl.TRACKS), bl.LAPS        # hard-coded baseline
    ac = Path(args.ac_dir)
    if not (ac / "acs.exe").exists():
        sys.exit(f"acs.exe not found in {ac}; pass --ac-dir")
    check_tracks(ac, args.tracks)

    race_ini = Path(args.docs_dir) / "cfg" / "race.ini"
    result_file = ac / "apps" / "lua" / "ac_bench" / "result.json"
    if not result_file.parent.is_dir():
        sys.exit(f"Logger app missing: copy ac_bench to {result_file.parent}")

    args.auto = None
    if args.click_drive or args.press_key or args.start_hotkey:
        try:
            import ac_input
        except Exception as e:
            sys.exit(f"Auto-start unavailable: {e}")
        combo = None
        if args.start_hotkey:
            import ac_controls
            vk, note = ac_controls.ensure_start_hotkey(args.docs_dir)
            print("start mode: AC 'Start race' hotkey: " + note, flush=True)
            if vk is None:
                sys.exit("Cannot use the start-race hotkey: " + note)
            for line in ac_controls.describe(args.docs_dir, str(ac))[1:]:
                print("    " + line, flush=True)
            combo = [ac_input.key_code("ctrl"), vk]
        pos = None
        if args.click_drive:
            pos = (tuple(float(v) for v in args.click_pos.split(",")) if args.click_pos
                   else ac_input.load_click())
            if not pos:
                sys.exit("No Drive position saved. Run: python ac_input.py calibrate")
        args.auto = (ac_input.nudge, pos, args.press_key, combo)

    cp = read_ini(args.template)
    for sec in ("RACE", "CAR_1"):
        if sec not in cp:
            sys.exit(f"Template race.ini has no [{sec}]. Use a quick drive race with 1 AI opponent.")
    base_car = dict(cp["CAR_1"])

    cars = sorted(d for d in (ac / "content" / "cars").iterdir() if d.is_dir())
    if args.probe:
        cars = [c for c in cars if c.name in args.probe]
        missing = set(args.probe) - {c.name for c in cars}
        if missing:
            sys.exit(f"Car(s) not found: {sorted(missing)}")
    if args.ids_file:
        wanted = {ln.strip() for ln in Path(args.ids_file).read_text(encoding="utf-8").splitlines() if ln.strip()}
        cars = [c for c in cars if c.name in wanted]
    if args.include:
        cars = [c for c in cars if re.search(args.include, c.name)]
    if args.exclude:
        cars = [c for c in cars if not re.search(args.exclude, c.name)]

    specs = args.tracks
    res_path = Path(args.results)
    results = load_results(res_path)

    # a car without a skins folder cannot be put on the grid (unowned DLC car or incomplete install): say so loudly
    no_skin = [c for c in cars if not first_skin(c)]
    if no_skin:
        print(f"{len(no_skin)} selected car(s) cannot be raced: no skins folder in content\\cars\\<car>\\skins "
              "(an unowned DLC car or an incomplete install): "
              + ", ".join(c.name for c in no_skin[:12]) + (" ..." if len(no_skin) > 12 else ""), flush=True)
        cars = [c for c in cars if c not in no_skin]
        if not args.dry_run:
            for c in no_skin:
                for spec in specs:
                    results.setdefault(c.name, {})[spec] = {"status": "failed", "reason": "no skins"}
            save_results(res_path, results)
        if not cars:
            sys.exit("Nothing to benchmark: none of the selected cars can be raced (see above).")

    est = {}
    if args.group_by:
        with open(args.group_by, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    est[r["id"]] = float(r["gap_pct"])
                except (KeyError, ValueError):
                    pass

    rerun_all = args.rerun is not None and len(args.rerun) == 0
    rerun_ids = set(args.rerun or [])

    best_ms = {}
    for per in results.values():
        for t, r in per.items():
            if r.get("status") == "ok" and (t not in best_ms or r["best_ms"] < best_ms[t]):
                best_ms[t] = r["best_ms"]

    def pace(car):
        """Sort key so similar-pace cars share a pack: measured gap if known, else the estimate."""
        gaps = [(r["best_ms"] / best_ms[t] - 1) * 100 for t, r in results.get(car, {}).items()
                if r.get("status") == "ok" and t in best_ms]
        return sum(gaps) / len(gaps) if gaps else est.get(car, 0.0)

    # Which (car, track) jobs are still to do
    todo, done_skip, fail_skip = {}, 0, 0
    for c in cars:
        for spec in specs:
            prev = results.get(c.name, {}).get(spec, {})
            forced = rerun_all or c.name in rerun_ids or bool(args.probe)   # a probe always runs
            if prev.get("status") == "ok" and not forced:
                done_skip += 1
            elif prev.get("status") == "failed" and not (forced or args.retry_failed):
                fail_skip += 1
            else:
                todo.setdefault(c.name, []).append(spec)

    # One pack = the cars launched together. Its size must fit on every track.
    size = max(args.batch, 1)
    for spec in specs:
        pb = pitboxes(ac, spec)
        if pb and size > pb - 1:
            print(f"{spec}: only {pb} pit boxes, packs capped at {pb - 1} cars")
            size = pb - 1
    size = max(size, 1)

    # PACK-MAJOR order: a pack runs on EVERY track before the next pack starts, so cars are
    # finished (rated on both tracks) pack by pack instead of track by track.
    by_name = {c.name: c for c in cars}
    names = sorted(todo, key=lambda n: (pace(n), n))
    packs = [names[i:i + size] for i in range(0, len(names), size)]
    plan = []
    for pk, pack in enumerate(packs, 1):
        for spec in specs:
            group = [by_name[n] for n in pack if spec in todo[n]]
            if group:
                plan.append((spec, group, pk))
    n_packs = len(packs)

    n_jobs = sum(len(b) for _, b, _ in plan)
    print("Baseline: " + bl.describe())
    print(f"{len(cars)} cars x {len(specs)} tracks: {n_jobs} to run in {len(plan)} launches "
          f"({n_packs} pack(s) of up to {size} cars; each pack runs on every track before the next pack); "
          f"{done_skip} skipped (already rated), {fail_skip} skipped (failed before, use --retry-failed)")
    if args.dry_run:
        for spec, group, pk in plan[:10]:
            names_txt = ", ".join(c.name for c in group[:4]) + (" ..." if len(group) > 4 else "")
            print(f"  pack {pk}/{n_packs}  {spec}: {len(group)} cars [{names_txt}]")
        if len(plan) > 10:
            print(f"  ... {len(plan) - 10} more launches")
    if args.dry_run or not plan:
        return

    if not args.skip_track_check:
        import ac_track_check as tc
        print("Checking that the benchmark tracks are vanilla ...", flush=True)
        res = tc.verify(ac, list(dict.fromkeys(s for s, _, _ in plan)), args.reference,
                        template=None, ignore_ui=args.ignore_ui_files)
        env_id, env = tc.make_env(res, bl.PROFILE_ID) if res["status"] == "ok" else (None, None)
        args.env_id = env_id
        tc.append_log(res_path.with_name("track_check_log.json"), res, env_id, env)
        if res["status"] != "ok":
            sys.exit("\nStopped: the tracks are not confirmed vanilla, so ratings could be inaccurate or not comparable.\n"
                     "  - the server has no reference yet: its operator must create one (GUI tab \"Vanilla check\" > Create track\n"
                     "    reference) and load it with server.py set-env\n"
                     "  - differences listed above: remove the mods / delete extra files / verify the game files in Steam\n"
                     "  - or override with --skip-track-check (not recommended)")
        print("Tracks verified vanilla.\n", flush=True)

    backup = race_ini.with_name("race.ini.benchbak")
    if race_ini.exists() and not backup.exists():
        shutil.copy2(race_ini, backup)

    flag = result_file.parent / "bench_active.flag"   # fallback marker for the in-game logger
    t0 = time.time()
    try:
        flag.write_text("1")
        for k, (spec, group, pk) in enumerate(plan, 1):
            if args.stop_file and Path(args.stop_file).exists():
                raise KeyboardInterrupt
            batch, skipped = [], []
            for c in group:
                s = first_skin(c)
                (batch.append((c.name, s)) if s else skipped.append(c.name))
            for name in skipped:
                results.setdefault(name, {})[spec] = {"status": "failed", "reason": "no skins"}
            if not batch:
                save_results(res_path, results)
                continue

            print(f"[{k}/{len(plan)}] pack {pk}/{n_packs}  {spec}: {len(batch)} cars ...", flush=True)
            out = run_batch(args, ac, race_ini, result_file, cp, base_car, batch, spec)
            for car, r in out.items():
                results.setdefault(car, {})[spec] = r
                msg = f"{r['best_ms'] / 1000:.3f}s" if r["status"] == "ok" else f"FAILED {r['reason']}"
                print(f"    {car}: {msg}")
            save_results(res_path, results)

            if k == 1 and not any(len(r["laps_ms"]) for r in out.values()):
                sys.exit("First launch logged no laps at all. The logger app is probably not loading: "
                         "check the AC Bench app in the sidebar and README troubleshooting. Stopping.")
            eta = (time.time() - t0) / k * (len(plan) - k) / 3600
            print(f"    ETA ~{eta:.1f} h")
    except KeyboardInterrupt:
        print("\nStopped. Progress is saved; rerun to resume.")
    finally:
        flag.unlink(missing_ok=True)
        if backup.exists():
            shutil.copy2(backup, race_ini)


if __name__ == "__main__":
    main()
