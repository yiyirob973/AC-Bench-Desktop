#!/usr/bin/env python3
"""
Simple GUI for the AC car benchmark tools. Keep this file in the same folder as ac_lap_bench.py, ac_conditions.py,
ac_baseline.py, ac_track_check.py, ac_cloud.py, ac_car_classifier.py and ac_tag_writer.py, plus the bundled
template_race.ini (the race.ini the benchmark runs are built from) a bundled_car/<car id>/ folder (the car
the benchmark drives) and apps/lua/ac_bench/ (the in-game lap logger). The car and the logger are installed into
Assetto Corsa automatically before each benchmark; the user is never asked for any of these. Results (lap_results.json)
are saved in that folder. Settings are remembered in ac_bench_gui.json.

Tabs
The tabs follow the workflow, first step to last:
  1. Setup           Assetto Corsa folders, install the required car and Lua logger, server address and registration
  2. Vanilla check   compares the benchmark tracks and acs.exe with the environment the server publishes
  3. Benchmark       the server's conditions (read-only), choose cars, run, then upload the results
  4. Cars & ratings  "Local cars": your own ratings; "Server cars": live classes; apply the class tags

The benchmark conditions (profile, tracks, laps, the vanilla environment) are never set here: they are fetched from
the server before every benchmark, check and upload.

Server cars is LIVE: the installed cars are hashed (cached) and only those are looked up on the server
(ac_live.py, POST /v1/cars/lookup) when the tab opens, at start and on Refresh. The ratings are held in memory
only; "Apply server classes as tags" writes the class tags (always "#Pride-<class>") from that live data.

Run: python ac_bench_gui.py   (tkinter ships with the python.org installer)
"""
import csv, json, os, queue, re, shutil, subprocess, sys, threading
from datetime import datetime
from pathlib import Path

import ac_paths  # noqa: E402  (the script's own folder is already first on sys.path when run as a script)

HERE = ac_paths.DATA        # everything the app writes and keeps: settings, results, caches (beside the exe)
RES = ac_paths.RES          # everything shipped inside the app: race template, benchmark car, Lua logger
from ac_car_classifier import class_sort_key  # noqa: E402
import ac_conditions as cond  # noqa: E402
import ac_cloud  # noqa: E402  (link codes for signing in on another device)
import ac_live  # noqa: E402  (live per-car lookups for the Server cars list)
import ac_track_check  # noqa: E402  (file hashing, used to compare the bundled car with the installed one)

cond.ALLOW_STALE = True  # this process only: show the last known conditions while offline. Jobs never do this.

CFG_FILE = HERE / "ac_bench_gui.json"
STOP_FILE = HERE / "STOP"
RESULTS = HERE / "lap_results.json"
CLOUD_CLASSES = HERE / "car_classes_cloud.csv"
CLOUD_MISSING = HERE / "cloud_missing.txt"
# Server table cached by ac_cloud.py sync. CHECK this name against what ac_cloud.py leaves in this folder.
CLOUD_TABLE = HERE / "cloud_classes.json"
CLOUD_CFG = HERE / "cloud_config.json"

BUNDLED_CAR_DIR = RES / "bundled_car"    # holds ONE car folder (the car the benchmark drives); installed into AC
BUNDLED_LUA_APP = RES / "apps" / "lua" / "ac_bench"   # the in-game lap logger, installed into AC's apps/lua
TEMPLATE = RES / "template_race.ini"      # embedded in the app: the user never provides a race.ini
TAG_PREFIX = "#Pride-"                    # class tags are always "#Pride-<class>", not configurable
LEGACY_TAG_PREFIXES = ["#grid-class-"]    # tags from the earlier tool version: replaced, never left next to the new one

DEFAULTS = {
    "ac_dir": r"C:\Program Files (x86)\Steam\steamapps\common\assettocorsa",
    "docs_dir": str(Path.home() / "Documents" / "Assetto Corsa"),
    "group_by": "",
    "batch": 1, "include": "", "exclude": "",
    "retry_failed": False, "rerun_mode": "skip", "rerun_ids": "", "probe_ids": "", "probe_all_tracks": False,
    "start_delay": 25, "auto_upload": True,
    "cloud_url": "", "cloud_name": "", "cloud_invite": "", "cloud_link": "", "cloud_prov": False, "cloud_attest": True,
}

LOCAL_FILTERS = ["All", "Done", "Not done", "Partial", "Failed", "Old settings"]
SERVER_FILTERS = ["All", "Verified", "Provisional", "No server class", "Flagged"]


# ---------- command builders (pure functions, no GUI) ----------

def cars_dir(c):
    return str(Path(c["ac_dir"]) / "content" / "cars")


def bundled_car_id():
    """Folder name of the bundled benchmark car (bundled_car/<id>/), or None if there is none (or not exactly one)."""
    try:
        dirs = [p for p in BUNDLED_CAR_DIR.iterdir() if p.is_dir()]
    except OSError:
        return None
    return dirs[0].name if len(dirs) == 1 else None


def exclude_regex(user_regex=""):
    """The user's 'skip' regex plus the bundled car, which is never a test car, never listed and never tagged."""
    parts = [f"(?:{user_regex})"] if str(user_regex).strip() else []
    car = bundled_car_id()
    if car:
        parts.append(f"^{re.escape(car)}$")
    return "|".join(parts)


def install_bundled_car(ac_dir, say=print):
    """Make sure the bundled benchmark car is installed in content/cars and identical to the bundled copy
    (a different or damaged copy is replaced). -> True if the car is ready (or there is no bundled car)."""
    car = bundled_car_id()
    if car is None:
        if BUNDLED_CAR_DIR.is_dir() and any(p.is_dir() for p in BUNDLED_CAR_DIR.iterdir()):
            say("bundled_car must contain exactly one car folder.\n")
            return False
        say("No bundled benchmark car found (bundled_car folder): nothing to install.\n")
        return True
    src, dst = BUNDLED_CAR_DIR / car, Path(ac_dir) / "content" / "cars" / car
    want = ac_track_check.digest(ac_track_check.hash_tree(src))
    if dst.is_dir() and ac_track_check.digest(ac_track_check.hash_tree(dst)) == want:
        return True
    say(f"Installing the benchmark car {car} into {dst} ...\n")
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return ac_track_check.digest(ac_track_check.hash_tree(dst)) == want


def install_bundled_lua_app(ac_dir, say=print):
    """Install or update the bundled Lua lap logger in <AC>/apps/lua/<name>. Only the bundled files are compared
    and copied (other files in that folder, such as anything the logger writes, are left alone).
    -> True if the logger is installed and identical to the bundled copy."""
    src = BUNDLED_LUA_APP
    if not src.is_dir() or not any(src.iterdir()):
        say(f"The bundled Lua logger is missing from this app ({src}).\n")
        return False
    dst = Path(ac_dir) / "apps" / "lua" / src.name
    want = ac_track_check.hash_tree(src)
    have = ac_track_check.hash_tree(dst) if dst.is_dir() else {}
    changed = sorted(f for f in want if have.get(f) != want[f])
    for f in changed:
        target = dst / f
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / f, target)
    if changed:
        say(f"Installed the AC Bench Lua logger into {dst} ({len(changed)} file(s) updated).\n")
    extras = sorted(f for f in have if f not in want and f.lower().endswith((".lua", ".ini")))
    if extras:
        say("WARNING: extra Lua/ini files in the logger's folder may change its behaviour: " + ", ".join(extras) + "\n")
    after = ac_track_check.hash_tree(dst)
    return all(after.get(f) == want[f] for f in want)


def bundled_car_state(ac_dir):
    """(code, text) for the bundled benchmark car in <AC>/content/cars: ok | missing | outdated | nobundle."""
    car = bundled_car_id()
    if car is None:
        return "nobundle", "No benchmark car embedded in this app (bundled_car): reinstall or restore the app files"
    dst = Path(ac_dir) / "content" / "cars" / car
    if not dst.is_dir():
        return "missing", f"Benchmark car {car} is not installed"
    want = ac_track_check.digest(ac_track_check.hash_tree(BUNDLED_CAR_DIR / car))
    if ac_track_check.digest(ac_track_check.hash_tree(dst)) == want:
        return "ok", f"Benchmark car {car} is installed and up to date"
    return "outdated", f"Benchmark car {car} differs from the bundled copy (installing replaces it)"


def bundled_lua_state(ac_dir):
    """(code, text) for the bundled Lua lap logger in <AC>/apps/lua/<name>: ok | missing | outdated | nobundle."""
    src = BUNDLED_LUA_APP
    if not src.is_dir() or not any(src.iterdir()):
        return "nobundle", "No Lua logger embedded in this app (apps/lua/ac_bench): reinstall or restore the app files"
    dst = Path(ac_dir) / "apps" / "lua" / src.name
    if not dst.is_dir():
        return "missing", "Lap logger (Lua app) is not installed"
    want, have = ac_track_check.hash_tree(src), ac_track_check.hash_tree(dst)
    if all(have.get(f) == want[f] for f in want):
        return "ok", "Lap logger (Lua app) is installed and up to date"
    return "outdated", "Lap logger (Lua app) is out of date (installing updates it)"


def bench_cmd(c, extra=()):
    cmd = ["ac_lap_bench.py", "--ac-dir", c["ac_dir"], "--docs-dir", c["docs_dir"],
           "--template", str(TEMPLATE), "--batch", str(c["batch"]),
           "--results", str(RESULTS), "--stop-file", str(STOP_FILE)]
    if c["group_by"]:
        cmd += ["--group-by", c["group_by"]]
    if c["include"]:
        cmd += ["--include", c["include"]]
    ex = exclude_regex(c["exclude"])
    if ex:
        cmd += ["--exclude", ex]
    if c["retry_failed"]:
        cmd.append("--retry-failed")
    cmd += ["--start-delay", str(c["start_delay"])]
    if c["auto_upload"] and str(c["cloud_url"]).strip():      # send each pack's times as soon as its cars have finished
        cmd += ["--auto-upload", "--server", str(c["cloud_url"]).strip()]
    cmd += list(extra)
    # variable-length options go last
    if c["rerun_mode"] == "all":
        cmd.append("--rerun")
    elif c["rerun_mode"] == "ids" and c["rerun_ids"].split():
        cmd += ["--rerun", *c["rerun_ids"].split()]
    return cmd


def cloud_cmd(c, action):
    cmd = ["ac_cloud.py"]
    if str(c["cloud_url"]).strip():
        cmd += ["--server", str(c["cloud_url"]).strip()]
    if action == "ping":
        return cmd + ["ping"]
    if action == "register":
        # --invite=VALUE keeps a code that starts with "-" from being mistaken for an option
        return cmd + ["register", "--invite=" + str(c["cloud_invite"]).strip(), "--name=" + str(c["cloud_name"]).strip()]
    if action == "login":     # --code=VALUE: a code is never mistaken for an option
        return cmd + ["login", "--code=" + str(c["cloud_link"]).strip()]
    cmd += [action, "--cars-dir", cars_dir(c)]
    if action == "upload" and c.get("cloud_attest"):
        cmd.append("--attest-legacy")
    return cmd


def conditions_cmd(c):
    """Fetch the benchmark conditions from the server (If-None-Match)."""
    cmd = ["ac_conditions.py", "fetch"]
    if str(c["cloud_url"]).strip():
        cmd += ["--server", str(c["cloud_url"]).strip()]
    return cmd


def verify_cmd(c):
    """Vanilla check against the server's environment (tracks come from the server too)."""
    return ["ac_track_check.py", "verify", "--ac-dir", c["ac_dir"]]


def create_ref_cmd(c, out=""):
    """Operator: build the canonical track reference from this install (the track list comes from the server)."""
    cmd = ["ac_track_check.py", "create", "--ac-dir", c["ac_dir"]]
    if out:
        cmd += ["--out", out]
    return cmd


def probe_cmd(c, ids=None, all_tracks=None):
    """Rebenchmark chosen cars. By default only the tracks where a car has no valid time yet are run;
    all_tracks=True (or the 'probe_all_tracks' setting) redoes every track."""
    ids = list(ids) if ids is not None else c["probe_ids"].split()
    if all_tracks is None:
        all_tracks = bool(c.get("probe_all_tracks"))
    return bench_cmd(c, (["--all-tracks"] if all_tracks else []) + ["--probe", *ids])


def tag_cmd(c, mode):
    """mode: apply | untag | restore. 'apply' looks up only the locally installed cars on the server.
    Tags are always TAG_PREFIX + class."""
    if mode == "restore":
        return ["ac_tag_writer.py", cars_dir(c), "--restore"]
    if mode == "apply":   # finds the local cars and asks the server about only those (ac_live.py tag)
        cmd = ["ac_live.py", "tag", "--server", str(c["cloud_url"]).strip(), "--cars-dir", cars_dir(c)]
        if c.get("cloud_prov"):
            cmd.append("--include-provisional")
    else:
        cmd = ["ac_tag_writer.py", cars_dir(c)]
    cmd += ["--prefix", TAG_PREFIX]
    if mode == "apply" and bundled_car_id():
        cmd += ["--exclude", exclude_regex()]
    for old in LEGACY_TAG_PREFIXES:
        cmd += ["--also-remove", old]
    cmd.append("--apply")
    if mode == "untag":
        cmd.append("--untag")
    return cmd


# ---------- car list data (pure functions, no GUI) ----------

def load_car_names(ac_dir):
    """[(folder id, display name)] for every car in content/cars."""
    base = Path(ac_dir) / "content" / "cars"
    cars = []
    if not base.is_dir():
        return cars
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        name = d.name
        try:
            j = json.loads((d / "ui" / "ui_car.json").read_text(encoding="utf-8-sig", errors="replace"),
                           strict=False)
            name = str(j.get("name") or d.name)
        except Exception:
            pass
        cars.append((d.name, name))
    return cars


def build_rows(cars, results, tracks, profile=None):
    """Rows for the LOCAL car list: only the lap times this PC measured. The class is NOT worked out here: the
    server classifies (upload, then see the Server cars list). 'done' = a valid time on every track."""
    tracks = [t.strip() for t in tracks if t and t.strip()]
    try:
        import ac_rating as rating
        lap_score = rating.lap_score
    except cond.ConditionsUnavailable:  # no usable conditions yet: list the cars without times
        lap_score = (lambda e: (None,))
    rows = []
    for cid, name in cars:
        r = results.get(cid, {})
        times, nok, failed, why = [], 0, False, ""
        for t in tracks:
            e = r.get(t, {})
            ms = lap_score(e)[0] if e.get("status") == "ok" else None
            times.append(None if ms is None else ms / 1000)
            nok += 1 if ms is not None else 0
            if e.get("status") == "failed":
                failed, why = True, why or str(e.get("reason") or "")
        if tracks and nok == len(tracks):
            old = any(r.get(t, {}).get("profile") != profile for t in tracks)
            status = "done (old settings)" if old else "done"
        elif nok:
            status = f"partial {nok}/{len(tracks)}"
        else:
            status = ("failed: " + why[:40] if why else "failed") if failed else "not run"
        rows.append({"id": cid, "name": name, "status": status, "times": times, "gap": None, "cls": None,
                     "flags": "", "bop": "", "variance": None})
    return rows


def _num(v):
    try:
        return float(v) if v not in ("", None) else None
    except (TypeError, ValueError):
        return None


def read_cloud_csv(csv_path):
    """{car id: csv row} from the downloaded server classes (empty if the file is not there)."""
    by_id = {}
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                by_id[r.get("id", "")] = r
    except OSError:
        pass
    return by_id


def purge_downloaded():
    """Delete the downloaded server ratings from disk and forget the download marker, so the next sync fetches
    the table fresh (otherwise the server answers 'not modified' and there is nothing left to read)."""
    for p in (CLOUD_CLASSES, CLOUD_TABLE):
        try:
            p.unlink()
        except OSError:
            pass
    try:
        j = json.loads(CLOUD_CFG.read_text(encoding="utf-8"))
        gone = [k for k in j if "etag" in k.lower()]
        for k in gone:
            j.pop(k)
        if gone:
            CLOUD_CFG.write_text(json.dumps(j, indent=1), encoding="utf-8")
    except (OSError, ValueError):
        pass


def load_cloud_rows(cars, source, tracks):
    """Rows for the SERVER car list. source: {car id: csv row} (or a CSV path). Every car in the library gets
    a row; cars the server has no usable class for are 'no server class'."""
    tracks = [t.strip() for t in tracks if t and t.strip()]
    by_id = source if isinstance(source, dict) else read_cloud_csv(source)
    rows = []
    for cid, name in cars:
        r = by_id.get(cid)
        if not r:
            rows.append({"id": cid, "name": name, "status": "no server class", "times": [None] * len(tracks),
                         "gap": None, "cls": None, "flags": "", "bop": "", "variance": None})
            continue
        rows.append({
            "id": cid, "name": name,
            "status": (r.get("cloud_status") or "verified").strip().lower(),
            "times": [_num(r.get("time_" + t.replace("/", "_"))) for t in tracks],
            "gap": _num(r.get("gap_pct")), "cls": (r.get("class") or "").strip() or None,
            "flags": r.get("flags", "") or "", "bop": r.get("bop", "") or "",
            "variance": _num(r.get("variance_pct"))})
    return rows


def status_tag(status):
    """Colour group for a row status."""
    s = status.lower()
    if s.startswith("failed"):
        return "bad"
    if "old settings" in s or s.startswith("partial") or s == "provisional":
        return "warn"
    if s.startswith("done") or s == "verified":
        return "ok"
    return "dim"


def row_matches(kind, r, text, sf):
    """Filter box + status dropdown for a row of either list."""
    if text and text not in r["id"].lower() and text not in r["name"].lower():
        return False
    s = r["status"]
    if sf == "All":
        return True
    if sf == "Flagged":
        return bool(r["flags"])
    if kind == "local":
        return ((sf == "Done" and s.startswith("done")) or (sf == "Not done" and not s.startswith("done"))
                or (sf == "Partial" and s.startswith("partial")) or (sf == "Failed" and s.startswith("failed"))
                or (sf == "Old settings" and "old settings" in s))
    return ((sf == "Verified" and s == "verified") or (sf == "Provisional" and s == "provisional")
            or (sf == "No server class" and s == "no server class"))


# ---------- GUI ----------

def main():
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import ttk, filedialog, messagebox, scrolledtext

    root = tk.Tk()
    root.title("AC Bench")
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    ww, wh = min(1060, sw - 80), min(780, sh - 120)
    root.geometry(f"{ww}x{wh}+{max(0, (sw - ww) // 2)}+{max(0, (sh - wh) // 3)}")
    root.minsize(min(900, ww), min(520, wh))

    # ---- look and feel ----
    style = ttk.Style(root)
    try:
        style.theme_use("vista" if os.name == "nt" else "clam")
    except tk.TclError:
        pass
    for fname in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        try:
            tkfont.nametofont(fname).configure(size=10)
        except tk.TclError:
            pass
    bold = tkfont.nametofont("TkDefaultFont").copy()
    bold.configure(weight="bold")
    style.configure("Treeview", rowheight=24)
    style.configure("Treeview.Heading", font=bold, padding=(6, 4))
    style.configure("TButton", padding=(8, 4))
    style.configure("Accent.TButton", font=bold, padding=(12, 5))
    style.configure("TNotebook.Tab", padding=(14, 6))
    style.configure("Muted.TLabel", foreground="#6e7781")
    style.configure("Bold.TLabel", font=bold)
    style.configure("TLabelframe.Label", font=bold)

    def fixed_map(option):  # workaround: Tk 8.6.9 ignores Treeview row tag colours without this
        return [e for e in style.map("Treeview", query_opt=option) if e[:2] != ("!disabled", "!selected")]
    style.map("Treeview", foreground=fixed_map("foreground"), background=fixed_map("background"))

    saved = {}
    if CFG_FILE.exists():
        try:
            saved = json.loads(CFG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    vars_ = {}
    if "start_delay" not in saved and "click_delay" in saved:
        saved["start_delay"] = saved["click_delay"]     # the old name of the delay before the first start attempt
    for k, d in DEFAULTS.items():
        v = saved.get(k, d)
        if isinstance(d, bool):
            vars_[k] = tk.BooleanVar(value=bool(v))
        elif isinstance(d, int):
            vars_[k] = tk.IntVar(value=int(v))
        elif isinstance(d, float):
            vars_[k] = tk.DoubleVar(value=float(v))
        else:
            vars_[k] = tk.StringVar(value=str(v))

    def cfg():
        out = {}
        for k, v in vars_.items():
            try:
                out[k] = v.get()
            except tk.TclError:
                out[k] = DEFAULTS[k]  # blank/invalid number field
        d = cond.load_any()  # the tracks come from the server, never from this app
        tr = (d["tracks"] if d else []) + ["", ""]
        out["track1"], out["track2"] = tr[0], tr[1]
        return out

    def save_cfg():
        CFG_FILE.write_text(json.dumps(cfg(), indent=1), encoding="utf-8")

    # --- log (hidden by default) + process runner ---
    log_frame = ttk.Frame(root)
    log_head = ttk.Frame(log_frame)
    log_head.pack(fill="x")
    ttk.Label(log_head, text="Log", style="Bold.TLabel").pack(side="left")
    log = scrolledtext.ScrolledText(log_frame, height=12, state="disabled", font=("Consolas", 9))
    ttk.Button(log_head, text="Clear",
               command=lambda: (log.configure(state="normal"), log.delete("1.0", "end"),
                                log.configure(state="disabled"))).pack(side="right")
    log.pack(fill="both", expand=True, pady=(4, 0))

    status = tk.StringVar(value="Idle")
    last_line = tk.StringVar(value="")
    q = queue.Queue()
    state = {"proc": None, "graceful": False, "on_done": None, "stopping": False,
             "cars": [], "cars_dir": None, "server_by_id": {}, "server_stamp": "", "purge_pending": False,
             "live_busy": False, "live_ok": False, "live_error": "", "live_at": 0.0, "live_msg": "", "live_found": 0}
    hooks = []  # called after every finished job (e.g. refresh the car lists)
    run_buttons = []

    def toggle_log(force=None):
        want = (not state.get("log_open", False)) if force is None else force
        state["log_open"] = want
        if want:
            log_frame.pack(side="bottom", fill="x", padx=10, pady=(0, 6), before=nb)
            log_btn.configure(text="Hide log")
            log.see("end")
        else:
            log_frame.pack_forget()
            log_btn.configure(text="Show log")

    def write(text):
        log.configure(state="normal")
        log.insert("end", text)
        log.see("end")
        log.configure(state="disabled")

    def set_busy(busy):
        for b in run_buttons:
            b.configure(state="disabled" if busy else "normal")
        stop_btn.configure(state="normal" if busy else "disabled")
        status.set("Running..." if busy else "Idle")
        if busy:
            progress.start(14)
        else:
            progress.stop()

    def reader(proc):
        for line in proc.stdout:
            q.put(line)
        q.put(("done", proc.wait()))

    def poll():
        try:
            while True:
                item = q.get_nowait()
                if isinstance(item, tuple):
                    write(f"[finished, exit code {item[1]}]\n")
                    state["last_rc"] = item[1]
                    state["proc"] = None
                    set_busy(False)
                    if item[1] != 0 and not state["stopping"] and not state.get("quiet"):
                        toggle_log(True)  # something went wrong: show the details
                    for h in hooks:
                        h()
                    cb, state["on_done"] = state["on_done"], None
                    if cb and item[1] == 0:
                        cb()
                else:
                    write(item)
                    if item.strip():
                        last_line.set(item.strip()[:140])
        except queue.Empty:
            pass
        root.after(150, poll)

    def run(cmd, graceful=False, on_done=None, quiet=False):
        if state["proc"]:
            return
        save_cfg()
        if STOP_FILE.exists():
            STOP_FILE.unlink()
        write("\n$ " + " ".join(f'"{a}"' if " " in a else a for a in cmd) + "\n")
        state["last_cmd"] = cmd
        state["stopping"] = False
        state["quiet"] = quiet
        last_line.set("")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            proc = subprocess.Popen(script_command(cmd), cwd=HERE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                    errors="replace", creationflags=flags, env=script_env())
        except Exception as e:
            messagebox.showerror("Could not start", f"{script_command(cmd)[0]}\n\n{e}")
            return
        state.update(proc=proc, graceful=graceful, on_done=on_done)
        set_busy(True)
        threading.Thread(target=reader, args=(proc,), daemon=True).start()

    def stop():
        p = state["proc"]
        if not p:
            return
        state["stopping"] = True
        if state["graceful"] and not STOP_FILE.exists():
            STOP_FILE.touch()
            write("Stop requested: finishing up (kills AC, keeps saved results)...\n")
            status.set("Stopping...")
        else:
            p.terminate()
            write("Terminated.\n")

    # --- validation helpers ---
    def need(*keys):
        c = cfg()
        for k in keys:
            if not str(c[k]).strip():
                messagebox.showwarning("Missing setting", f"Please fill in: {k.replace('_', ' ')}")
                return None
        return c

    def install_required(c):
        """Install/update the bundled benchmark car and the Lua lap logger into the AC folder. -> True if both are ready."""
        try:
            car_ok = install_bundled_car(c["ac_dir"], say=write)
        except OSError as e:
            messagebox.showerror("Benchmark car", f"Could not install the bundled benchmark car: {e}")
            return None
        if not car_ok:
            messagebox.showwarning("Benchmark car", "The bundled benchmark car could not be installed correctly "
                                                    "(see the log). Reinstall or restore the app files.")
            return None
        try:
            lua_ok = install_bundled_lua_app(c["ac_dir"], say=write)
        except OSError as e:
            messagebox.showerror("Lua logger", f"Could not install the bundled Lua logger: {e}")
            return None
        if not lua_ok:
            messagebox.showwarning("Lua logger", "The bundled Lua logger could not be installed correctly "
                                                 "(see the log). Reinstall or restore the app files.")
            return None
        return True

    def need_bench():
        c = need("ac_dir", "docs_dir")
        if not c:
            return None
        if not (Path(c["ac_dir"]) / "acs.exe").exists():
            messagebox.showwarning("AC folder", "acs.exe not found in the Assetto Corsa folder.")
            return None
        if not TEMPLATE.exists():
            messagebox.showwarning("Template", f"{TEMPLATE.name} is missing from this app (it should be embedded). "
                                               "Reinstall or restore the app files.")
            return None
        if not install_required(c):
            return None
        return c

    def need_csv(path):
        if not Path(path).exists():
            messagebox.showwarning("Missing file", f"{path.name} not found yet. Run the earlier step first.")
            return False
        return True

    def run_with_conditions(build, graceful=False):
        """Fetch the benchmark conditions from the server first, then run build() -> command.
        Nothing runs if the server cannot be reached: the conditions are never taken from this PC."""
        c = cfg()
        if not c["cloud_url"].strip():
            messagebox.showwarning("Server", "The benchmark conditions come from the server. "
                                             "Fill in the server address on the Setup tab first.")
            return
        run(conditions_cmd(c), on_done=lambda: run(build(), graceful=graceful))

    # --- widget helpers ---
    def entry_row(parent, r, label, key, browse=None, width=60):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", padx=(4, 10), pady=3)
        ttk.Entry(parent, textvariable=vars_[key], width=width).grid(row=r, column=1, sticky="ew", pady=3)
        if browse == "dir":
            cmd = lambda: vars_[key].set(filedialog.askdirectory(initialdir=vars_[key].get() or None) or vars_[key].get())
        elif browse == "file":
            cmd = lambda: vars_[key].set(filedialog.askopenfilename() or vars_[key].get())
        else:
            return
        ttk.Button(parent, text="Browse", command=cmd).grid(row=r, column=2, padx=(8, 4))

    def btn(parent, text, command, r, c, span=1, accent=False):
        b = ttk.Button(parent, text=text, command=command, style="Accent.TButton" if accent else "TButton")
        b.grid(row=r, column=c, columnspan=span, padx=(0, 8), pady=6, sticky="w")
        run_buttons.append(b)
        return b

    def pbtn(parent, text, command, accent=False, side="left"):
        """Pack-style button that is disabled while a job runs."""
        b = ttk.Button(parent, text=text, command=command, style="Accent.TButton" if accent else "TButton")
        b.pack(side=side, padx=(0, 8))
        run_buttons.append(b)
        return b

    def group(parent, title):
        f = ttk.LabelFrame(parent, text=title, padding=10)
        f.pack(fill="x", pady=(0, 10))
        f.columnconfigure(1, weight=1)
        return f

    scroll_areas = []

    def scroll_tab(parent, padding=12):
        """A tab page that scrolls vertically when its content is taller than the window. -> (outer, inner):
        add `outer` to the notebook and build the page inside `inner`."""
        outer = ttk.Frame(parent)
        canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=padding)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)

        def layout(_=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            need_bar = inner.winfo_reqheight() > canvas.winfo_height() > 1
            if need_bar and not vsb.winfo_ismapped():
                vsb.pack(side="right", fill="y", before=canvas)
            elif not need_bar and vsb.winfo_ismapped():
                vsb.pack_forget()
                canvas.yview_moveto(0)

        def fit_width(e):
            canvas.itemconfigure(win, width=e.width)
            layout()

        inner.bind("<Configure>", layout)
        canvas.bind("<Configure>", fit_width)
        scroll_areas.append((outer, canvas, inner))
        return outer, inner

    def on_wheel(e):
        w = root.winfo_containing(e.x_root, e.y_root)
        while w is not None:           # lists and text boxes keep their own wheel scrolling
            if isinstance(w, (ttk.Treeview, tk.Text, tk.Listbox)):
                return
            for outer, canvas, inner in scroll_areas:
                if w is outer:
                    if inner.winfo_reqheight() > canvas.winfo_height():
                        step = -1 if (e.num == 4 or e.delta > 0) else 1
                        canvas.yview_scroll(step * 3, "units")
                    return
            w = w.master

    root.bind_all("<MouseWheel>", on_wheel)
    root.bind_all("<Button-4>", on_wheel)   # Linux
    root.bind_all("<Button-5>", on_wheel)

    nb = ttk.Notebook(root)

    # ======== Tab: Vanilla check ========
    tv_page, tv = scroll_tab(nb)
    vstat = tk.StringVar(value="Not checked yet")
    ttk.Label(tv, textvariable=vstat, style="Bold.TLabel").pack(anchor="w", pady=(0, 8))

    def do_verify():
        if need("ac_dir"):
            run_with_conditions(lambda: verify_cmd(cfg()))

    def do_create_ref():
        c = need("ac_dir", "cloud_url")
        if not c:
            return
        if not messagebox.askyesno("Create track reference",
                                   "This turns THIS Assetto Corsa install into the canonical reference for the server: "
                                   "every benchmark track folder and acs.exe are fingerprinted.\n\n"
                                   "Only do this on a clean install (Steam > Verify integrity of game files, no extra "
                                   "files in the track folders, no CSP track configs).\n\nContinue?"):
            return
        out = filedialog.asksaveasfilename(title="Save the track reference", defaultextension=".json",
                                           initialfile="track_reference.json", filetypes=[("JSON", "*.json")])
        if out:
            run(create_ref_cmd(c, out))   # reads only the track list from the server; needs no environment

    def do_steam():
        try:
            os.startfile("steam://validate/244210")
        except Exception as e:
            messagebox.showinfo("Steam", f"Could not open Steam ({e}).\nIn Steam: Assetto Corsa > Properties > "
                                         "Installed Files > Verify integrity of game files.")

    vf = ttk.Frame(tv)
    vf.pack(fill="x")
    pbtn(vf, "Verify tracks now", do_verify, accent=True)
    ttk.Button(vf, text="Ask Steam to verify game files", command=do_steam).pack(side="left", padx=(0, 6))
    ttk.Button(vf, text="Create track reference (server operator)", command=do_create_ref).pack(side="left")
    ttk.Label(tv, justify="left", style="Muted.TLabel", text=(
        "Compares every file of the benchmark tracks (including the AI racing lines) and acs.exe (the AI driving\n"
        "code) with the environment the server publishes. Benchmarks run this check first and stop on any\n"
        "difference. The server only keeps fingerprints, so a mismatch cannot list the files: use Steam's\n"
        "'Verify integrity of game files' and remove any extra files you added to the track folders.\n"
        "The tracks, laps and race settings are set by the server and cannot be changed here.\n"
        "Server operators: 'Create track reference' fingerprints this (clean) install into a file; load it on the\n"
        "server with: python server.py set-env --from <file>.")
              ).pack(anchor="w", pady=10)

    def vstatus_hook():
        cmd = state.get("last_cmd") or []
        if len(cmd) > 1 and cmd[0] == "ac_track_check.py" and cmd[1] == "create":
            rc = state.get("last_rc")
            vstat.set({0: "Track reference created (see log for the file and the set-env command)",
                       2: "Reference NOT created: install incomplete (see log)",
                       3: "Cannot create: no track list from the server"}.get(rc, f"Create failed (exit {rc})"))
        elif len(cmd) > 1 and cmd[0] == "ac_track_check.py":
            rc = state.get("last_rc")
            vstat.set({0: "Tracks are vanilla: identical to the server's environment",
                       2: "NOT VANILLA: differs from the server's environment (see log)",
                       3: "Cannot check: no usable benchmark conditions from the server"}.get(rc, f"Check failed (exit {rc})"))

    hooks.append(vstatus_hook)

    # ======== Tab: Setup (step 1) ========
    ts_page, ts = scroll_tab(nb)

    next_step = tk.StringVar()
    ttk.Label(ts, textvariable=next_step, style="Bold.TLabel").pack(anchor="w", pady=(0, 8))

    acg = group(ts, "Assetto Corsa")
    entry_row(acg, 0, "Assetto Corsa folder", "ac_dir", "dir")
    entry_row(acg, 1, "Documents/Assetto Corsa", "docs_dir", "dir")
    entry_row(acg, 2, "Batch grouping CSV (optional)", "group_by", "file")

    rq = group(ts, "Required files (the benchmark car and the lap logger)")
    ac_stat, car_stat, lua_stat = tk.StringVar(), tk.StringVar(), tk.StringVar()
    for i, v in enumerate((ac_stat, car_stat, lua_stat)):
        ttk.Label(rq, textvariable=v).grid(row=i, column=0, columnspan=3, sticky="w", padx=4)
    ttk.Label(rq, justify="left", style="Muted.TLabel", text=(
        "Both ship with this app and go into your Assetto Corsa folder: the benchmark car into content/cars and the\n"
        "Lua logger into apps/lua/ac_bench. A different or damaged copy is replaced. This also happens automatically\n"
        "before every benchmark.")).grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))

    def do_install_required():
        c = need("ac_dir")
        if not c:
            return
        if not (Path(c["ac_dir"]) / "acs.exe").exists():
            messagebox.showwarning("AC folder", "acs.exe not found in the Assetto Corsa folder.")
            return
        if install_required(c):
            write("Required files are installed and up to date.\n")
            messagebox.showinfo("Required files", "The benchmark car and the lap logger are installed and up to date.")
        refresh_setup()
        cars_refresh(rescan=True)

    rqb = ttk.Frame(rq)
    rqb.grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))
    pbtn(rqb, "Install / update required files", do_install_required, accent=True)
    pbtn(rqb, "Check again", lambda: refresh_setup())

    sg = group(ts, "Server")
    entry_row(sg, 0, "Server address (https://...)", "cloud_url")
    entry_row(sg, 1, "Your name (for registering)", "cloud_name", width=30)
    entry_row(sg, 2, "Invite code (for registering)", "cloud_invite", width=30)
    cloud_stat = tk.StringVar()

    def refresh_cloud_status():
        try:
            j = json.loads(CLOUD_CFG.read_text(encoding="utf-8"))
        except Exception:
            j = {}
        cloud_stat.set(("Registered as " + str(j.get("name", "?"))) if j.get("api_key") else "Not registered yet")

    ttk.Label(sg, textvariable=cloud_stat, style="Bold.TLabel").grid(row=3, column=0, columnspan=3, sticky="w", padx=4, pady=(6, 0))
    ttk.Checkbutton(sg, text="Also use classes backed by a single submission (less reliable)",
                    variable=vars_["cloud_prov"]).grid(row=4, column=0, columnspan=3, sticky="w", padx=4, pady=(8, 0))

    def do_cloud(action):
        c = cfg()
        if not c["cloud_url"].strip():
            messagebox.showwarning("Server", "Fill in the server address first (Setup tab).")
            return
        if action == "register" and not (c["cloud_name"].strip() and c["cloud_invite"].strip()):
            messagebox.showwarning("Server", "Registering needs your name and an invite code.")
            return
        if action == "login" and not c["cloud_link"].strip():
            messagebox.showwarning("Server", "Enter the link code created on your other device first.")
            return
        if action == "upload" and not need("ac_dir"):
            return
        if action == "upload" and c["cloud_attest"]:
            # older results are attested with the CURRENT environment, so verify the tracks right now first
            run(conditions_cmd(c), on_done=lambda: run(verify_cmd(cfg()), on_done=lambda: run(cloud_cmd(c, "upload"))))
            return
        run(cloud_cmd(c, action))

    def do_download_and_tag():
        """Tag the cars installed here: the app identifies them, asks the server about only those, and writes the tags."""
        c = cfg()
        if not c["cloud_url"].strip():
            messagebox.showwarning("Server", "Fill in the server address first (Setup tab).")
            return
        if not need("ac_dir"):
            return
        if not messagebox.askyesno(
                "Apply server classes as tags",
                f"The app will identify the cars installed here, ask the server about only those cars, and write a "
                f"{TAG_PREFIX}<class> tag into each one it has a "
                f"{'verified or provisional' if c['cloud_prov'] else 'verified'} class for (backups are made first). "
                "Nothing is downloaded or saved beyond that.\n\nContinue?"):
            return
        run(tag_cmd(c, "apply"))

    sb = ttk.Frame(sg)
    sb.grid(row=6, column=0, columnspan=3, sticky="w", pady=(10, 0))
    pbtn(sb, "Test connection", lambda: do_cloud("ping"))
    pbtn(sb, "Register", lambda: do_cloud("register"))
    pbtn(sb, "Create link code for another device", lambda: do_link_code())
    ttk.Label(sg, justify="left", style="Muted.TLabel", text=(
        "Register once with the invite code you were given. Already registered on another PC? Press 'Create link code'\n"
        "there, then enter the code under 'Use the same account on another device' just below and press Sign in.\n"
        "Uploading results is step 3, on the Benchmark tab; the class tags are applied on the Cars & ratings tab.")
              ).grid(row=7, column=0, columnspan=3, sticky="w", pady=(8, 0))

    # ---- the same account on another device
    dv = group(ts, "Use the same account on another device")
    entry_row(dv, 0, "Link code (from your other device)", "cloud_link", width=30)

    def show_link_code(code, minutes):
        win = tk.Toplevel(root)
        win.title("Link code")
        win.transient(root)
        win.resizable(False, False)
        ttk.Label(win, justify="left", text=("On your other device open the Setup tab, enter this code under\n"
                                              "'Use the same account on another device' and press Sign in:")
                  ).pack(padx=16, pady=(16, 8))
        ent = ttk.Entry(win, justify="center", font=("Consolas", 18), width=16)
        ent.insert(0, code)
        ent.configure(state="readonly")
        ent.pack(padx=16)
        ttk.Label(win, style="Muted.TLabel", text=f"It works once and for {minutes} minutes.").pack(pady=(8, 0))
        bb = ttk.Frame(win)
        bb.pack(pady=14)

        def copy():
            root.clipboard_clear()
            root.clipboard_append(code)
        ttk.Button(bb, text="Copy", command=copy).pack(side="left", padx=4)
        ttk.Button(bb, text="Close", command=win.destroy).pack(side="left", padx=4)

    def do_link_code():
        """Signed in here: get a single-use code that signs another device in as the same account."""
        import argparse
        c = cfg()
        if not c["cloud_url"].strip():
            messagebox.showwarning("Server", "Fill in the server address first.")
            return

        def work():
            try:
                cd = ac_cloud.settings(argparse.Namespace(server=c["cloud_url"].strip()))
                code, r, _ = ac_cloud.call(cd, "POST", "/v1/devices/link", {}, auth=True)
                err = None if code == 201 else f"HTTP {code}: {(r or {}).get('error', code)}"
            except SystemExit as e:
                r, err = None, str(e)

            def done():
                if err:
                    messagebox.showerror("Link code", err)
                else:
                    show_link_code(r["code"], r["expires_in"] // 60)
            root.after(0, done)
        threading.Thread(target=work, daemon=True).start()

    dvb = ttk.Frame(dv)
    dvb.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
    pbtn(dvb, "Sign in with link code", lambda: do_cloud("login"), accent=True)
    ttk.Label(dv, justify="left", style="Muted.TLabel", text=(
        "To get a code, press 'Create link code for another device' next to Register on a device that is already signed in.\n"
        "Each device gets its own key for the same account; the code works once and expires after 10 minutes.")
              ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

    drv = group(ts, "Starting each race")
    af = ttk.Frame(drv)
    af.grid(row=0, column=0, columnspan=3, sticky="w", pady=(2, 0))
    ttk.Label(af, text="first try after launching AC (s)").grid(row=0, column=0, padx=(4, 4))
    ttk.Spinbox(af, from_=5, to=300, width=5, textvariable=vars_["start_delay"]).grid(row=0, column=1)
    btn(af, "Set up start hotkey", lambda: run(["ac_controls.py", "setup", "--docs-dir", cfg()["docs_dir"],
                                                 "--ac-dir", cfg()["ac_dir"]]), 1, 0)
    btn(af, "Test start hotkey (AC open on the pre-race screen)",
        lambda: run(["ac_input.py", "hotkey", "--docs-dir", cfg()["docs_dir"]]), 1, 1, 2)
    ttk.Label(drv, justify="left", style="Muted.TLabel", text=(
        "Every race is started by pressing AC's 'Start race' hotkey (Ctrl + a key, the same command as in Content Manager > Settings >\n"
        "Assetto Corsa > Controls > System). A key you already set there is used; F12 is set only if nothing is set. Custom Shaders\n"
        "Patch handles it inside the game when it lists __CM_START_SESSION, so Content Manager need not run. 'Set up start hotkey'\n"
        "shows what controls.ini contains. Restart AC after the key changes.")
              ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

    tgs = group(ts, "Optional: car tag clean-up")
    ttk.Label(tgs, justify="left", style="Muted.TLabel", text=(
        f"Class tags are always written as {TAG_PREFIX}<class> (for example {TAG_PREFIX}A): one per car, never duplicated.\n"
        "Backups of the changed car files are kept next to them.")).grid(row=0, column=0, columnspan=3, sticky="w")

    def do_tags(mode):
        c = need("ac_dir")
        if not c or not messagebox.askyesno("Confirm", {
                "untag": f"Remove all {TAG_PREFIX}* tags from your car files?",
                "restore": "Restore every car file from its backup (discards other edits made to those files)?"}[mode]):
            return
        run(tag_cmd(c, mode))

    tf = ttk.Frame(tgs)
    tf.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))
    pbtn(tf, f"Remove {TAG_PREFIX} tags", lambda: do_tags("untag"))
    pbtn(tf, "Restore car file backups", lambda: do_tags("restore"))
    # ======== Tab: Cars & ratings (Local cars | Server cars) ========
    tc = ttk.Frame(nb, padding=10)
    tc.columnconfigure(0, weight=1)
    tc.rowconfigure(0, weight=1)
    sub = ttk.Notebook(tc)
    sub.grid(row=0, column=0, sticky="nsew")

    def do_bench_selected(s, all_tracks=False):
        ids = list(s["tree"].selection())
        if not ids:
            messagebox.showinfo("Select cars", "Select one or more cars in the list first.")
            return
        c = need_bench()
        if not c:
            return
        if len(ids) > 20:
            what = "on every track, even if already rated" if all_tracks else "only on the tracks where they have no time yet"
            if not messagebox.askyesno("Many cars", f"{len(ids)} cars selected. They run {what}. Continue?"):
                return
        run_with_conditions(lambda: probe_cmd(cfg(), ids, all_tracks), graceful=True)

    def make_section(kind):
        local = kind == "local"
        s = {"kind": kind, "rows": [], "sort": ("gap", False)}
        fr = ttk.Frame(sub, padding=(0, 10, 0, 0))
        fr.columnconfigure(0, weight=1)
        fr.rowconfigure(1, weight=1)
        s["frame"] = fr

        top = ttk.Frame(fr)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        s["filt"], s["stat"] = tk.StringVar(), tk.StringVar(value="All")
        s["count"], s["info"] = tk.StringVar(), tk.StringVar()
        ttk.Label(top, text="Filter").pack(side="left")
        ttk.Entry(top, textvariable=s["filt"], width=26).pack(side="left", padx=(6, 14))
        ttk.Label(top, text="Show").pack(side="left")
        box = ttk.Combobox(top, textvariable=s["stat"], state="readonly", width=16,
                           values=LOCAL_FILTERS if local else SERVER_FILTERS)
        box.pack(side="left", padx=6)
        ttk.Label(top, textvariable=s["count"], style="Muted.TLabel").pack(side="right")

        if local:
            cols = ("name", "id", "t1", "t2", "status")
            widths = (240, 170, 130, 130, 160)
        else:
            cols = ("name", "id", "cls", "gap", "t1", "t2", "var", "status", "bop", "flags")
            widths = (210, 150, 60, 70, 110, 110, 70, 110, 60, 200)
        left = ("name", "id", "status", "flags", "bop")
        tree = ttk.Treeview(fr, columns=cols, show="headings", height=11, selectmode="extended")
        for k, w in zip(cols, widths):
            tree.column(k, width=w, anchor="w" if k in left else ("center" if k == "cls" else "e"))
        tree.tag_configure("odd", background="#f6f8fa")
        tree.tag_configure("ok", foreground="#1a7f37")
        tree.tag_configure("warn", foreground="#9a6700")
        tree.tag_configure("bad", foreground="#cf222e")
        tree.tag_configure("dim", foreground="#6e7781")
        sbar = ttk.Scrollbar(fr, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sbar.set)
        tree.grid(row=1, column=0, sticky="nsew")
        sbar.grid(row=1, column=1, sticky="ns")
        s["tree"] = tree

        def fmt_t(row, i):
            return "" if i >= len(row["times"]) or row["times"][i] is None else f"{row['times'][i]:.3f}"

        def sort_by(k):
            col, rev = s["sort"]
            s["sort"] = (k, not rev if k == col else False)
            render()

        def render(*_):
            c = cfg()
            names = {"name": "Car", "id": "Folder id", "cls": "Class", "gap": "Gap %",
                     "t1": (c["track1"].strip() or "track 1") + " (median s)",
                     "t2": (c["track2"].strip() or "track 2") + " (median s)",
                     "var": "Var %", "status": "Status", "bop": "BoP", "flags": "Flags"}
            col, rev = s["sort"]
            for k in cols:
                tree.heading(k, text=names[k] + ((" v" if rev else " ^") if k == col else ""),
                             command=lambda k=k: sort_by(k))
            text, sf = s["filt"].get().strip().lower(), s["stat"].get()

            def val(r):
                if col == "cls":
                    return class_sort_key(r["cls"]) if r["cls"] else None
                if col == "gap":
                    return r["gap"]
                if col in ("t1", "t2"):
                    i = 0 if col == "t1" else 1
                    return r["times"][i] if i < len(r["times"]) else None
                if col == "var":
                    return r.get("variance")
                return str(r.get(col, "")).lower()

            rows = [r for r in s["rows"] if row_matches(kind, r, text, sf)]
            have = sorted((r for r in rows if val(r) is not None), key=val, reverse=rev)
            rows = have + [r for r in rows if val(r) is None]
            selected = set(tree.selection())
            tree.delete(*tree.get_children())
            for n, r in enumerate(rows):
                if local:
                    vals = [r["name"], r["id"], fmt_t(r, 0), fmt_t(r, 1), r["status"]]
                else:
                    vals = [r["name"], r["id"], r["cls"] or "", "" if r["gap"] is None else f"{r['gap']:.2f}",
                            fmt_t(r, 0), fmt_t(r, 1), "" if r.get("variance") is None else f"{r['variance']:.2f}",
                            r["status"], r.get("bop", ""), r["flags"]]
                tags = (status_tag(r["status"]),) + (("odd",) if n % 2 else ())
                tree.insert("", "end", iid=r["id"], values=vals, tags=tags)
            keep_sel = [i for i in selected if tree.exists(i)]
            if keep_sel:
                tree.selection_set(keep_sel)
            total = len(s["rows"])
            if local:
                n_ok = sum(1 for r in s["rows"] if r["status"].startswith("done"))
                n_old = sum(1 for r in s["rows"] if "old settings" in r["status"])
                extra = f" ({n_old} made with old settings)" if n_old else ""
                s["count"].set(f"{len(rows)} shown / {total} cars / {n_ok} done{extra}")
                title = f"Local cars ({n_ok} done)"
            else:
                n_ok = sum(1 for r in s["rows"] if r["cls"])
                s["count"].set(f"{len(rows)} shown / {total} cars / {n_ok} with a server class")
                title = f"Server cars ({n_ok} classed)"
            try:
                sub.tab(fr, text=title)
            except tk.TclError:
                pass

        s["render"] = render
        s["filt"].trace_add("write", render)
        box.bind("<<ComboboxSelected>>", render)

        bar_ = ttk.Frame(fr)
        bar_.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        pbtn(bar_, "Benchmark selected cars", lambda: do_bench_selected(s), accent=True)
        pbtn(bar_, "Redo all tracks for selected", lambda: do_bench_selected(s, True))
        if not local:
            pbtn(bar_, "Apply server classes as tags", lambda: do_download_and_tag())
            pbtn(bar_, "Benchmark cars missing from server", lambda: do_missing())
        def refresh_clicked(local=local):
            cars_refresh(rescan=True)
            if not local:
                live_refresh(force=True)
        ttk.Button(bar_, text="Refresh", command=refresh_clicked).pack(side="right")
        ttk.Button(bar_, text="Clear selection",
                   command=lambda: tree.selection_remove(tree.selection())).pack(side="right", padx=(0, 8))
        ttk.Button(bar_, text="Select all shown",
                   command=lambda: tree.selection_set(tree.get_children())).pack(side="right", padx=(0, 8))
        ttk.Label(fr, textvariable=s["info"], style="Muted.TLabel").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        return s

    local_sec = make_section("local")
    server_sec = make_section("server")
    sub.add(local_sec["frame"], text="Local cars")
    sub.add(server_sec["frame"], text="Server cars")

    def cars_refresh(rescan=False, live=False):
        c = cfg()
        if rescan or state["cars_dir"] != c["ac_dir"]:
            local_sec["count"].set("loading cars...")
            server_sec["count"].set("loading cars...")
            root.update_idletasks()
            skip = bundled_car_id()
            state["cars"] = [x for x in load_car_names(c["ac_dir"]) if x[0] != skip]
            state["cars_dir"] = c["ac_dir"]
        try:
            results = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}
        except Exception:
            results = {}
        tracks = [c["track1"], c["track2"]]
        d = cond.load_any()
        local_sec["rows"] = build_rows(state["cars"], results, tracks, profile=d["profile"] if d else None)
        server_sec["rows"] = load_cloud_rows(state["cars"], state["server_by_id"], tracks)
        local_sec["info"].set(
            "Lap times measured on this PC (lap_results.json). The app only measures; after you upload, the server "
            "decides each car's class (see Server cars). Selected cars run on every track, even if already done."
            if d else "Benchmark conditions not downloaded yet, so no times can be shown: "
                      "press Refresh on the Benchmark tab.")
        if state["live_busy"]:
            server_sec["info"].set("Asking the server ... " + state["live_msg"])
        elif state["live_ok"]:
            server_sec["info"].set(f"Live from the server at {state['server_stamp']}: {state['live_found']} of your "
                                   f"{len(state['cars'])} cars are known to it. Only your installed cars are requested "
                                   "and nothing is saved to disk.")
        elif state["live_error"]:
            server_sec["info"].set("Live data unavailable: " + state["live_error"] + "  (press Refresh to retry)")
        else:
            server_sec["info"].set("Server data not loaded yet. Press Refresh.")
        local_sec["render"]()
        server_sec["render"]()

    hooks.append(cars_refresh)

    def live_refresh(force=False, max_age=60):
        """Fetch live data for the installed cars from the server on a worker thread (never blocks the window)."""
        import time as _t
        c = cfg()
        if state["live_busy"] or not c["cloud_url"].strip() or not c["ac_dir"].strip():
            return
        if not force and state["live_ok"] and _t.time() - state["live_at"] < max_age:
            return
        if not state["cars"] or state["cars_dir"] != c["ac_dir"]:
            cars_refresh(rescan=True)
        ids = [x[0] for x in state["cars"]]
        if not ids:
            return
        state["live_busy"], state["live_msg"] = True, "hashing cars ..."
        server_sec["info"].set("Asking the server ...")

        def progress(text):
            def apply():
                state["live_msg"] = text
                if state["live_busy"]:
                    server_sec["count"].set(text)
            root.after(0, apply)

        def done(result, err):
            def apply():
                state["live_busy"] = False
                if result is not None:
                    state["server_by_id"] = result["by_id"]
                    state["live_ok"], state["live_error"] = True, ""
                    state["live_found"] = len(result["by_id"])
                    state["live_at"] = _t.time()
                    state["server_stamp"] = datetime.now().strftime("%H:%M:%S")
                else:
                    state["live_ok"], state["live_error"] = False, err or "unknown error"
                cars_refresh()
            root.after(0, apply)

        ac_live.fetch_async(c["cloud_url"], cars_dir(c), ids, progress, done)

    # ======== Tab: Benchmark ========
    t1_page, t1 = scroll_tab(nb)

    cnd = ttk.LabelFrame(t1, text="Benchmark conditions (set by the server, read-only)", padding=10)
    cnd.pack(fill="x", pady=(0, 10))
    cond_text = tk.StringVar()
    pbtn(cnd, "Refresh", lambda: refresh_conditions(), side="right")
    ttk.Label(cnd, textvariable=cond_text, wraplength=780, justify="left").pack(side="left", fill="x", expand=True)

    sel = group(t1, "Which cars")
    entry_row(sel, 0, "Only car ids matching (regex)", "include")
    entry_row(sel, 1, "Skip car ids matching (regex)", "exclude")
    rr = ttk.Frame(sel)
    rr.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))
    ttk.Label(rr, text="Cars that already have results:").grid(row=0, column=0, sticky="w", padx=(4, 12))
    ttk.Radiobutton(rr, text="Skip them", variable=vars_["rerun_mode"], value="skip").grid(row=0, column=1, sticky="w")
    ttk.Radiobutton(rr, text="Rerun all selected", variable=vars_["rerun_mode"], value="all").grid(row=0, column=2, sticky="w", padx=12)
    ttk.Radiobutton(rr, text="Rerun only these ids:", variable=vars_["rerun_mode"], value="ids").grid(row=0, column=3, sticky="w")
    ttk.Entry(rr, textvariable=vars_["rerun_ids"], width=30).grid(row=0, column=4, padx=6)
    ttk.Checkbutton(rr, text="Also retry cars that failed before", variable=vars_["retry_failed"]).grid(
        row=1, column=1, columnspan=4, sticky="w", pady=(4, 0))
    entry_row(sel, 3, "Probe car ids (space separated)", "probe_ids")
    ttk.Checkbutton(sel, text="Probe: redo tracks that already have a valid time too (default: only missing/failed tracks)",
                    variable=vars_["probe_all_tracks"]).grid(row=4, column=0, columnspan=3, sticky="w", padx=4, pady=(2, 0))

    opts = group(t1, "Run options")
    nums = ttk.Frame(opts)
    nums.grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(nums, text="Cars per pack").pack(side="left")
    ttk.Spinbox(nums, from_=1, to=30, width=4, textvariable=vars_["batch"]).pack(side="left", padx=6)
    ttk.Label(nums, style="Muted.TLabel", wraplength=640, justify="left",
              text="A pack runs on BOTH tracks before the next pack. 1 = cleanest baseline (one car on track); "
                   "more is faster but cars share the track (the server limits how many).").pack(side="left", padx=8)

    def do_probe():
        c = need_bench()
        if c and need("probe_ids"):
            run_with_conditions(lambda: probe_cmd(cfg()), graceful=True)

    def do_bench(dry=False):
        c = need_bench()
        if c:
            run_with_conditions(lambda: bench_cmd(cfg(), ["--dry-run"] if dry else []), graceful=True)

    bf = ttk.Frame(t1)
    bf.pack(fill="x")
    pbtn(bf, "Start benchmark", do_bench, accent=True)
    pbtn(bf, "Dry run (count jobs)", lambda: do_bench(True))
    pbtn(bf, "Probe cars", do_probe)

    upg = group(t1, "Uploading your results")
    ttk.Checkbutton(upg, text="Upload each pack's times automatically as soon as its cars have finished (needs registration)",
                    variable=vars_["auto_upload"]).grid(row=0, column=0, columnspan=3, sticky="w", padx=4)
    upr = ttk.Frame(upg)
    upr.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
    pbtn(upr, "Upload my results (backup)", lambda: do_cloud("upload"))
    ttk.Checkbutton(upg, text="Include results benchmarked before the server update (re-checks the vanilla tracks first)",
                    variable=vars_["cloud_attest"]).grid(row=2, column=0, columnspan=3, sticky="w", padx=4, pady=(6, 0))
    ttk.Label(upg, justify="left", style="Muted.TLabel", text=(
        "A pack is the cars that ran together (one car when 'Cars per pack' is 1). The server recomputes every score and rejects what\n"
        "does not validate, and its classes for those cars appear in the log. If an automatic upload fails, the times stay saved: the\n"
        "button sends everything that has not been uploaded yet.")
              ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))

    def refresh_conditions(quiet=False):
        c = cfg()
        if not c["cloud_url"].strip():
            if not quiet:
                messagebox.showwarning("Server", "Fill in the server address on the Setup tab first.")
            return
        run(conditions_cmd(c), quiet=quiet)

    def update_conditions_panel():
        d = cond.load_any()
        if not d:
            cond_text.set("Not downloaded yet. They are fetched from the server automatically before every "
                          "benchmark, check and upload (press Refresh to fetch now).")
            return
        try:
            import ac_baseline
            ac_baseline.reload()
            detail = ac_baseline.describe()
        except cond.ConditionsUnavailable as e:
            detail = "PROBLEM: " + str(e)
        t = cond.fetched_at()
        when = datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M") if t else "?"
        cond_text.set(f"{detail}\nServer version {d['version']}, fetched {when}. Up to {d['max_batch']} cars per pack. "
                      f"Submissions {'open' if d['accepting_submissions'] else 'CLOSED'}.")

    def conditions_hook():
        cmd = state.get("last_cmd") or []
        if cmd and cmd[0] == "ac_conditions.py":
            update_conditions_panel()

    def upload_hook():
        """After an upload the server has new classes for those cars: read them live."""
        cmd = state.get("last_cmd") or []
        if cmd and cmd[0] == "ac_cloud.py" and "upload" in cmd and state.get("last_rc") == 0:
            live_refresh(force=True)

    def purge_hook():
        """After the tag step (or a failed download) remove the downloaded ratings from disk."""
        if not state["purge_pending"]:
            return
        cmd = state.get("last_cmd") or []
        name = cmd[0] if cmd else ""
        if name == "ac_tag_writer.py" or (name == "ac_cloud.py" and state.get("last_rc") != 0):
            state["purge_pending"] = False
            purge_downloaded()
            write("Downloaded ratings removed from disk (kept in memory for the Server cars list).\n")
            cars_refresh()

    def do_missing():
        """Benchmark the installed cars the server has no class for yet (from the live server data)."""
        c = need_bench()
        if not c:
            return
        if not state["live_ok"]:
            messagebox.showinfo("Server", "No live server data yet. Press Refresh on the Server cars list first"
                                          f"{(': ' + state['live_error']) if state['live_error'] else '.'}")
            return
        skip = bundled_car_id()
        ids = [x[0] for x in state["cars"]
               if x[0] != skip and not (state["server_by_id"].get(x[0]) or {}).get("class")]
        if not ids:
            messagebox.showinfo("Server", "Nothing to benchmark: the server has a class for every car you have installed.")
            return
        if len(ids) > 20 and not messagebox.askyesno("Server", f"{len(ids)} cars have no server class yet. Benchmark them all?"):
            return
        todo = HERE / "cloud_missing_run.txt"
        todo.write_text("\n".join(ids) + "\n", encoding="utf-8")
        run_with_conditions(lambda: bench_cmd(cfg(), ["--ids-file", str(todo)]), graceful=True)

    def refresh_setup():
        """The Setup checklist: AC folder, required files, server registration, and what to do next."""
        c = cfg()
        ac = c["ac_dir"].strip()
        have_ac = bool(ac) and (Path(ac) / "acs.exe").exists()
        ac_stat.set(("\u2714 " if have_ac else "\u2718 ") +
                    ("Assetto Corsa folder found" if have_ac else
                     "Assetto Corsa folder not set or acs.exe not found there (set it below)"))
        car_code = lua_code = None
        if have_ac:
            try:
                car_code, car_txt = bundled_car_state(ac)
                lua_code, lua_txt = bundled_lua_state(ac)
            except OSError as e:
                car_txt = lua_txt = f"Could not check ({e})"
        else:
            car_txt = lua_txt = "Cannot check until the Assetto Corsa folder is set"
        car_stat.set(("\u2714 " if car_code == "ok" else "\u2718 ") + car_txt)
        lua_stat.set(("\u2714 " if lua_code == "ok" else "\u2718 ") + lua_txt)
        refresh_cloud_status()
        registered = cloud_stat.get().startswith("Registered")
        if not have_ac:
            nxt = "Next: set the Assetto Corsa folder"
        elif car_code != "ok" or lua_code != "ok":
            nxt = "Next: press 'Install / update required files'"
        elif not c["cloud_url"].strip():
            nxt = "Next: enter the server address"
        elif not registered:
            nxt = "Next: enter your name and invite code and press Register (or sign in with a link code from another device)"
        else:
            nxt = "Setup is complete. Next: step 2, Vanilla check"
        next_step.set(nxt)
        return nxt.startswith("Setup is complete")

    hooks.append(lambda: refresh_cloud_status())
    hooks.append(lambda: refresh_setup())
    hooks.append(purge_hook)
    hooks.append(upload_hook)
    hooks.append(conditions_hook)
    refresh_cloud_status()

    # tab order follows the workflow: set up, check the tracks, run and upload, then the cars and their classes
    for page, title in ((ts_page, "1. Setup"), (tv_page, "2. Vanilla check"), (t1_page, "3. Benchmark"),
                        (tc, "4. Cars & ratings")):
        nb.add(page, text=title)

    def tab_changed(_e=None):
        if nb.select() == str(ts_page):
            refresh_setup()
        if nb.select() == str(tc):
            cars_refresh()
            live_refresh()          # only if the last answer is older than a minute

    nb.bind("<<NotebookTabChanged>>", tab_changed)

    # ======== bottom bar ========
    bar = ttk.Frame(root, padding=(10, 4))
    bar.pack(side="bottom", fill="x")
    nb.pack(fill="both", expand=True, padx=10, pady=(10, 6))

    log_btn = ttk.Button(bar, text="Show log", command=toggle_log)
    log_btn.pack(side="right")
    stop_btn = ttk.Button(bar, text="Stop", command=stop, state="disabled")
    stop_btn.pack(side="left")
    progress = ttk.Progressbar(bar, mode="indeterminate", length=90)
    progress.pack(side="left", padx=10)
    ttk.Label(bar, textvariable=status, style="Bold.TLabel", width=12).pack(side="left")
    ttk.Label(bar, textvariable=last_line, style="Muted.TLabel").pack(side="left", fill="x", expand=True, padx=(6, 10))

    def on_close():
        if state["proc"] and not messagebox.askyesno("Quit", "A job is running. Stop it and quit?"):
            return
        if state["proc"]:
            stop()
        purge_downloaded()
        save_cfg()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    update_conditions_panel()
    if refresh_setup():
        nb.select(tv_page)         # setup is done: start at step 2
    else:
        nb.select(ts_page)         # first run or something missing: start at step 1
    if cfg()["cloud_url"].strip():
        root.after(400, lambda: refresh_conditions(quiet=True))
        root.after(1500, lambda: live_refresh(force=True))
    purge_downloaded()  # never leave downloaded server ratings lying around between sessions
    write("Ready.\n")
    poll()
    root.mainloop()


def script_command(cmd):
    """Command line that runs one of the app's scripts (cmd = ["ac_lap_bench.py", args...]).
    From source that is python -u script.py. In the single exe there are no script files: the exe starts itself
    with --ac-run and runs the embedded module (see run_embedded_script)."""
    if ac_paths.FROZEN:
        return [ac_paths.app_executable(), "--ac-run", *cmd]
    return [sys.executable, "-u", *cmd]


def script_env():
    # the job processes must keep their settings and results in the same folder as this window
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", PYTHONUTF8="1", AC_BENCH_DATA=str(ac_paths.DATA))
    if ac_paths.FROZEN and hasattr(sys, "_MEIPASS"):
        # a PyInstaller one-file exe starting itself as an independent process must unpack its own copy of the embedded files
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def run_embedded_script(argv):
    """argv = ["ac_lap_bench.py", args...]: run that embedded module as __main__ (used by the exe's child processes)."""
    import runpy
    for name, fd in (("stdout", 1), ("stderr", 2)):      # a windowed exe may start without console streams
        if getattr(sys, name) is None:
            try:
                setattr(sys, name, open(fd, "w", encoding="utf-8", buffering=1, closefd=False))
            except OSError:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    ac_paths.utf8_output()      # after the stream repair above: the log reads UTF-8
    script, rest = argv[0], argv[1:]
    sys.argv = [script, *rest]
    name = Path(script).stem
    # Compiled modules (Nuitka) have no code object, so runpy cannot run them: import the module and call its main().
    # Source and PyInstaller builds keep using runpy, which runs the module exactly as "python script.py" would.
    compiled = "__compiled__" in globals() or (ac_paths.FROZEN and not hasattr(sys, "_MEIPASS"))
    try:
        if compiled:
            import importlib
            main_fn = getattr(importlib.import_module(name), "main", None)
            if main_fn is None:
                print(f"{script} has no main() to run", file=sys.stderr)
                return 1
            result = main_fn()
            return result if isinstance(result, int) else 0
        runpy.run_module(name, run_name="__main__", alter_sys=True)
    except SystemExit as e:
        code = e.code
        return code if isinstance(code, int) else (0 if code is None else (print(code, file=sys.stderr) or 1))
    return 0


def selfcheck():
    """--ac-selfcheck: confirm this build carries everything it needs (used by the CI build; exit 0 = fine).
    Checks the embedded race template, benchmark car and Lua logger, that every module the app starts as a job is
    importable, and that the folder for settings and results is writable."""
    import importlib
    for name, fd in (("stdout", 1), ("stderr", 2)):
        if getattr(sys, name) is None:
            try:
                setattr(sys, name, open(fd, "w", encoding="utf-8", buffering=1, closefd=False))
            except OSError:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    bad = []

    def check(ok, text):
        print(("OK    " if ok else "FAIL  ") + text)
        if not ok:
            bad.append(text)

    check(TEMPLATE.is_file(), f"embedded race template: {TEMPLATE}")
    cars = [p for p in BUNDLED_CAR_DIR.iterdir() if p.is_dir()] if BUNDLED_CAR_DIR.is_dir() else []
    check(len(cars) == 1 and ((cars[0] / "data").exists() or (cars[0] / "data.acd").exists()),
          f"embedded benchmark car: {[p.name for p in cars]}")
    lua = sorted(p.name for p in BUNDLED_LUA_APP.iterdir()) if BUNDLED_LUA_APP.is_dir() else []
    check("ac_bench.lua" in lua and "manifest.ini" in lua, f"embedded Lua logger: {lua}")
    for mod in ("ac_paths", "ac_lap_bench", "ac_cloud", "ac_conditions", "ac_live", "ac_tag_writer", "ac_track_check",
                "ac_baseline", "ac_rating", "ac_carid", "ac_car_classifier", "ac_input", "ac_controls", "ac_classify_laps",
                "ac_grid_builder", "tkinter"):
        try:
            importlib.import_module(mod)
            ok = True
        except cond.ConditionsUnavailable:
            ok = True     # imported fine; it only wants the server's conditions at run time
        except Exception as e:
            ok = False
            print("      " + type(e).__name__ + ": " + str(e))
        check(ok, f"module {mod}")
    try:      # start a job the way the buttons do (the app running a copy of itself) and read its output
        job = subprocess.run(script_command(["ac_paths.py"]), cwd=HERE, capture_output=True, text=True, timeout=120,
                             env=script_env(), creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        check(job.returncode == 0 and "DATA=" in job.stdout,
              f"the app can start a job from inside itself: {script_command(['ac_paths.py'])[0]}"
              + ("" if job.returncode == 0 else f" (exit {job.returncode}: {(job.stderr or job.stdout).strip()[:200]})"))
    except Exception as e:
        check(False, f"the app cannot start a job from inside itself: {type(e).__name__}: {e}")
    try:
        probe = HERE / ".selfcheck"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        check(True, f"settings and results folder is writable: {HERE}")
    except OSError as e:
        check(False, f"settings and results folder is not writable: {HERE} ({e})")
    print("SELFCHECK " + ("FAILED" if bad else "PASSED"))
    return 1 if bad else 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--ac-run":
        sys.exit(run_embedded_script(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "--ac-selfcheck":
        sys.exit(selfcheck())
    main()
