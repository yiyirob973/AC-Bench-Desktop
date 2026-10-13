#!/usr/bin/env python3
"""
Vanilla track check. Makes sure the tracks used for benchmarking are identical to a
reference, so lap-time ratings made on different AC installations stay comparable.

How it works
  * "create" hashes EVERY file in content/tracks/<track>/ (all layouts) and saves the file
    list + SHA-256 hashes to track_reference.json. Do this once on a clean install:
    first run Steam > Assetto Corsa > Properties > Installed Files > Verify integrity,
    which restores changed or deleted Kunos files. (Steam does NOT remove extra files; this
    tool reports those.)
  * "verify" hashes the current install again and reports files that are modified,
    missing or extra compared with the reference. Exit code 0 = identical.
  * The reference is only as trustworthy as the install it was made from. Copy the same
    track_reference.json to every PC you benchmark on.

The AI is covered in two places: the track folder holds the AI racing lines (ai/*.ai, hashed
like every other file) and acs.exe holds the AI driving code (its hash is stored and compared).
Race conditions are NOT checked here: the runner pins them in ac_baseline.py.

Warnings only (never block): CSP track config files in extension/config/tracks/ for these
tracks.

  python ac_track_check.py create --ac-dir "<AC>" --tracks magione ks_vallelunga/club_circuit --template template_race.ini
  python ac_track_check.py verify --ac-dir "<AC>" --tracks magione ks_vallelunga/club_circuit
Exit codes (verify): 0 identical, 2 different, 3 no reference for the track(s).
"""
import argparse, configparser, hashlib, json, os, sys, time
from pathlib import Path

from ac_baseline import PROFILE_ID

DEFAULT_REF = Path(__file__).resolve().with_name("track_reference.json")
JUNK = {"thumbs.db", "desktop.ini", ".ds_store"}          # OS clutter, never part of the game
COND_SECTIONS = ("DYNAMIC_TRACK", "WEATHER", "TEMPERATURE", "LIGHTING")


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_tree(root):
    files = {}
    for dp, dn, fn in os.walk(root):
        dn.sort()
        for n in sorted(fn):
            if n.lower() in JUNK:
                continue
            p = Path(dp) / n
            files[p.relative_to(root).as_posix()] = [p.stat().st_size, sha256_file(p)]
    return files


def file_info(p):
    return [Path(p).stat().st_size, sha256_file(p)]


def track_ids(specs):
    """'ks_vallelunga/club_circuit' -> 'ks_vallelunga' (the whole track folder is checked)."""
    return list(dict.fromkeys(s.strip().partition("/")[0] for s in specs if s.strip()))


def csp_files(ac, track):
    base = Path(ac) / "extension" / "config" / "tracks"
    out = {}
    if base.is_dir():
        for p in sorted(base.iterdir()):
            if p.is_file() and p.name.lower().startswith(track.lower()):
                out[p.name] = [p.stat().st_size, sha256_file(p)]
    return out


def conditions(template):
    cp = configparser.ConfigParser(strict=False, interpolation=None, delimiters=("=",))
    cp.optionxform = str
    with open(template, encoding="utf-8", errors="ignore") as f:
        cp.read_file(f)
    return {s: dict(cp[s]) for s in COND_SECTIONS if s in cp}


def keep(files, ignore_ui):
    if not ignore_ui:
        return files
    return {p: v for p, v in files.items() if p.split("/")[0].lower() != "ui"}


def diff(ref, cur):
    modified = sorted(p for p in ref if p in cur and ref[p] != cur[p])
    missing = sorted(p for p in ref if p not in cur)
    extra = sorted(p for p in cur if p not in ref)
    return modified, missing, extra


def digest(files):
    h = hashlib.sha256()
    for p in sorted(files):
        h.update(f"{p}\t{files[p][0]}\t{files[p][1]}\n".encode())
    return h.hexdigest()


def load_ref(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def create(ac, specs, ref_path, template=None, say=print):
    ref = load_ref(ref_path) or {"format": 1, "tracks": {}, "csp": {}, "conditions": None}
    for t in track_ids(specs):
        tdir = Path(ac) / "content" / "tracks" / t
        if not tdir.is_dir():
            say(f"{t}: folder not found: {tdir}")
            return 1
        say(f"{t}: hashing every file ...")
        files = hash_tree(tdir)
        ref["tracks"][t] = {"files": files}
        ref["csp"][t] = csp_files(ac, t)
        say(f"{t}: {len(files)} files, {sum(v[0] for v in files.values()) / 1e6:.0f} MB, digest {digest(files)[:12]}")
    exe = Path(ac) / "acs.exe"
    if exe.exists():
        ref["game"] = {"acs.exe": file_info(exe)}
        say("acs.exe: fingerprint stored (the AI driving code lives in the game executable)")
    if template:
        ref["conditions"] = conditions(template)
    ref["created"] = time.strftime("%Y-%m-%d %H:%M:%S")
    Path(ref_path).write_text(json.dumps(ref, indent=1), encoding="utf-8")
    say(f"Reference saved to {ref_path}")
    return 0


def verify(ac, specs, ref_path, template=None, ignore_ui=False, say=print):
    """-> {"status": ok | modified | noref, "tracks": {t: {"files": n, "digest": ...}}, "warnings": [...]}"""
    ref = load_ref(ref_path)
    result = {"status": "ok", "tracks": {}, "warnings": [], "ignore_ui": ignore_ui}
    if not ref:
        say(f"No reference file at {ref_path}. Create one on a clean install first.")
        result["status"] = "noref"
        return result
    for t in track_ids(specs):
        if t not in ref.get("tracks", {}):
            say(f"{t}: NOT IN THE REFERENCE. Create the reference including this track.")
            if result["status"] == "ok":
                result["status"] = "noref"
            continue
        tdir = Path(ac) / "content" / "tracks" / t
        if not tdir.is_dir():
            say(f"{t}: MISSING: folder not found: {tdir}")
            result["status"] = "modified"
            continue
        say(f"{t}: hashing every file ...")
        cur = keep(hash_tree(tdir), ignore_ui)
        want = keep(ref["tracks"][t]["files"], ignore_ui)
        modified, missing, extra = diff(want, cur)
        result["tracks"][t] = {"files": len(cur), "digest": digest(cur)}
        if modified or missing or extra:
            result["status"] = "modified"
            say(f"{t}: NOT VANILLA: {len(modified)} changed, {len(missing)} missing, {len(extra)} extra")
            for label, items in (("changed", modified), ("missing", missing), ("extra", extra)):
                for p in items[:10]:
                    say(f"    {label}: {p}")
                if len(items) > 10:
                    say(f"    ... and {len(items) - 10} more {label}")
        else:
            say(f"{t}: OK, {len(cur)} files identical to the reference (digest {result['tracks'][t]['digest'][:12]})")
        ai_names = sorted({Path(p).name for p in cur if p.lower().endswith(".ai")})
        ai_bad = [p for p in modified + missing + extra if p.lower().endswith(".ai")]
        if ai_bad:
            bad_list = ", ".join(ai_bad)
            say(f"{t}: AI LINE FILES NOT VANILLA: {bad_list}")
        elif ai_names:
            n_ai = sum(1 for p in cur if p.lower().endswith(".ai"))
            name_list = ", ".join(ai_names)
            say(f"{t}: AI lines vanilla ({n_ai} files: {name_list})")
        else:
            result["warnings"].append(f"{t}: no .ai line files found in the track, the AI may not drive it properly")
        m, x, e = diff(ref.get("csp", {}).get(t, {}), csp_files(ac, t))
        if m or x or e:
            result["warnings"].append(f"{t}: CSP track config files differ from the reference "
                                      f"({len(m)} changed, {len(x)} missing, {len(e)} extra)")
    game = ref.get("game")
    exe = Path(ac) / "acs.exe"
    if exe.exists():
        result["game"] = {"acs.exe": file_info(exe)[1]}
    if game is None:
        result["warnings"].append("reference has no acs.exe fingerprint (made by an older version): re-create it")
    elif not exe.exists():
        say("acs.exe: MISSING")
        result["status"] = "modified"
    elif file_info(exe) != game["acs.exe"]:
        say("acs.exe: DIFFERENT from the reference (other game version or patched). The AI is part of this file,\n"
            "    so its behaviour may differ: ratings would not be comparable.")
        result["status"] = "modified"
    else:
        say("acs.exe: OK, same game version as the reference (AI driving code)")
    if template and ref.get("conditions") is not None:
        cur_c, ref_c = conditions(template), ref["conditions"]
        for sec in sorted(set(cur_c) | set(ref_c)):
            for k in sorted(set(cur_c.get(sec, {})) | set(ref_c.get(sec, {}))):
                a, b = ref_c.get(sec, {}).get(k), cur_c.get(sec, {}).get(k)
                if a != b:
                    result["warnings"].append(f"race conditions differ: [{sec}] {k}: reference {a!r}, template {b!r}")
    for w in result["warnings"]:
        say("WARNING: " + w)
    return result


def make_env(result, profile):
    """Environment fingerprint of a passed check: which exact tracks + game executable the laps were driven on.
    -> (short id, dict). Uploaded with results; the cloud server compares it with its canonical one."""
    env = {"profile": profile, "ignore_ui": bool(result.get("ignore_ui")),
           "tracks": {t: v["digest"] for t, v in result["tracks"].items()},
           "acs": (result.get("game") or {}).get("acs.exe")}
    env_id = hashlib.sha256(json.dumps(env, sort_keys=True).encode()).hexdigest()[:16]
    return env_id, env


def append_log(path, result, env_id=None, env=None):
    """Keep a small history of checks next to the results (which install state was benchmarked)."""
    try:
        log = json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else []
    except Exception:
        log = []
    log.append({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "status": result["status"],
                "ignore_ui": result.get("ignore_ui", False), "tracks": result["tracks"],
                "warnings": result["warnings"], "env_id": env_id, "env": env})
    Path(path).write_text(json.dumps(log, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Vanilla track check")
    ap.add_argument("action", choices=["create", "verify"])
    ap.add_argument("--ac-dir", required=True)
    ap.add_argument("--reference", default=str(DEFAULT_REF))
    ap.add_argument("--template", help="template race.ini (race conditions are stored / compared as warnings)")
    ap.add_argument("--ignore-ui-files", action="store_true", help="verify: ignore each track's ui/ folder")
    ap.add_argument("--log", default=str(Path(__file__).resolve().with_name("track_check_log.json")),
                    help="verify: append the result (with the environment id) to this log")
    ap.add_argument("--tracks", nargs="+", required=True, help="track[/layout] (the whole track folder is used)")
    args = ap.parse_args()
    if args.action == "create":
        return create(args.ac_dir, args.tracks, args.reference, args.template)
    res = verify(args.ac_dir, args.tracks, args.reference, args.template, args.ignore_ui_files)
    env_id, env = make_env(res, PROFILE_ID) if res["status"] == "ok" else (None, None)
    append_log(args.log, res, env_id, env)
    return {"ok": 0, "modified": 2, "noref": 3}[res["status"]]


if __name__ == "__main__":
    sys.exit(main())
