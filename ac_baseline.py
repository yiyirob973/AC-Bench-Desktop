"""
The benchmark baseline. The SERVER defines it (see ac_conditions.py): profile, tracks, lap counts and, through the
server's "conditions" object, any race setting. Nothing the server decides is written in this file, and nothing here
can be edited from the GUI. Attribute names are unchanged (PROFILE_ID, TRACKS, TIMED_LAPS, LAPS, AI_CAR, CONDITIONS,
...), they are just resolved on first use from the last conditions fetched from the server. Without valid conditions
(never fetched, older than 12 hours, other server) reading any of them raises ac_conditions.ConditionsUnavailable.

What the server can send in its "conditions" object (same names as before; a section or dict the server sends
replaces the built-in one completely):
    AI_LEVEL, AI_AGGRESSION, RACE_LENGTH_LAPS                       scalars
    DYNAMIC_TRACK, WEATHER, TEMPERATURE, LIGHTING, WIND              race.ini sections written in every race
    AI_CAR                                                           written into every AI car section
    ASSISTS                                                          applied if the template has [ASSISTS]
The server currently sends an empty object, so the built-in values below (the ones profile baseline-v2 was defined
with) are used for these. They only apply to that profile: if the server moves to another profile it must send ALL of
the keys above, otherwise the app refuses to run rather than label results with a profile it did not measure.
"""
import copy, sys

from ac_conditions import ConditionsUnavailable, load

BUILTIN_PROFILE = "baseline-v2"   # the profile the built-in values below belong to

_BUILTIN = {
    "AI_LEVEL": "100",
    "AI_AGGRESSION": "0",
    "RACE_LENGTH_LAPS": 99,       # so long the race never finishes (see ac_lap_bench.py); only the first LAPS laps score
    "DYNAMIC_TRACK": {"SESSION_START": "100", "RANDOMNESS": "0", "LAP_GAIN": "0", "SESSION_TRANSFER": "0"},
    "WEATHER": {"NAME": "3_clear"},
    "TEMPERATURE": {"AMBIENT": "22", "ROAD": "28"},
    "LIGHTING": {"SUN_ANGLE": "-16", "TIME_MULT": "1"},
    "WIND": {"SPEED_KMH_MIN": "0", "SPEED_KMH_MAX": "0", "DIRECTION_DEG": "0"},
    "AI_CAR": {"BALLAST": "0", "RESTRICTOR": "0", "SETUP": "", "MODEL_CONFIG": ""},   # + AI_LEVEL / AI_AGGRESSION
    "ASSISTS": {"DAMAGE": "0", "FUEL_RATE": "0", "TYRE_WEAR": "0"},
}
_SCALARS = ("AI_LEVEL", "AI_AGGRESSION", "RACE_LENGTH_LAPS")
_SECTIONS = ("DYNAMIC_TRACK", "WEATHER", "TEMPERATURE", "LIGHTING", "WIND")
_KNOWN = _SCALARS + _SECTIONS + ("AI_CAR", "ASSISTS")

_NAMES = ("PROFILE_ID", "TRACKS", "TIMED_LAPS", "LAPS", "RACE_LENGTH_LAPS", "AI_LEVEL", "AI_AGGRESSION", "AI_CAR",
          "CONDITIONS", "ASSISTS", "MAX_BATCH", "MAX_ENTRIES", "ENV", "ACCEPTING_SUBMISSIONS", "CONDITIONS_VERSION")
__all__ = list(_NAMES) + ["describe", "reload", "ConditionsUnavailable"]

_state = None


def _strdict(name, v):
    if not isinstance(v, dict):
        raise ConditionsUnavailable(f"The server's condition '{name}' must be an object.")
    return {str(k): str(x) for k, x in v.items()}


def _build():
    d = load()
    over = d["conditions"]
    unknown = sorted(set(over) - set(_KNOWN))
    if unknown:
        print("WARNING: the server sent condition keys this app does not use (ignored): " + ", ".join(unknown),
              file=sys.stderr)
    if d["profile"] != BUILTIN_PROFILE:
        missing = [k for k in _KNOWN if k not in over]
        if missing:
            raise ConditionsUnavailable(
                f"The server's profile is {d['profile']}, but it did not send these race settings: "
                f"{', '.join(missing)}. Refusing to run with settings from another profile; "
                "the server must send them (or the app must be updated).")
    scal = {k: over.get(k, _BUILTIN[k]) for k in _SCALARS}
    try:
        race_len = int(scal["RACE_LENGTH_LAPS"])
    except (TypeError, ValueError):
        raise ConditionsUnavailable("The server's RACE_LENGTH_LAPS is not a number.")
    ai_level, ai_aggr = str(scal["AI_LEVEL"]), str(scal["AI_AGGRESSION"])
    race = {s: (_strdict(s, over[s]) if s in over else dict(_BUILTIN[s])) for s in _SECTIONS}
    ai_car = _strdict("AI_CAR", over["AI_CAR"]) if "AI_CAR" in over else {
        "AI_LEVEL": ai_level, "AI_AGGRESSION": ai_aggr, **_BUILTIN["AI_CAR"]}
    assists = _strdict("ASSISTS", over["ASSISTS"]) if "ASSISTS" in over else dict(_BUILTIN["ASSISTS"])
    return {"PROFILE_ID": d["profile"], "TRACKS": d["tracks"], "TIMED_LAPS": d["timed_laps"], "LAPS": d["laps"],
            "RACE_LENGTH_LAPS": race_len, "AI_LEVEL": ai_level, "AI_AGGRESSION": ai_aggr, "AI_CAR": ai_car,
            "CONDITIONS": race, "ASSISTS": assists, "MAX_BATCH": d["max_batch"], "MAX_ENTRIES": d["max_entries"],
            "ENV": d["env"], "ACCEPTING_SUBMISSIONS": d["accepting_submissions"], "CONDITIONS_VERSION": d["version"]}


def __getattr__(name):
    global _state
    if name in _NAMES:
        if _state is None:
            _state = _build()
        return copy.deepcopy(_state[name])
    raise AttributeError(f"module 'ac_baseline' has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | set(_NAMES))


def reload():
    """Forget the values read so far (the next access reads the cache again)."""
    global _state
    _state = None


def describe():
    s = _state if _state is not None else _build()
    c = s["CONDITIONS"]
    return (f"{s['PROFILE_ID']}: tracks {', '.join(s['TRACKS'])} | {s['LAPS']} laps (lap 1 dropped, median of {s['TIMED_LAPS']}) | "
            f"AI level {s['AI_LEVEL']}, aggression {s['AI_AGGRESSION']} | "
            f"{c['WEATHER'].get('NAME', '?')}, air {c['TEMPERATURE'].get('AMBIENT', '?')}C / road {c['TEMPERATURE'].get('ROAD', '?')}C, "
            f"grip {c['DYNAMIC_TRACK'].get('SESSION_START', '?')}% constant, no wind, 12:00")
