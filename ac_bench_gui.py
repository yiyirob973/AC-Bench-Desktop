#!/usr/bin/env python3
"""
Simple GUI for the AC car benchmark tools. Keep this file in the same folder as
ac_lap_bench.py, ac_classify_laps.py, ac_car_classifier.py, ac_grid_builder.py
and ac_tag_writer.py. Results (lap_results.json, car_classes.csv, grid.csv) are
saved in that folder. Settings are remembered in ac_bench_gui.json.

Run:  python ac_bench_gui.py        (tkinter ships with the python.org installer)
"""
import json, os, queue, subprocess, sys, threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ac_car_classifier import class_label, class_sort_key   # noqa: E402
from ac_baseline import TRACKS as BL_TRACKS, PROFILE_ID, describe as bl_describe   # noqa: E402
import ac_rating as rating   # noqa: E402
CFG_FILE = HERE / "ac_bench_gui.json"
STOP_FILE = HERE / "STOP"
RESULTS = HERE / "lap_results.json"
CLASSES = HERE / "car_classes.csv"
CLOUD_CLASSES = HERE / "car_classes_cloud.csv"
CLOUD_MISSING = HERE / "cloud_missing.txt"
CLOUD_CFG = HERE / "cloud_config.json"
ESTIMATE = HERE / "car_classes_estimate.csv"
GRID = HERE / "grid.csv"

DEFAULTS = {
    "ac_dir": r"C:\Program Files (x86)\Steam\steamapps\common\assettocorsa",
    "docs_dir": str(Path.home() / "Documents" / "Assetto Corsa"),
    "template": "", "group_by": "",
    "track1": BL_TRACKS[0], "track2": BL_TRACKS[1],      # hard-coded baseline tracks (not editable)
    "batch": 1, "include": "", "exclude": "",
    "retry_failed": False, "rerun_mode": "skip", "rerun_ids": "", "probe_ids": "",
    "auto_drive": False, "click_delay": 25, "press_key": "",
    "reference": str(HERE / "track_reference.json"), "ignore_ui": False, "skip_vanilla": False,
    "cloud_url": "", "cloud_name": "", "cloud_invite": "", "cloud_prov": False, "cloud_attest": True, "class_source": "local",
    "class_gap": 2.0, "allow_partial": False, "min_class_size": 3, "fixed_classes": 0,
    "tie_zone": 0.10, "bop_sens": "",
    "grid_size": 20, "grid_gap": 2.5, "grid_class": "", "grid_around": "",
    "grid_tightest": False, "grid_include": "", "grid_exclude": "", "grid_seed": "",
    "tag_prefix": "#grid-class-", "tag_exclude": "",
}


# ---------- command builders (pure functions, no GUI) ----------
def cars_dir(c):
    return str(Path(c["ac_dir"]) / "content" / "cars")


def bench_cmd(c, extra=()):
    cmd = ["ac_lap_bench.py", "--ac-dir", c["ac_dir"], "--docs-dir", c["docs_dir"],
           "--template", c["template"], "--batch", str(c["batch"]),
           "--results", str(RESULTS), "--stop-file", str(STOP_FILE)]
    if c["group_by"]:
        cmd += ["--group-by", c["group_by"]]
    if c["include"]:
        cmd += ["--include", c["include"]]
    if c["exclude"]:
        cmd += ["--exclude", c["exclude"]]
    if c["retry_failed"]:
        cmd.append("--retry-failed")
    cmd += ["--reference", c["reference"]]
    if c["ignore_ui"]:
        cmd.append("--ignore-ui-files")
    if c["skip_vanilla"]:
        cmd.append("--skip-track-check")
    if c["auto_drive"]:
        cmd += ["--click-drive", "--click-delay", str(c["click_delay"])]
    if c["auto_drive"] and str(c["press_key"]).strip():
        cmd += ["--press-key", str(c["press_key"]).strip()]
    cmd += list(extra)
    # variable-length options go last
    if c["rerun_mode"] == "all":
        cmd.append("--rerun")
    elif c["rerun_mode"] == "ids" and c["rerun_ids"].split():
        cmd += ["--rerun", *c["rerun_ids"].split()]
    return cmd


def classes_path(c):
    """Class CSV the grid builder and tag writer read: your own results or the cloud classes."""
    return CLOUD_CLASSES if c.get("class_source") == "cloud" else CLASSES


def cloud_cmd(c, action):
    cmd = ["ac_cloud.py"]
    if str(c["cloud_url"]).strip():
        cmd += ["--server", str(c["cloud_url"]).strip()]
    if action == "ping":
        return cmd + ["ping"]
    if action == "register":
        return cmd + ["register", "--invite", str(c["cloud_invite"]).strip(), "--name", str(c["cloud_name"]).strip()]
    cmd += [action, "--cars-dir", cars_dir(c)]
    if action == "sync" and c["cloud_prov"]:
        cmd.append("--include-provisional")
    if action == "upload" and c.get("cloud_attest"):
        cmd.append("--attest-legacy")
    return cmd


def verify_cmd(c, create=False):
    cmd = ["ac_track_check.py", "create" if create else "verify", "--ac-dir", c["ac_dir"],
           "--reference", c["reference"]]
    if c["ignore_ui"] and not create:
        cmd.append("--ignore-ui-files")
    return cmd + ["--tracks", *[t.strip() for t in (c["track1"], c["track2"]) if t.strip()]]


def probe_cmd(c, ids=None):
    ids = list(ids) if ids is not None else c["probe_ids"].split()
    return bench_cmd(c, ["--probe", *ids])


def classify_cmd(c):
    cmd = ["ac_classify_laps.py", str(RESULTS), cars_dir(c),
           "--class-gap", str(c["class_gap"]), "--out", str(CLASSES),
           "--min-class-size", str(c["min_class_size"]), "--tie-zone", str(c["tie_zone"])]
    if int(c["fixed_classes"]) > 0:
        cmd += ["--classes", str(int(c["fixed_classes"]))]
    if str(c["bop_sens"]).strip():
        cmd += ["--bop-sensitivity", str(c["bop_sens"]).strip()]
    if c["allow_partial"]:
        cmd.append("--allow-partial")
    return cmd


def estimate_cmd(c):
    return ["ac_car_classifier.py", cars_dir(c), "--class-gap", str(c["class_gap"]),
            "--out", str(ESTIMATE)]


def grid_cmd(c, list_only=False):
    cmd = ["ac_grid_builder.py", str(classes_path(c))]
    if list_only:
        return cmd + ["--list-classes"]
    cmd += ["--size", str(c["grid_size"]), "--max-gap", str(c["grid_gap"]), "--out", str(GRID)]
    if c["grid_class"].strip():
        for n in c["grid_class"].replace(",", " ").split():
            cmd += ["--class", n]
    if c["grid_around"]:
        cmd += ["--around", c["grid_around"]]
    if c["grid_tightest"]:
        cmd.append("--tightest")
    if c["grid_include"]:
        cmd += ["--include", c["grid_include"]]
    if c["grid_exclude"]:
        cmd += ["--exclude", c["grid_exclude"]]
    if str(c["grid_seed"]).strip():
        cmd += ["--seed", str(c["grid_seed"]).strip()]
    return cmd


def tag_cmd(c, mode):
    """mode: dry | apply | untag | restore"""
    if mode == "restore":
        return ["ac_tag_writer.py", cars_dir(c), "--restore"]
    cmd = ["ac_tag_writer.py", cars_dir(c), str(classes_path(c)), "--prefix", c["tag_prefix"]]
    if c["tag_exclude"]:
        cmd += ["--exclude", c["tag_exclude"]]
    if mode in ("apply", "untag"):
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


def build_rows(cars, results, tracks, class_gap, min_size=3, fixed_k=0):
    """Rows for the car list. 'rated' = a valid time on every track. Classes, gaps and flags come from
    ac_rating.rate: median lap score, mean % delta over the tracks, natural class borders."""
    tracks = [t.strip() for t in tracks if t and t.strip()]
    info, _ = rating.rate(results, tracks, class_gap=class_gap, min_size=min_size, fixed_k=fixed_k)
    rows = []
    for cid, name in cars:
        r = results.get(cid, {})
        times, nok, failed = [], 0, False
        for t in tracks:
            e = r.get(t, {})
            ms = rating.lap_score(e)[0] if e.get("status") == "ok" else None
            times.append(None if ms is None else ms / 1000)
            nok += 1 if ms is not None else 0
            failed = failed or e.get("status") == "failed"
        if tracks and nok == len(tracks):
            old = any(r.get(t, {}).get("profile") != PROFILE_ID for t in tracks)
            status = "rated (old settings)" if old else "rated"
        elif nok:
            status = f"partial {nok}/{len(tracks)}"
        else:
            status = "failed" if failed else "not run"
        row = {"id": cid, "name": name, "status": status, "times": times, "gap": None, "cls": None, "flags": ""}
        c = info.get(cid)
        if c and status.startswith("rated"):
            row.update(gap=c["gap"], cls=c["cls"], flags=c["flags_text"])
        rows.append(row)
    return rows


# ---------- GUI ----------
def main():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, scrolledtext

    root = tk.Tk()
    root.title("AC Car Benchmark")
    root.geometry("920x840")

    saved = {}
    if CFG_FILE.exists():
        try:
            saved = json.loads(CFG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    vars_ = {}
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
                out[k] = DEFAULTS[k]       # blank/invalid number field
        out["track1"], out["track2"] = BL_TRACKS[0], BL_TRACKS[1]     # baseline tracks are fixed
        return out

    def save_cfg():
        CFG_FILE.write_text(json.dumps(cfg(), indent=1), encoding="utf-8")

    # --- log + process runner ---
    log = scrolledtext.ScrolledText(root, height=14, state="disabled", font=("Consolas", 9))
    status = tk.StringVar(value="Idle")
    q = queue.Queue()
    state = {"proc": None, "graceful": False, "on_done": None,
             "cars": [], "cars_dir": None, "rows": [], "sort": ("gap", False)}
    hooks = []      # called after every finished job (e.g. refresh the car list)
    run_buttons = []

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
                    for h in hooks:
                        h()
                    cb, state["on_done"] = state["on_done"], None
                    if cb and item[1] == 0:
                        cb()
                else:
                    write(item)
        except queue.Empty:
            pass
        root.after(150, poll)

    def run(cmd, graceful=False, on_done=None):
        if state["proc"]:
            return
        save_cfg()
        if STOP_FILE.exists():
            STOP_FILE.unlink()
        write("\n$ " + " ".join(f'"{a}"' if " " in a else a for a in cmd) + "\n")
        state["last_cmd"] = cmd
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            proc = subprocess.Popen([sys.executable, "-u", *cmd], cwd=HERE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                    errors="replace", creationflags=flags,
                                    env=dict(os.environ, PYTHONUNBUFFERED="1"))
        except Exception as e:
            messagebox.showerror("Could not start", str(e))
            return
        state.update(proc=proc, graceful=graceful, on_done=on_done)
        set_busy(True)
        threading.Thread(target=reader, args=(proc,), daemon=True).start()

    def stop():
        p = state["proc"]
        if not p:
            return
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

    def need_bench():
        c = need("ac_dir", "docs_dir", "template", "track1")
        if not c:
            return None
        if not (Path(c["ac_dir"]) / "acs.exe").exists():
            messagebox.showwarning("AC folder", "acs.exe not found in the Assetto Corsa folder.")
            return None
        if not Path(c["template"]).exists():
            messagebox.showwarning("Template", "Template race.ini not found.")
            return None
        return c

    def need_csv(path):
        if not Path(path).exists():
            messagebox.showwarning("Missing file", f"{path.name} not found yet. Run the earlier step first.")
            return False
        return True

    # --- widgets ---
    def entry_row(parent, r, label, key, browse=None, width=60):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", padx=6, pady=3)
        ttk.Entry(parent, textvariable=vars_[key], width=width).grid(row=r, column=1, sticky="ew", pady=3)
        if browse == "dir":
            cmd = lambda: vars_[key].set(filedialog.askdirectory(initialdir=vars_[key].get() or None) or vars_[key].get())
        elif browse == "file":
            cmd = lambda: vars_[key].set(filedialog.askopenfilename() or vars_[key].get())
        else:
            return
        ttk.Button(parent, text="Browse", command=cmd).grid(row=r, column=2, padx=6)

    def btn(parent, text, command, r, c, span=1):
        b = ttk.Button(parent, text=text, command=command)
        b.grid(row=r, column=c, columnspan=span, padx=6, pady=6, sticky="w")
        run_buttons.append(b)
        return b

    nb = ttk.Notebook(root)

    # Tab 1: benchmark
    t1 = ttk.Frame(nb)
    t1.columnconfigure(1, weight=1)
    entry_row(t1, 0, "Assetto Corsa folder", "ac_dir", "dir")
    entry_row(t1, 1, "Documents/Assetto Corsa", "docs_dir", "dir")
    entry_row(t1, 2, "Template race.ini", "template", "file")
    entry_row(t1, 3, "Batch grouping CSV (optional)", "group_by", "file")
    ttk.Label(t1, text="Fixed baseline (set in the tool, not editable): " + bl_describe(),
              wraplength=800, justify="left").grid(row=4, column=0, columnspan=3, sticky="w", padx=6, pady=3)
    nums = ttk.Frame(t1)
    nums.grid(row=6, column=0, columnspan=3, sticky="w", padx=6, pady=3)
    ttk.Label(nums, text="Cars per pack").pack(side="left")
    ttk.Spinbox(nums, from_=1, to=30, width=4, textvariable=vars_["batch"]).pack(side="left", padx=4)
    ttk.Label(nums, text="A pack runs on BOTH tracks before the next pack. 1 = cleanest baseline (one car on track); more is faster but cars share the track"
              ).pack(side="left", padx=8)
    entry_row(t1, 7, "Only car ids matching (regex)", "include")
    entry_row(t1, 8, "Skip car ids matching (regex)", "exclude")
    rr = ttk.LabelFrame(t1, text="Cars that already have results")
    rr.grid(row=9, column=0, columnspan=3, sticky="ew", padx=6, pady=4)
    ttk.Radiobutton(rr, text="Skip them (default)", variable=vars_["rerun_mode"], value="skip").grid(row=0, column=0, sticky="w")
    ttk.Radiobutton(rr, text="Rerun all selected", variable=vars_["rerun_mode"], value="all").grid(row=0, column=1, sticky="w", padx=12)
    ttk.Radiobutton(rr, text="Rerun only these ids:", variable=vars_["rerun_mode"], value="ids").grid(row=0, column=2, sticky="w")
    ttk.Entry(rr, textvariable=vars_["rerun_ids"], width=34).grid(row=0, column=3, padx=6, pady=3)
    ttk.Checkbutton(rr, text="Also retry cars that failed before", variable=vars_["retry_failed"]).grid(row=1, column=0, columnspan=4, sticky="w")
    entry_row(t1, 10, "Probe car ids (space separated)", "probe_ids")

    def do_calibrate():
        messagebox.showinfo("Calibrate Drive button",
            "1. Start AC (windowed/borderless) until the Drive menu shows, e.g. from Content Manager.\n"
            "2. Hover the mouse over the Drive button.\n"
            "3. Press F8.\n\nClick OK, then do those steps (waits up to 3 minutes).")
        run(["ac_input.py", "calibrate"])

    def do_probe():
        c = need_bench()
        if c and need("probe_ids"):
            run(probe_cmd(c), graceful=True)

    def do_bench(dry=False):
        c = need_bench()
        if c:
            run(bench_cmd(c, ["--dry-run"] if dry else []), graceful=True)

    af = ttk.LabelFrame(t1, text="Start races automatically (bypass the Drive menu)")
    af.grid(row=11, column=0, columnspan=3, sticky="ew", padx=6, pady=4)
    ttk.Checkbutton(af, text="Auto-click the Drive button", variable=vars_["auto_drive"]).grid(row=0, column=0, sticky="w")
    ttk.Label(af, text="first try after (s)").grid(row=0, column=1, padx=(12, 2))
    ttk.Spinbox(af, from_=5, to=300, width=5, textvariable=vars_["click_delay"]).grid(row=0, column=2)
    ttk.Label(af, text="also press key").grid(row=0, column=3, padx=(12, 2))
    ttk.Entry(af, textvariable=vars_["press_key"], width=8).grid(row=0, column=4)
    btn(af, "Calibrate Drive button", do_calibrate, 1, 0, 2)
    btn(af, "Test click", lambda: run(["ac_input.py", "click"]), 1, 2, 3)

    bf = ttk.Frame(t1)
    bf.grid(row=12, column=0, columnspan=3, sticky="w")
    btn(bf, "Probe cars", do_probe, 0, 0)
    btn(bf, "Dry run (count jobs)", lambda: do_bench(True), 0, 1)
    btn(bf, "Start benchmark", do_bench, 0, 2)
    nb.add(t1, text="1  Benchmark")

    # Tab: cars list
    tc = ttk.Frame(nb)
    tc.columnconfigure(0, weight=1)
    tc.rowconfigure(1, weight=1)
    top = ttk.Frame(tc)
    top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=4)
    filt, stat_f, count = tk.StringVar(), tk.StringVar(value="All"), tk.StringVar()
    ttk.Label(top, text="Filter").pack(side="left")
    ttk.Entry(top, textvariable=filt, width=24).pack(side="left", padx=(4, 10))
    stat_box = ttk.Combobox(top, textvariable=stat_f, state="readonly", width=10,
                            values=["All", "Rated", "Not rated", "Partial", "Failed", "Old settings", "Flagged"])
    stat_box.pack(side="left")
    ttk.Label(top, textvariable=count).pack(side="right")

    cols = ("name", "id", "cls", "gap", "t1", "t2", "status", "flags")
    tree = ttk.Treeview(tc, columns=cols, show="headings", height=11, selectmode="extended")
    for k, w in zip(cols, (200, 150, 50, 60, 100, 100, 110, 230)):
        tree.column(k, width=w, anchor="w" if k in ("name", "id", "status", "flags") else "e")
    sbar = ttk.Scrollbar(tc, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sbar.set)
    tree.grid(row=1, column=0, sticky="nsew", padx=(6, 0))
    sbar.grid(row=1, column=1, sticky="ns")

    def fmt_t(row, i):
        return "" if i >= len(row["times"]) or row["times"][i] is None else f"{row['times'][i]:.3f}"

    def render(*_):
        c = cfg()
        names = {"name": "Car", "id": "Folder id", "cls": "Class", "gap": "Gap %",
                 "t1": (c["track1"].strip() or "track 1") + " (median s)",
                 "t2": (c["track2"].strip() or "track 2") + " (median s)", "status": "Status", "flags": "Flags"}
        col, rev = state["sort"]
        for k, v in names.items():
            tree.heading(k, text=v + ((" v" if rev else " ^") if k == col else ""),
                         command=lambda k=k: sort_by(k))
        text, sf = filt.get().strip().lower(), stat_f.get()

        def keep(r):
            if text and text not in r["id"].lower() and text not in r["name"].lower():
                return False
            s = r["status"]
            return (sf == "All" or (sf == "Rated" and s.startswith("rated"))
                    or (sf == "Not rated" and not s.startswith("rated"))
                    or (sf == "Partial" and s.startswith("partial")) or (sf == "Failed" and s == "failed")
                    or (sf == "Old settings" and "old settings" in s) or (sf == "Flagged" and bool(r["flags"])))

        def val(r):
            if col == "cls":
                return class_sort_key(r["cls"]) if r["cls"] else None
            if col == "gap":
                return r["gap"]
            if col in ("t1", "t2"):
                i = 0 if col == "t1" else 1
                return r["times"][i] if i < len(r["times"]) else None
            return str(r[col]).lower()

        rows = [r for r in state["rows"] if keep(r)]
        have = sorted((r for r in rows if val(r) is not None), key=val, reverse=rev)
        rows = have + [r for r in rows if val(r) is None]
        sel = set(tree.selection())
        tree.delete(*tree.get_children())
        for r in rows:
            tree.insert("", "end", iid=r["id"], values=(
                r["name"], r["id"], r["cls"] or "", "" if r["gap"] is None else f"{r['gap']:.2f}",
                fmt_t(r, 0), fmt_t(r, 1), r["status"], r["flags"]))
        keep_sel = [i for i in sel if tree.exists(i)]
        if keep_sel:
            tree.selection_set(keep_sel)
        n_rated = sum(1 for r in state["rows"] if r["status"].startswith("rated"))
        n_old = sum(1 for r in state["rows"] if "old settings" in r["status"])
        extra = f" ({n_old} made with old settings)" if n_old else ""
        count.set(f"{len(rows)} shown / {len(state['rows'])} cars / {n_rated} rated{extra}")

    def sort_by(k):
        col, rev = state["sort"]
        state["sort"] = (k, not rev if k == col else False)
        render()

    def cars_refresh(rescan=False):
        c = cfg()
        if rescan or state["cars_dir"] != c["ac_dir"]:
            count.set("loading cars...")
            root.update_idletasks()
            state["cars"], state["cars_dir"] = load_car_names(c["ac_dir"]), c["ac_dir"]
        try:
            results = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}
        except Exception:
            results = {}
        state["rows"] = build_rows(state["cars"], results, [c["track1"], c["track2"]], c["class_gap"],
                                   int(c["min_class_size"]), int(c["fixed_classes"]))
        render()

    hooks.append(cars_refresh)
    filt.trace_add("write", render)
    stat_box.bind("<<ComboboxSelected>>", render)

    def do_bench_selected():
        ids = list(tree.selection())
        if not ids:
            messagebox.showinfo("Select cars", "Select one or more cars in the list first.")
            return
        c = need_bench()
        if not c:
            return
        if len(ids) > 20 and not messagebox.askyesno(
                "Many cars", f"{len(ids)} cars selected. They run on every track, even if already rated. Continue?"):
            return
        run(probe_cmd(c, ids), graceful=True)

    cf = ttk.Frame(tc)
    cf.grid(row=2, column=0, columnspan=2, sticky="w", padx=6)
    btn(cf, "Benchmark selected cars", do_bench_selected, 0, 0)
    ttk.Button(cf, text="Select all shown", command=lambda: tree.selection_set(tree.get_children())).grid(row=0, column=1, padx=6)
    ttk.Button(cf, text="Clear selection", command=lambda: tree.selection_remove(tree.selection())).grid(row=0, column=2)
    ttk.Button(cf, text="Refresh", command=lambda: cars_refresh(rescan=True)).grid(row=0, column=3, padx=6)
    ttk.Label(cf, text="Selected cars run on every track, even if already rated.").grid(row=0, column=4, padx=6)
    nb.add(tc, text="2  Cars")

    # Tab 3: classes
    t2 = ttk.Frame(nb)
    t2.columnconfigure(1, weight=1)
    ttk.Label(t2, text="Max spread inside a class (% of lap time)").grid(row=0, column=0, sticky="w", padx=6, pady=6)
    ttk.Spinbox(t2, from_=0.5, to=10, increment=0.5, width=6, textvariable=vars_["class_gap"]).grid(row=0, column=1, sticky="w")
    ttk.Checkbutton(t2, text="Include cars with only some tracks", variable=vars_["allow_partial"]).grid(row=1, column=0, columnspan=2, sticky="w", padx=6)

    def do_classify():
        c = cfg()
        if need_csv(RESULTS):
            run(classify_cmd(c))

    def do_estimate():
        c = need("ac_dir")
        if c:
            def fill():
                if not vars_["group_by"].get():
                    vars_["group_by"].set(str(ESTIMATE))
                    write("Batch grouping CSV set to the estimate file.\n")
            run(estimate_cmd(c), on_done=fill)

    adv = ttk.LabelFrame(t2, text="Class assignment (natural breaks, see grid_dynamics.txt)")
    adv.grid(row=5, column=0, columnspan=2, sticky="ew", padx=6, pady=6)
    ttk.Label(adv, text="Min cars per class").grid(row=0, column=0, sticky="w", padx=4, pady=2)
    ttk.Spinbox(adv, from_=1, to=30, width=5, textvariable=vars_["min_class_size"]).grid(row=0, column=1, sticky="w")
    ttk.Label(adv, text="Force exactly N classes (0 = automatic)").grid(row=1, column=0, sticky="w", padx=4, pady=2)
    ttk.Spinbox(adv, from_=0, to=60, width=5, textvariable=vars_["fixed_classes"]).grid(row=1, column=1, sticky="w")
    ttk.Label(adv, text="Borderline zone (% of lap time)").grid(row=2, column=0, sticky="w", padx=4, pady=2)
    ttk.Spinbox(adv, from_=0.0, to=1.0, increment=0.05, width=5, textvariable=vars_["tie_zone"]).grid(row=2, column=1, sticky="w")
    ttk.Label(adv, text="BoP sensitivity (optional, % lap time per % power-to-weight)").grid(row=3, column=0, sticky="w", padx=4, pady=2)
    ttk.Entry(adv, textvariable=vars_["bop_sens"], width=7).grid(row=3, column=1, sticky="w")
    btn(t2, "Rate cars from lap results", do_classify, 2, 0)
    btn(t2, "Quick estimate from car data (no game, for batch grouping)", do_estimate, 3, 0, 2)
    ttk.Label(t2, text="Writes car_classes.csv next to this program (flags and BoP hints are columns in it).\nThe grid and tag steps read that file.").grid(row=4, column=0, columnspan=2, sticky="w", padx=6, pady=8)
    nb.add(t2, text="3  Classes")

    # Tab 3: grid
    t3 = ttk.Frame(nb)
    t3.columnconfigure(1, weight=1)
    g = ttk.Frame(t3)
    g.grid(row=0, column=0, columnspan=3, sticky="w", padx=6, pady=6)
    ttk.Label(g, text="Cars").pack(side="left")
    ttk.Spinbox(g, from_=2, to=60, width=5, textvariable=vars_["grid_size"]).pack(side="left", padx=(4, 16))
    ttk.Label(g, text="Max spread (%)").pack(side="left")
    ttk.Spinbox(g, from_=0.5, to=20, increment=0.5, width=6, textvariable=vars_["grid_gap"]).pack(side="left", padx=4)
    ttk.Checkbutton(g, text="Tightest possible", variable=vars_["grid_tightest"]).pack(side="left", padx=16)
    entry_row(t3, 1, "Only classes (e.g. A B)", "grid_class")
    entry_row(t3, 2, "Center on car id", "grid_around")
    entry_row(t3, 3, "Only car ids matching (regex)", "grid_include")
    entry_row(t3, 4, "Skip car ids matching (regex)", "grid_exclude")
    entry_row(t3, 5, "Random seed (optional)", "grid_seed", width=12)

    def do_grid():
        if need_csv(classes_path(cfg())):
            run(grid_cmd(cfg()))

    def do_list():
        if need_csv(classes_path(cfg())):
            run(grid_cmd(cfg(), list_only=True))

    gf = ttk.Frame(t3)
    gf.grid(row=6, column=0, columnspan=3, sticky="w")
    btn(gf, "Show classes", do_list, 0, 0)
    btn(gf, "Build grid", do_grid, 0, 1)
    b = ttk.Button(gf, text="Open results folder", command=lambda: os.startfile(HERE) if os.name == "nt" else None)
    b.grid(row=0, column=2, padx=6)
    nb.add(t3, text="4  Grid")

    # Tab 4: tags
    t4 = ttk.Frame(nb)
    t4.columnconfigure(1, weight=1)
    entry_row(t4, 0, "Tag prefix", "tag_prefix", width=30)
    entry_row(t4, 1, "Skip car ids matching (regex)", "tag_exclude")
    ttk.Label(t4, text="Writes class tags into each car's ui_car.json (backups kept as .gridbak).\n"
                       "Skip cars you also race online.").grid(row=2, column=0, columnspan=3, sticky="w", padx=6, pady=4)

    def do_tags(mode):
        c = need("ac_dir", "tag_prefix")
        if not c or (mode != "restore" and not need_csv(classes_path(c))):
            return
        if mode != "dry" and not messagebox.askyesno("Confirm", {
                "apply": "Write tags into car files? Backups are made first.",
                "untag": "Remove this tool's tags from car files?",
                "restore": "Restore every .gridbak backup (discards other edits to those files)?"}[mode]):
            return
        run(tag_cmd(c, mode))

    tf = ttk.Frame(t4)
    tf.grid(row=3, column=0, columnspan=3, sticky="w")
    btn(tf, "Dry run", lambda: do_tags("dry"), 0, 0)
    btn(tf, "Apply tags", lambda: do_tags("apply"), 0, 1)
    btn(tf, "Remove tags", lambda: do_tags("untag"), 0, 2)
    btn(tf, "Restore backups", lambda: do_tags("restore"), 0, 3)
    nb.add(t4, text="5  CM tags")

    # Tab 6: vanilla check
    tv = ttk.Frame(nb)
    tv.columnconfigure(1, weight=1)
    entry_row(tv, 0, "Reference file", "reference", "file")
    ttk.Checkbutton(tv, text="Ignore UI/preview files (they do not affect lap times)",
                    variable=vars_["ignore_ui"]).grid(row=1, column=0, columnspan=3, sticky="w", padx=6)
    ttk.Checkbutton(tv, text="Skip this check when benchmarking (not recommended: ratings may not be comparable)",
                    variable=vars_["skip_vanilla"]).grid(row=2, column=0, columnspan=3, sticky="w", padx=6)
    vstat = tk.StringVar(value="Not checked yet")
    ttk.Label(tv, textvariable=vstat, font=("TkDefaultFont", 10, "bold")).grid(
        row=3, column=0, columnspan=3, sticky="w", padx=6, pady=8)

    def do_verify():
        c = need("ac_dir", "track1")
        if c:
            run(verify_cmd(c))

    def do_create():
        c = need("ac_dir", "track1")
        if c and messagebox.askyesno(
                "Create reference",
                "Only do this on a CLEAN install, right after Steam's 'Verify integrity of game files'.\n"
                "Anything modded in these tracks right now will be treated as vanilla from now on.\n\nContinue?"):
            run(verify_cmd(c, create=True))

    def do_steam():
        try:
            os.startfile("steam://validate/244210")
        except Exception as e:
            messagebox.showinfo("Steam", f"Could not open Steam ({e}).\nIn Steam: Assetto Corsa > Properties > "
                                         "Installed Files > Verify integrity of game files.")

    vf = ttk.Frame(tv)
    vf.grid(row=4, column=0, columnspan=3, sticky="w")
    btn(vf, "Verify tracks now", do_verify, 0, 0)
    btn(vf, "Create reference from this install", do_create, 0, 1)
    ttk.Button(vf, text="Ask Steam to verify game files", command=do_steam).grid(row=0, column=2, padx=6)
    ttk.Label(tv, justify="left", text=(
        "Checks every file of the two fixed benchmark tracks against the reference, including the AI racing\n"
        "lines (ai/*.ai), plus acs.exe, which holds the AI driving code. Benchmarks run this check first and\n"
        "stop on any difference. Make the reference once on a clean install (Steam verify first; Steam does\n"
        "not delete extra files, this check reports them) and use the same reference file on every PC.\n"
        "Race conditions, AI level and aggression are fixed inside the tool. Not covered: cars, CSP itself.")
    ).grid(row=5, column=0, columnspan=3, sticky="w", padx=6, pady=8)

    def vstatus_hook():
        cmd = state.get("last_cmd") or []
        if len(cmd) > 1 and cmd[0] == "ac_track_check.py":
            rc = state.get("last_rc")
            if cmd[1] == "verify":
                vstat.set({0: "Tracks are vanilla: identical to the reference",
                           2: "NOT VANILLA: differs from the reference (see log)",
                           3: "No reference for these tracks yet"}.get(rc, f"Check failed (exit {rc})"))
            else:
                vstat.set("Reference created" if rc == 0 else "Reference creation failed (see log)")

    hooks.append(vstatus_hook)
    nb.add(tv, text="6  Vanilla check")

    # Tab 7: cloud
    tcl = ttk.Frame(nb)
    tcl.columnconfigure(1, weight=1)
    entry_row(tcl, 0, "Server address (https://...)", "cloud_url")
    entry_row(tcl, 1, "Your name (for registering)", "cloud_name", width=30)
    entry_row(tcl, 2, "Invite code (for registering)", "cloud_invite", width=30)
    cloud_stat = tk.StringVar()

    def refresh_cloud_status():
        try:
            j = json.loads(CLOUD_CFG.read_text(encoding="utf-8"))
        except Exception:
            j = {}
        cloud_stat.set(("Registered as " + str(j.get("name", "?"))) if j.get("api_key") else "Not registered yet")

    ttk.Label(tcl, textvariable=cloud_stat, font=("TkDefaultFont", 10, "bold")).grid(
        row=3, column=0, columnspan=3, sticky="w", padx=6, pady=4)
    ttk.Checkbutton(tcl, text="Also use classes backed by a single submission (less reliable)",
                    variable=vars_["cloud_prov"]).grid(row=4, column=0, columnspan=3, sticky="w", padx=6)
    ttk.Checkbutton(tcl, text="Include results benchmarked before the cloud update (re-checks the vanilla tracks first)",
                    variable=vars_["cloud_attest"]).grid(row=8, column=0, columnspan=3, sticky="w", padx=6)

    def do_cloud(action):
        c = cfg()
        if not c["cloud_url"].strip():
            messagebox.showwarning("Cloud", "Fill in the server address first.")
            return
        if action == "register" and not (c["cloud_name"].strip() and c["cloud_invite"].strip()):
            messagebox.showwarning("Cloud", "Registering needs your name and an invite code.")
            return
        if action in ("upload", "sync") and not need("ac_dir"):
            return
        if action == "upload" and c["cloud_attest"]:
            # older results are attested with the CURRENT environment, so verify the tracks right now first
            run(verify_cmd(c), on_done=lambda: run(cloud_cmd(c, "upload")))
            return
        run(cloud_cmd(c, action))

    def do_missing():
        c = need_bench()
        if not c:
            return
        ids = CLOUD_MISSING.read_text(encoding="utf-8").split() if CLOUD_MISSING.exists() else []
        if not ids:
            messagebox.showinfo("Cloud", "Nothing to benchmark. Press 'Download and match classes' first; "
                                         "it lists the cars the cloud has no class for.")
            return
        if len(ids) > 20 and not messagebox.askyesno("Cloud", f"{len(ids)} cars have no cloud class yet. Benchmark them all?"):
            return
        run(bench_cmd(c, ["--ids-file", str(CLOUD_MISSING)]), graceful=True)

    cf2 = ttk.Frame(tcl)
    cf2.grid(row=5, column=0, columnspan=3, sticky="w")
    btn(cf2, "Test connection", lambda: do_cloud("ping"), 0, 0)
    btn(cf2, "Register", lambda: do_cloud("register"), 0, 1)
    btn(cf2, "Upload my results", lambda: do_cloud("upload"), 0, 2)
    btn(cf2, "Download and match classes", lambda: do_cloud("sync"), 0, 3)
    btn(cf2, "Benchmark cars missing from the cloud", do_missing, 1, 0, 3)
    src = ttk.LabelFrame(tcl, text="Which classes should the Grid and CM tags tabs use?")
    src.grid(row=6, column=0, columnspan=3, sticky="ew", padx=6, pady=6)
    ttk.Radiobutton(src, text="My own results (car_classes.csv)", variable=vars_["class_source"], value="local").grid(row=0, column=0, sticky="w")
    ttk.Radiobutton(src, text="Cloud classes (car_classes_cloud.csv)", variable=vars_["class_source"], value="cloud").grid(row=0, column=1, sticky="w", padx=12)
    ttk.Label(tcl, justify="left", text=(
        "Upload sends only results driven on the verified vanilla setup (Vanilla check tab) under the current baseline.\n"
        "The server recomputes every score and rejects what does not validate; reasons appear in the log.\n"
        "Download matches your cars to the cloud by the hash of their physics files (not the folder name), so a\n"
        "modified or updated car is not given another car's class. Cars without a class are listed for benchmarking.")
    ).grid(row=7, column=0, columnspan=3, sticky="w", padx=6, pady=6)

    def cloud_hook():
        refresh_cloud_status()

    hooks.append(cloud_hook)
    refresh_cloud_status()
    nb.add(tcl, text="7  Cloud")

    nb.bind("<<NotebookTabChanged>>",
            lambda e: cars_refresh() if nb.tab(nb.select(), "text").strip().endswith("Cars") else None)
    nb.pack(fill="x", padx=8, pady=6)

    bar = ttk.Frame(root)
    bar.pack(fill="x", padx=8)
    stop_btn = ttk.Button(bar, text="Stop", command=stop, state="disabled")
    stop_btn.pack(side="left")
    ttk.Button(bar, text="Clear log", command=lambda: (log.configure(state="normal"), log.delete("1.0", "end"), log.configure(state="disabled"))).pack(side="left", padx=6)
    ttk.Label(bar, textvariable=status).pack(side="right")
    log.pack(fill="both", expand=True, padx=8, pady=6)

    def on_close():
        if state["proc"] and not messagebox.askyesno("Quit", "A job is running. Stop it and quit?"):
            return
        if state["proc"]:
            stop()
        save_cfg()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    write("Steps: 1 Benchmark (probe first), 2 Cars (ratings, benchmark selected), 3 Classes, 4 Grid, 5 CM tags.\n")
    poll()
    root.mainloop()


if __name__ == "__main__":
    main()
