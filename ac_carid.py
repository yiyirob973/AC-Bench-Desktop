#!/usr/bin/env python3
"""Car identity helper."""
import hashlib
from pathlib import Path


def car_hash(car_dir):
    base = Path(car_dir)
    h = hashlib.sha256()
    for p in sorted((base / "data").rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(base)).encode("utf-8"))
            h.update(p.read_bytes())
    coll = base / "collider.ini"
    if coll.exists():
        h.update(b"collider.ini")
        h.update(coll.read_bytes())
    return h.hexdigest()
