"""
The fixed benchmark baseline. Everything that can change a lap time is pinned HERE, in code,
so every car on every PC is measured under identical conditions. Nothing below is read from
the template race.ini or from GUI settings; the runner overwrites those values in every race
it writes. If you ever change anything in this file, bump PROFILE_ID: results are tagged with
it, and results made under another profile are shown as "old settings" and are not mixed in
silently.

The goal is a repeatable baseline to compare cars against each other, not the fastest lap.
"""

PROFILE_ID = "baseline-v2"

# Vanilla Kunos tracks (the whole track folder, AI lines included, is hash-checked by ac_track_check.py)
TRACKS = ["magione", "ks_vallelunga/club_circuit"]
TIMED_LAPS = 3                 # laps that count: a car is scored by the MEDIAN of these (use 3 to 5)
LAPS = TIMED_LAPS + 1          # laps that are recorded per car = lap 1 (standing start, always dropped) + the timed laps
RACE_LENGTH_LAPS = 99          # the race itself is made so long that it never finishes: lapped or slow cars can then
                               # always complete LAPS laps, AC never reaches the results screen, and the runner closes AC
                               # itself once every car has its laps. Only the first LAPS laps of each car are scored.

AI_LEVEL = "100"
AI_AGGRESSION = "0"

# Written into every AI car section (these also wipe anything a template might carry: ballast,
# restrictors, setups, layouts).
AI_CAR = {
    "AI_LEVEL": AI_LEVEL,
    "AI_AGGRESSION": AI_AGGRESSION,
    "BALLAST": "0",
    "RESTRICTOR": "0",
    "SETUP": "",
    "MODEL_CONFIG": "",
}

# Race conditions, overwritten in every generated race.ini
CONDITIONS = {
    "DYNAMIC_TRACK": {"SESSION_START": "100", "RANDOMNESS": "0", "LAP_GAIN": "0", "SESSION_TRANSFER": "0"},
    "WEATHER": {"NAME": "3_clear"},                                  # vanilla clear weather
    "TEMPERATURE": {"AMBIENT": "22", "ROAD": "28"},
    "LIGHTING": {"SUN_ANGLE": "-16", "TIME_MULT": "1"},               # 12:00, time not accelerated
    "WIND": {"SPEED_KMH_MIN": "0", "SPEED_KMH_MAX": "0", "DIRECTION_DEG": "0"},
}

# Only applied if the template has an [ASSISTS] section (keeps wear / fuel / damage out of the picture)
ASSISTS = {"DAMAGE": "0", "FUEL_RATE": "0", "TYRE_WEAR": "0"}


def describe():
    c = CONDITIONS
    return (f"{PROFILE_ID}: tracks {', '.join(TRACKS)} | {LAPS} laps (lap 1 dropped, median of {TIMED_LAPS}) | AI level {AI_LEVEL}, aggression {AI_AGGRESSION} | "
            f"{c['WEATHER']['NAME']}, air {c['TEMPERATURE']['AMBIENT']}C / road {c['TEMPERATURE']['ROAD']}C, "
            f"grip {c['DYNAMIC_TRACK']['SESSION_START']}% constant, no wind, 12:00")
