"""NASA POWER daily rain, used only for days since a wetting rain.

The daily product lags real time. On 2026-11-19 the newest three days came
back as the -999 fill. Those values are dropped and counted. They are never
treated as zero rain and never treated as a dry day by themselves.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.constants import (
    MEANINGFUL_RAIN_MM,
    POWER_FILL_SENTINEL,
    POWER_LAG_NOTE,
    POWER_LOOKBACK_DAYS,
)
from app.http_client import FeedHTTPError, get_json

POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"


def fetch_point(lat: float, lon: float, today: date) -> dict:
    start = today - timedelta(days=POWER_LOOKBACK_DAYS)
    status, payload = get_json(
        POWER_URL,
        params={
            "parameters": "T2M_MAX,RH2M,WS2M,PRECTOTCORR",
            "community": "AG",
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "start": start.strftime("%Y%m%d"),
            "end": today.strftime("%Y%m%d"),
            "format": "JSON",
        },
    )
    if status != 200 or not isinstance(payload, dict):
        raise FeedHTTPError(f"NASA POWER returned HTTP {status}")
    return payload


def _is_fill(value: float) -> bool:
    return value <= POWER_FILL_SENTINEL


def _out_of_range(name: str, value: float) -> bool:
    if name == "T2M_MAX":
        return not (-80.0 <= value <= 60.0)
    if name == "RH2M":
        return not (0.0 <= value <= 100.0)
    if name == "WS2M":
        return not (0.0 <= value <= 75.0)
    if name == "PRECTOTCORR":
        return not (0.0 <= value <= 500.0)
    return False


def summarize(payload: dict, today: date) -> dict:
    """Days since PRECTOTCORR >= 2.5 mm, walking back through valid days only.

    The count stops at the latest valid day. Trailing fill days are the lag,
    not extra dry days. A fill day in the middle also stops the walk, because
    that day is unknown rather than dry.
    """
    parameters = ((payload.get("properties") or {}).get("parameter") or {}) if isinstance(payload, dict) else {}
    dropped = {"fill": 0, "range": 0, "missing": 0}
    per_parameter: dict[str, int] = {}
    for name in ("T2M_MAX", "RH2M", "WS2M", "PRECTOTCORR"):
        series = parameters.get(name) or {}
        count = 0
        if not isinstance(series, dict):
            continue
        for raw in series.values():
            if raw is None or raw == "":
                dropped["missing"] += 1
                count += 1
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                dropped["missing"] += 1
                count += 1
                continue
            if _is_fill(value):
                dropped["fill"] += 1
                count += 1
                continue
            if _out_of_range(name, value):
                dropped["range"] += 1
                count += 1
        per_parameter[name] = count

    precip = parameters.get("PRECTOTCORR") if isinstance(parameters.get("PRECTOTCORR"), dict) else {}
    valid: dict[date, float] = {}
    for key, raw in precip.items():
        try:
            day = datetime.strptime(str(key), "%Y%m%d").date()
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if _is_fill(value) or _out_of_range("PRECTOTCORR", value):
            continue
        valid[day] = value

    notes = [POWER_LAG_NOTE]
    total_dropped = dropped["fill"] + dropped["range"] + dropped["missing"]
    if dropped["fill"]:
        notes.append(f"Dropped {dropped['fill']} POWER fill values (-999).")
    if dropped["range"]:
        notes.append(f"Dropped {dropped['range']} POWER values outside the expected range.")
    if dropped["missing"]:
        notes.append(f"Dropped {dropped['missing']} POWER values that were missing or not numeric.")

    if not valid:
        notes.append("Every POWER day in this window was unusable, so days since rain were left out of the score.")
        return {
            "available": False,
            "days_since_rain": None,
            "last_valid": None,
            "last_rain": None,
            "lag_days": None,
            "dropped": total_dropped,
            "dropped_detail": dropped,
            "notes": notes,
            "no_rain_in_window": False,
        }

    last_valid = max(valid)
    lag_days = (today - last_valid).days
    notes.append(
        f"Latest valid POWER day is {last_valid.isoformat()} ({lag_days} day{'s' if lag_days != 1 else ''} before today)."
    )

    days_since = 0
    cursor = last_valid
    last_rain: date | None = None
    hit_gap = False
    while cursor >= min(valid):
        if cursor not in valid:
            hit_gap = True
            break
        if valid[cursor] >= MEANINGFUL_RAIN_MM:
            last_rain = cursor
            break
        days_since += 1
        cursor -= timedelta(days=1)

    no_rain = last_rain is None and not hit_gap
    if last_rain is not None:
        notes.append(
            f"Meaningful rain is at least {MEANINGFUL_RAIN_MM} mm in a day. "
            f"Last one on {last_rain.isoformat()}. Days since, as of the latest valid day: {days_since}."
        )
    elif hit_gap:
        notes.append("A gap in POWER stopped the dry-day count. Days before that gap were not treated as dry.")
    else:
        notes.append(
            f"No day with at least {MEANINGFUL_RAIN_MM} mm in the valid POWER window. "
            "The dryness factor uses that whole dry stretch."
        )

    return {
        "available": True,
        "days_since_rain": days_since,
        "last_valid": last_valid.isoformat(),
        "last_rain": None if last_rain is None else last_rain.isoformat(),
        "lag_days": lag_days,
        "dropped": total_dropped,
        "dropped_detail": dropped,
        "notes": notes,
        "no_rain_in_window": no_rain,
    }
