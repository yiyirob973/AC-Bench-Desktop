#!/usr/bin/env python3
"""
Start a race with AC's own "Start race" command instead of clicking the Drive button.

Content Manager > Settings > Assetto Corsa > Controls > System > Race has a "Start race" row. It is stored in
Documents/Assetto Corsa/cfg/controls.ini as

    [__CM_START_SESSION]
    KEY=<Windows virtual-key code>

and the hotkey is Ctrl + that key. This module makes sure that entry exists (so the user never has to set it
up in Content Manager), and tells ac_input.py which key to press. An existing binding of the user is kept.

Who acts on the hotkey inside the game: Custom Shaders Patch handles the hotkeys listed in
<AC>/extension/config/data_hotkeys_supported.txt itself; Content Manager handles the others, but only for games it
launched. csp_handles_start_session() reports which case this install is.

  python ac_controls.py status --docs-dir "<Documents/Assetto Corsa>" [--ac-dir "<AC>"]
  python ac_controls.py setup  --docs-dir "<Documents/Assetto Corsa>" [--ac-dir "<AC>"]
"""
import argparse
import re
import sys
from pathlib import Path

import ac_paths  # noqa: F401  (keeps the packaged build's module list complete)

SECTION = "__CM_START_SESSION"
DEFAULT_VK = 0x7B            # F12: not a toggle key, nothing else in AC needs Ctrl+F12
BACKUP_NAME = "controls.ini.acbench.bak"
_HEADER = re.compile(r"^\s*\[([^\]]*)\]\s*$")
_KEY = re.compile(r"^\s*KEY\s*=\s*(-?\d+)\s*(;.*)?$", re.IGNORECASE)

_NAMES = {0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x1B: "Esc", 0x20: "Space", 0x21: "Page Up", 0x22: "Page Down",
          0x23: "End", 0x24: "Home", 0x2D: "Insert", 0x2E: "Delete", 0x13: "Pause", 0x91: "Scroll Lock"}


def vk_name(vk):
    if 0x70 <= vk <= 0x87:
        return "F%d" % (vk - 0x6F)
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    if 0x60 <= vk <= 0x69:
        return "Numpad %d" % (vk - 0x60)
    return _NAMES.get(vk, "key %d" % vk)


def controls_ini(docs_dir):
    return Path(docs_dir) / "cfg" / "controls.ini"


def _split(text):
    nl = "\r\n" if "\r\n" in text else "\n"
    return text.split(nl), nl


def _find_section(lines, name):
    """(header index, index of the next header or len) of the first [name] section, or None."""
    start = None
    for i, line in enumerate(lines):
        m = _HEADER.match(line.rstrip("\r"))
        if m:
            if start is not None:
                return start, i
            if m.group(1).strip().upper() == name.upper():
                start = i
    return (start, len(lines)) if start is not None else None


def _find_key(lines, start, end):
    """(line index, value) of KEY= inside the section, or None."""
    for i in range(start + 1, end):
        m = _KEY.match(lines[i].rstrip("\r"))
        if m:
            return i, int(m.group(1))
    return None


def read_start_hotkey(docs_dir):
    """The Ctrl+<key> virtual-key code set for 'Start race' in controls.ini, or None."""
    path = controls_ini(docs_dir)
    try:
        text = path.read_bytes().decode("latin-1")
    except OSError:
        return None
    lines, _ = _split(text)
    sec = _find_section(lines, SECTION)
    if not sec:
        return None
    found = _find_key(lines, *sec)
    return found[1] if found and found[1] > 0 else None


def ensure_start_hotkey(docs_dir, default_vk=DEFAULT_VK, say=print):
    """Make sure 'Start race' has a key in controls.ini. A binding that is already there is left alone.
    Only the one line is added or changed; the rest of the file is kept byte for byte, and a backup of the original is
    saved once as controls.ini.acbench.bak. -> (virtual-key code or None, what happened)."""
    path = controls_ini(docs_dir)
    if not path.is_file():
        return None, ("controls.ini not found in %s: start Assetto Corsa once (or Content Manager) so it is created"
                      % path.parent)
    original = path.read_bytes()
    lines, nl = _split(original.decode("latin-1"))
    sec = _find_section(lines, SECTION)
    changed = False
    if sec:
        found = _find_key(lines, *sec)
        if found and found[1] > 0:
            return found[1], "using the 'Start race' hotkey already set in controls.ini: Ctrl+%s" % vk_name(found[1])
        if found:
            lines[found[0]] = "KEY=%d" % default_vk
        else:
            lines.insert(sec[0] + 1, "KEY=%d" % default_vk)
        changed = True
    else:
        while lines and lines[-1].strip() == "":
            lines.pop()
        lines += ["", "[%s]" % SECTION, "KEY=%d" % default_vk, ""]
        changed = True
    if changed:
        backup = path.with_name(BACKUP_NAME)
        try:
            if not backup.exists():
                backup.write_bytes(original)
            tmp = path.with_name(path.name + ".acbench.tmp")
            tmp.write_bytes(nl.join(lines).encode("latin-1"))
            tmp.replace(path)
        except OSError as e:
            return None, "could not write controls.ini (%s)" % e
    return default_vk, "set the 'Start race' hotkey in controls.ini: Ctrl+%s" % vk_name(default_vk)


def csp_handles_start_session(ac_dir):
    """True: Custom Shaders Patch handles the 'Start race' hotkey inside the game. False: it does not (then only
    Content Manager does, for games it started itself). None: cannot tell (no Custom Shaders Patch file)."""
    p = Path(ac_dir) / "extension" / "config" / "data_hotkeys_supported.txt"
    try:
        names = {x.strip() for x in p.read_text(encoding="utf-8", errors="replace").splitlines()}
    except OSError:
        return None
    return SECTION in names


def describe(docs_dir, ac_dir=None):
    vk = read_start_hotkey(docs_dir)
    lines = [("Start-race hotkey in controls.ini: Ctrl+%s" % vk_name(vk)) if vk
             else "Start-race hotkey in controls.ini: not set yet (the app sets it before the first benchmark)"]
    if ac_dir:
        csp = csp_handles_start_session(ac_dir)
        lines.append({True: "Custom Shaders Patch handles it inside the game: works however AC is started",
                      False: "Custom Shaders Patch does NOT list it: only Content Manager acts on this hotkey, and only "
                             "for games it started itself, so it may do nothing here",
                      None: "Custom Shaders Patch hotkey list not found (CSP not installed or not recent enough)"}[csp])
    return lines


def main(argv=None):
    ac_paths.utf8_output()
    ap = argparse.ArgumentParser(description="Set up and inspect AC's 'Start race' hotkey")
    ap.add_argument("action", choices=["status", "setup"])
    ap.add_argument("--docs-dir", default=str(Path.home() / "Documents" / "Assetto Corsa"))
    ap.add_argument("--ac-dir")
    args = ap.parse_args(argv)
    if args.action == "setup":
        vk, note = ensure_start_hotkey(args.docs_dir)
        print(note)
        if vk is None:
            return 1
    for line in describe(args.docs_dir, args.ac_dir):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
