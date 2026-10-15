"""
Car identity for the cloud. A folder name is not an identity: two mods can share one, and a mod
update can change the physics under the same name. So a rating belongs to the car's PHYSICS:
the hash covers data.acd and/or data/ (every file) and collider.ini. Skins, models, sounds and the
UI files do not change how a car drives, so they are not part of it.
"""
import hashlib
from pathlib import Path


def _sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def car_hash(car_dir):
    """sha256 hex of the car's physics files as installed, or None if the car has none."""
    base = Path(car_dir)
    parts = []
    acd = base / "data.acd"
    if acd.is_file():
        parts.append(("data.acd", acd))
    ddir = base / "data"
    if ddir.is_dir():
        for p in sorted(ddir.rglob("*")):
            if p.is_file():
                parts.append(("data/" + p.relative_to(ddir).as_posix(), p))
    coll = base / "collider.ini"
    if coll.is_file():
        parts.append(("collider.ini", coll))
    if not parts:
        return None
    h = hashlib.sha256()
    for rel, p in parts:
        h.update(rel.encode("utf-8") + b"\0" + _sha256_file(p).encode("ascii") + b"\n")
    return h.hexdigest()
