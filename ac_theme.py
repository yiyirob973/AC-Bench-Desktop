"""Colors and look of the app. The palette comes from the AC Bench logo (dark navy badge, blue ring, cyan accents).

Everything that decides how the window looks lives here, so the GUI only has to call use_theme() and apply().
"""
import ac_paths

# Backgrounds, darkest to lightest
BG = "#111d33"          # window background (the navy of the badge)
BG_RAISED = "#182a45"   # tab headers, buttons, the header strip
BG_FIELD = "#0c1627"    # inputs, lists and the log
ROW_ALT = "#14233b"     # every other row in the car lists
BORDER = "#2d5972"      # the ring of the badge: outlines and dividers

# Accents (the cyan of the AC frame and the gauge)
ACCENT = "#97e7f2"
ACCENT_STRONG = "#74d4e0"   # main buttons, progress
ACCENT_DIM = "#23435a"      # hover, selected rows

# Text
TEXT = "#ffffff"
TEXT_MUTED = "#9fb3c8"
TEXT_DISABLED = "#5d7087"

# Status colors for the lists
OK = "#5fd3a0"
WARN = "#f2c46d"
ERROR = "#ef6f6f"

ICON_ICO = ac_paths.res("branding", "ac-bench.ico")
ICON_PNG = ac_paths.res("branding", "ac-bench.png")
HEADER_PNG = ac_paths.res("branding", "header.png")


def use_theme(root, style):
    """Switch to the theme that can be recolored. The native Windows theme ignores most colors, so it isn't used."""
    try:
        style.theme_use("clam")
    except Exception:
        pass
    root.configure(background=BG)


def set_window_icon(root):
    """The logo in the title bar and the taskbar. Returns the PhotoImage objects, which have to be kept alive."""
    import tkinter as tk
    keep = []
    try:
        if ICON_ICO.is_file():
            root.iconbitmap(default=str(ICON_ICO))
    except tk.TclError:
        pass
    try:
        if ICON_PNG.is_file():
            img = tk.PhotoImage(file=str(ICON_PNG))
            root.iconphoto(True, img)
            keep.append(img)
    except tk.TclError:
        pass
    return keep


def header_logo():
    """The small logo for the strip at the top of the window, or None if the file is missing."""
    import tkinter as tk
    try:
        return tk.PhotoImage(file=str(HEADER_PNG)) if HEADER_PNG.is_file() else None
    except tk.TclError:
        return None


def apply(root, style, bold_font):
    """Colors for every widget the app uses. Call it before any widget is created."""
    # plain tk widgets (they don't read ttk styles)
    for pattern, value in (
        ("*Toplevel.background", BG), ("*Frame.background", BG), ("*Canvas.background", BG),
        ("*Text.background", BG_FIELD), ("*Text.foreground", TEXT), ("*Text.insertBackground", ACCENT),
        ("*Text.selectBackground", ACCENT_DIM), ("*Text.selectForeground", TEXT),
        ("*Text.highlightThickness", 1), ("*Text.highlightBackground", BORDER), ("*Text.highlightColor", ACCENT),
        ("*Text.borderWidth", 0),
        ("*Listbox.background", BG_FIELD), ("*Listbox.foreground", TEXT),
        ("*Listbox.selectBackground", ACCENT_DIM), ("*Listbox.selectForeground", TEXT),
        ("*TCombobox*Listbox.background", BG_FIELD), ("*TCombobox*Listbox.foreground", TEXT),
        ("*TCombobox*Listbox.selectBackground", ACCENT_DIM), ("*TCombobox*Listbox.selectForeground", TEXT),
    ):
        root.option_add(pattern, value)

    style.configure(".", background=BG, foreground=TEXT, fieldbackground=BG_FIELD, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, troughcolor=BG_FIELD, focuscolor=ACCENT,
                    insertcolor=ACCENT, selectbackground=ACCENT_DIM, selectforeground=TEXT)
    style.map(".", foreground=[("disabled", TEXT_DISABLED)])

    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Muted.TLabel", foreground=TEXT_MUTED)
    style.configure("Bold.TLabel", font=bold_font)
    style.configure("Header.TLabel", background=BG_RAISED, foreground=TEXT)
    style.configure("TLabelframe", background=BG, bordercolor=BORDER)
    style.configure("TLabelframe.Label", background=BG, foreground=ACCENT, font=bold_font)

    style.configure("TButton", background=BG_RAISED, foreground=TEXT, bordercolor=BORDER, focusthickness=1)
    style.map("TButton",
              background=[("disabled", BG), ("pressed", ACCENT_DIM), ("active", ACCENT_DIM)],
              bordercolor=[("active", ACCENT), ("focus", ACCENT)])
    style.configure("Accent.TButton", background=ACCENT_STRONG, foreground=BG, bordercolor=ACCENT_STRONG)
    style.map("Accent.TButton",
              background=[("disabled", ACCENT_DIM), ("pressed", ACCENT), ("active", ACCENT)],
              foreground=[("disabled", TEXT_DISABLED)])

    style.configure("TNotebook", background=BG, bordercolor=BORDER)
    style.configure("TNotebook.Tab", background=BG_RAISED, foreground=TEXT_MUTED, bordercolor=BORDER)
    style.map("TNotebook.Tab",
              background=[("selected", BG), ("active", ACCENT_DIM)],
              foreground=[("selected", ACCENT), ("active", TEXT)])

    style.configure("Treeview", background=BG_FIELD, fieldbackground=BG_FIELD, foreground=TEXT, bordercolor=BORDER)
    style.map("Treeview", background=[("selected", ACCENT_DIM)], foreground=[("selected", TEXT)])
    style.configure("Treeview.Heading", background=BG_RAISED, foreground=ACCENT, bordercolor=BORDER, relief="flat")
    style.map("Treeview.Heading", background=[("active", ACCENT_DIM)])

    for name in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(name, fieldbackground=BG_FIELD, foreground=TEXT, bordercolor=BORDER, insertcolor=ACCENT,
                        arrowcolor=ACCENT, background=BG_RAISED)
        style.map(name, bordercolor=[("focus", ACCENT)], fieldbackground=[("disabled", BG), ("readonly", BG_FIELD)],
                  foreground=[("disabled", TEXT_DISABLED)])

    for name in ("TCheckbutton", "TRadiobutton"):
        style.configure(name, background=BG, foreground=TEXT, indicatorbackground=BG_FIELD,
                        indicatorforeground=BG, upperbordercolor=BORDER, lowerbordercolor=BORDER)
        style.map(name, background=[("active", BG)], indicatorbackground=[("selected", ACCENT_STRONG)],
                  foreground=[("disabled", TEXT_DISABLED)])

    style.configure("TScrollbar", background=BG_RAISED, troughcolor=BG_FIELD, bordercolor=BORDER, arrowcolor=ACCENT)
    style.map("TScrollbar", background=[("active", ACCENT_DIM)])
    style.configure("TProgressbar", background=ACCENT_STRONG, troughcolor=BG_FIELD, bordercolor=BORDER)
    style.configure("TSeparator", background=BORDER)
