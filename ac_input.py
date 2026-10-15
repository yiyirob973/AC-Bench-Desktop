#!/usr/bin/env python3
"""
Windows-only helper: find the Assetto Corsa window and click / press a key in it.
Used by ac_lap_bench.py to get past the pre-race "Drive" menu automatically.

  python ac_input.py calibrate   # AC open on the Drive menu: hover the mouse over the
                                 # Drive button, press F8. Saves drive_click.json
  python ac_input.py click       # test: one click at the saved position
  python ac_input.py key enter   # test: press a key (enter, space, esc, tab, f1-f12, a letter)

The position is saved as a fraction of the AC window, so it survives resolution
changes. Run AC windowed or borderless. Inputs go to whatever is on screen, so
don't use the PC for other things while a benchmark runs.
"""
import json, sys, time
from pathlib import Path

import ac_paths  # noqa: E402
CFG = ac_paths.DATA / "drive_click.json"
TITLE = "Assetto Corsa"
KEYS = {"enter": 0x0D, "space": 0x20, "esc": 0x1B, "tab": 0x09,
        **{f"f{i}": 0x6F + i for i in range(1, 13)}}

try:
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass
except (ImportError, AttributeError, OSError):
    user32 = None


def _need_windows():
    if user32 is None:
        raise RuntimeError("Auto-start (click/key) only works on Windows.")


def find_window(title=TITLE):
    """Handle of the visible window titled exactly `title`, or None."""
    _need_windows()
    found = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value == title:
                    found.append(hwnd)
        return True

    user32.EnumWindows(enum_proc(cb), 0)
    return found[0] if found else None


def focus(hwnd):
    user32.keybd_event(0x12, 0, 0, 0)       # tap Alt: lets us take the foreground
    user32.keybd_event(0x12, 0, 2, 0)
    user32.ShowWindow(hwnd, 9)              # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)


def click_fraction(hwnd, fx, fy):
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    pt = wintypes.POINT(int(fx * rect.right), int(fy * rect.bottom))
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    focus(hwnd)
    user32.SetCursorPos(pt.x, pt.y)
    time.sleep(0.15)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # left down
    time.sleep(0.06)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # left up


def press_key(hwnd, name):
    name = name.strip().lower()
    vk = KEYS.get(name) or (ord(name.upper()) if len(name) == 1 else None)
    if vk is None:
        raise ValueError(f"Unknown key '{name}'")
    focus(hwnd)
    scan = user32.MapVirtualKeyW(vk, 0)
    user32.keybd_event(vk, scan, 0, 0)
    time.sleep(0.08)
    user32.keybd_event(vk, scan, 2, 0)


def load_click():
    try:
        d = json.loads(CFG.read_text(encoding="utf-8"))
        return float(d["fx"]), float(d["fy"])
    except Exception:
        return None


def nudge(click_pos=None, key=None):
    """One start attempt: click and/or press a key in the AC window. False if no window."""
    hwnd = find_window()
    if not hwnd:
        return False
    if click_pos:
        click_fraction(hwnd, *click_pos)
    if key:
        press_key(hwnd, key)
    return True


def calibrate(timeout=180):
    _need_windows()
    print("Open AC so the Drive menu is showing, hover the mouse over the Drive button,")
    print(f"then press F8 (waiting up to {timeout} s)...", flush=True)
    end = time.time() + timeout
    while time.time() < end:
        if user32.GetAsyncKeyState(0x77) & 0x8000:      # F8
            break
        time.sleep(0.05)
    else:
        print("Timed out, nothing saved.")
        return 1
    hwnd = find_window()
    if not hwnd:
        print(f"No window titled '{TITLE}' found. Is AC running (windowed/borderless)?")
        return 1
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    user32.ScreenToClient(hwnd, ctypes.byref(pt))
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    fx, fy = pt.x / rect.right, pt.y / rect.bottom
    if not (0 <= fx <= 1 and 0 <= fy <= 1):
        print("The mouse was outside the AC window. Try again.")
        return 1
    CFG.write_text(json.dumps({"fx": round(fx, 4), "fy": round(fy, 4)}), encoding="utf-8")
    print(f"Saved Drive position ({fx:.1%} across, {fy:.1%} down) to {CFG.name}")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if cmd == "calibrate":
            return calibrate()
        if cmd == "click":
            pos = load_click()
            if not pos:
                print("No saved position. Run: python ac_input.py calibrate")
                return 1
            print("Clicked." if nudge(pos, None) else f"No '{TITLE}' window found.")
            return 0
        if cmd == "key" and len(sys.argv) > 2:
            print("Sent." if nudge(None, sys.argv[2]) else f"No '{TITLE}' window found.")
            return 0
    except Exception as e:
        print("Error:", e)
        return 1
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
