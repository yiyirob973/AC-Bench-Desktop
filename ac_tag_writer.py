#!/usr/bin/env python3
"""
Write class tags into each car's ui/ui_car.json (shown as tags in Content Manager).

    ac_tag_writer.py CARS_DIR CLASSES_CSV [--prefix #Pride-] [--also-remove PREFIX ...] [--exclude REGEX] [--apply]
    ac_tag_writer.py CARS_DIR [--prefix #Pride-] [--also-remove PREFIX ...] --untag [--apply]
    ac_tag_writer.py CARS_DIR --restore

Without --apply it is a dry run. Duplicate protection:
  * every tag that starts with the prefix (or with an --also-remove prefix, e.g. tags of an older version) is
    removed first, then exactly ONE class tag is added, so applying
    twice, or after a car changed class, never leaves two class tags behind;
  * the whole tag list is de-duplicated (case-insensitive, first spelling kept, order kept);
  * a file is only rewritten when its tag list actually changes, and written atomically;
  * the first backup (ui_car.json.gridbak) is never overwritten, so --restore always returns the ORIGINAL file.
"""
import argparse, csv, json, os, re, sys, tempfile
from pathlib import Path

BOM = b"\xef\xbb\xbf"


def norm(tag):
    return tag.strip().casefold()


def dedupe(tags):
    """Drop repeated tags (case/whitespace-insensitive), keeping the first one and the order."""
    seen, out = set(), []
    for t in tags:
        key = norm(t) if isinstance(t, str) else None
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        out.append(t)
    return out


def new_tags(existing, prefix, label, untag=False, also_remove=()):
    """Tag list after removing every tag with this prefix (or an also_remove prefix) and, unless untag, adding
    the single class tag."""
    prefixes = tuple(norm(x) for x in (prefix, *also_remove) if x.strip())
    kept = [t for t in existing if not (isinstance(t, str) and norm(t).startswith(prefixes))]
    if not untag:
        kept.append(prefix + label)
    return dedupe(kept)


def read_classes(path):
    """{car id: class label} from the classes CSV (last row wins if an id repeats)."""
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            cid, label = (r.get("id") or "").strip(), (r.get("class") or "").strip()
            if cid and label:
                out[cid] = label
    return out


def write_atomic(path, data):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def restore(cars_dir):
    n = 0
    for d in sorted(p for p in cars_dir.iterdir() if p.is_dir()):
        f = d / "ui" / "ui_car.json"
        bak = Path(str(f) + ".gridbak")
        if bak.exists():
            write_atomic(f, bak.read_bytes())
            bak.unlink()
            n += 1
            print(f"restored {d.name}")
    print(f"Restored {n} car file(s).")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cars_dir")
    ap.add_argument("classes", nargs="?")
    ap.add_argument("--prefix", default="#Pride-")
    ap.add_argument("--also-remove", action="append", default=[],
                    help="also remove tags starting with this prefix (repeatable), e.g. tags from an older version")
    ap.add_argument("--exclude", default="")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--untag", action="store_true")
    ap.add_argument("--restore", action="store_true")
    a = ap.parse_args()

    cars = Path(a.cars_dir)
    if not cars.is_dir():
        sys.exit(f"Cars folder not found: {cars}")
    if a.restore:
        return restore(cars)
    if not a.classes and not a.untag:
        sys.exit("A classes CSV is required (or use --untag / --restore).")
    for x in (a.prefix, *a.also_remove):
        if len(x.strip()) < 3:
            sys.exit("A tag prefix is too short; it must be at least 3 characters so other tags are never removed.")
    labels = read_classes(a.classes) if a.classes else {}
    excl = re.compile(a.exclude) if a.exclude else None

    changed = same = skipped = 0
    for d in sorted(p for p in cars.iterdir() if p.is_dir()):
        label = labels.get(d.name)
        f = d / "ui" / "ui_car.json"
        if excl and excl.search(d.name):
            skipped += 1
            continue
        if not f.exists() or (label is None and not a.untag):
            skipped += 1
            continue
        raw = f.read_bytes()
        try:
            data = json.loads(raw.decode("utf-8-sig", errors="replace"), strict=False)
        except ValueError as e:
            print(f"skip {d.name}: ui_car.json is not valid JSON ({e}); left untouched")
            skipped += 1
            continue
        old = data.get("tags", [])
        if not isinstance(old, list):
            print(f"skip {d.name}: 'tags' is not a list; left untouched")
            skipped += 1
            continue
        tags = new_tags(old, a.prefix, label or "", untag=a.untag, also_remove=a.also_remove)
        if tags == old:
            same += 1
            continue
        changed += 1
        print(f"{'set' if a.apply else 'would set'} {d.name}: {old} -> {tags}")
        if not a.apply:
            continue
        bak = Path(str(f) + ".gridbak")
        if not bak.exists():  # keep the first (original) backup
            write_atomic(bak, raw)
        data["tags"] = tags
        out = json.dumps(data, indent=4, ensure_ascii=False).encode("utf-8")
        write_atomic(f, (BOM if raw.startswith(BOM) else b"") + out)

    verb = "Changed" if a.apply else "Would change"
    print(f"{verb} {changed} car(s); {same} already correct; {skipped} skipped."
          + ("" if a.apply else " Dry run: nothing written (use Apply tags)."))


if __name__ == "__main__":
    main()
