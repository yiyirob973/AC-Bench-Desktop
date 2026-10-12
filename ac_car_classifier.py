#!/usr/bin/env python3
"""Assetto Corsa car classifier (desktop-side helper)."""
import argparse, csv, json, math, re
from pathlib import Path

PW_EXP = 0.40
GRIP_EXP = 0.80


def num(v):
    m = re.search(r"\d+(?:\.\d+)?", str(v).replace(",", ""))
    return float(m.group()) if m else None


def read_ini(path):
    import configparser
    cp = configparser.ConfigParser(strict=False, interpolation=None, inline_comment_prefixes=(";", "//"))
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            cp.read_file(f)
    except Exception:
        pass
    return cp


def class_label(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def norm_class(v):
    s = str(v).strip()
    return class_label(int(s)) if s.isdigit() else s.upper()


def main():
    print("AC Bench classifier loaded")


if __name__ == "__main__":
    main()
