"""
Where the app's files are: from source, and in a packaged build (Nuitka standalone/onefile or PyInstaller).

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

# PyInstaller sets sys.frozen; Nuitka does not, but defines __compiled__ in every compiled module
FROZEN = bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()
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


def _exe_folder():
    """The folder the user's exe sits in (for a Nuitka onefile build: the original exe, not the unpack folder)."""
    compiled = globals().get("__compiled__")
    containing = getattr(compiled, "containing_dir", None)
    if containing:
        return Path(containing).resolve()
    return Path(sys.executable).resolve().parent


def _data_dir():
    if not FROZEN:
        return Path(__file__).resolve().parent
    beside_exe = _exe_folder()
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
