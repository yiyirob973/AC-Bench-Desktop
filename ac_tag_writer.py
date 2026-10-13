#!/usr/bin/env python3
"""
Writes grid-class tags into each car's ui/ui_car.json so Content Manager can
filter opponents by tag. Only ui_car.json is touched (display metadata),
never data/, data.acd or models.

Safe by default: DRY RUN unless you pass --apply. First change to a file
creates ui_car.json.gridbak next to it.

Examples:
  python ac_tag_writer.py CARS_DIR car_classes.csv                      # dry run
  python ac_tag_writer.py CARS_DIR car_classes.csv --apply
  python ac_tag_writer.py CARS_DIR car_classes.csv --apply --exclude "^ks_"
  python ac_tag_writer.py CARS_DIR car_classes.csv --apply --untag      # remove our tags
  python ac_tag_writer.py CARS_DIR --restore                            # put backups back
"""
import argparse, csv, json, re, shutil
from pathlib import Path

from ac_car_classifier import norm_class

BACKUP_SUFFIX = ".gridbak"


def load_json(p):
    return json.loads(p.read_text(encoding="utf-8-sig", errors="replace"), strict=False)


def write_json(p, data):
    p.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")


def restore(cars_dir):
    n = 0
    for bak in Path(cars_dir).glob(f"*/ui/ui_car.json{BACKUP_SUFFIX}"):
        shutil.copy2(bak, bak.with_suffix(""))
        bak.unlink()
        n += 1
    print(f"Restored {n} files.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cars_dir", help="path to content/cars")
    ap.add_argument("csv", nargs="?", help="car_classes.csv from the classifier")
    ap.add_argument("--prefix", default="#grid-class-",
                    help="tag prefix; class letter is appended, e.g. #grid-class-A")
    ap.add_argument("--apply", action="store_true", help="actually write files")
    ap.add_argument("--untag", action="store_true", help="remove tags with this prefix")
    ap.add_argument("--restore", action="store_true", help="restore all .gridbak backups")
    ap.add_argument("--include", help="regex: only car ids matching")
    ap.add_argument("--exclude", help="regex: skip car ids matching (e.g. cars you race online)")
    args = ap.parse_args()

    if args.restore:
        restore(args.cars_dir)
        return
    if not args.csv:
        ap.error("csv is required unless --restore is used")

    cars = Path(args.cars_dir)
    pre = args.prefix.lower()
    changed = unchanged = 0
    skipped = []

    with open(args.csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for r in rows:
        cid = r["id"]
        if args.include and not re.search(args.include, cid):
            continue
        if args.exclude and re.search(args.exclude, cid):
            continue

        p = cars / cid / "ui" / "ui_car.json"
        if not p.exists():
            skipped.append(f"{cid}: no ui_car.json")
            continue
        try:
            data = load_json(p)
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except Exception as e:
            skipped.append(f"{cid}: unreadable ({e.__class__.__name__}), left untouched")
            continue

        old = data.get("tags") if isinstance(data.get("tags"), list) else []
        new = [t for t in old if not str(t).lower().startswith(pre)]
        if not args.untag:
            new.append(f"{args.prefix}{norm_class(r['class'])}")

        if new == old:
            unchanged += 1
            continue
        changed += 1
        if args.apply:
            bak = p.with_name(p.name + BACKUP_SUFFIX)
            if not bak.exists():
                shutil.copy2(p, bak)
            data["tags"] = new
            write_json(p, data)

    mode = "Updated" if args.apply else "Would update (dry run, pass --apply)"
    print(f"{mode}: {changed} cars, unchanged: {unchanged}, skipped: {len(skipped)}")
    for s in skipped[:15]:
        print("  skipped", s)
    if len(skipped) > 15:
        print(f"  ... and {len(skipped) - 15} more")


if __name__ == "__main__":
    main()
