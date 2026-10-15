"""
Where the app's files are, in source form and as a single portable exe (PyInstaller onefile).

RES   read-only files shipped inside the app: template_race.ini, bundled_car/, apps/lua/ac_bench/.
      In the exe these are unpacked to a temporary folder (sys._MEIPASS) that is DELETED when the app closes,
      so nothing the app must keep may be written there.
DATA  everything the app writes and keeps (settings, results, cloud_config.json, caches, logs): the folder the exe
      sits in (portable: copy the folder and everything moves with it). If that folder is not writable
      (for example Program Files) it falls back to %LOCALAPPDATA%\\AC-Bench.
In source form both are simply the folder of the .py files.
"""
import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
APP_NAME = "AC-Bench"


def _writable(folder):
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".write_test"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _data_dir():
    if not FROZEN:
        return Path(__file__).resolve().parent
    beside_exe = Path(sys.executable).resolve().parent
    if _writable(beside_exe):
        return beside_exe
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    fallback = Path(base) / APP_NAME
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


RES = Path(getattr(sys, "_MEIPASS", None) or Path(__file__).resolve().parent)
DATA = _data_dir()


def data(name):
    """A file or folder that belongs to the user (settings, results, caches)."""
    return DATA / name


def res(*parts):
    """A file or folder shipped inside the app (template, bundled car, Lua logger)."""
    return RES.joinpath(*parts)
