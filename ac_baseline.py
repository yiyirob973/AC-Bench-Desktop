#!/usr/bin/env python3
"""Shared benchmark baseline settings."""
PROFILE_ID = "baseline-v2"
TRACKS = ["magione", "ks_vallelunga/club_circuit"]
TIMED_LAPS = 3
LAPS = TIMED_LAPS + 1
RACE_LENGTH_LAPS = 99
AI_LEVEL = "100"
AI_AGGRESSION = "0"


def describe():
    return "baseline-v2"
