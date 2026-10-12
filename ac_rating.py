#!/usr/bin/env python3
"""Shared rating logic for the desktop repo."""
PROFILE_ID = "baseline-v2"


def lap_score(entry):
    return float(entry.get("score", 0.0))


def main():
    print("Desktop rating helper loaded")


if __name__ == "__main__":
    main()
