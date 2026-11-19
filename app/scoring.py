"""Fosberg Fire Weather Index and the 0–100 daily risk score.

See app.constants for the formula, the weights, and where each number came from.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from app.constants import (
    DRYNESS_FULL_DAYS,
    EMC_MAX,
    EMC_MIN,
    FFWI_CAP,
    NEARBY_FIRE_FULL_KM,
    NEARBY_FIRE_ZERO_KM,
    RISK_BANDS,
    SCORE_WEIGHTS,
)

_WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def equilibrium_moisture(temp_f: float, rh: float) -> float:
    """Simard equilibrium moisture content, percent, before clamping.

    Boundaries: h < 10 uses the low branch, 10 <= h <= 50 the middle branch
    (coefficient 0.01478), and h > 50 the high branch. h == 10 and h == 50
    stay on the middle branch so the piecewise function has no gap.
    """
    if rh < 0 or rh > 100:
        raise ValueError(f"relative humidity {rh} is outside 0–100")
    if rh < 10:
        return 0.03229 + 0.281073 * rh - 0.000578 * rh * temp_f
    if rh <= 50:
        return 2.22749 + 0.160107 * rh - 0.01478 * temp_f
    return 21.0606 + 0.005565 * rh * rh - 0.00035 * rh * temp_f - 0.483199 * rh


def moisture_damping(emc: float) -> tuple[float, float]:
    """Return (clamped EMC, eta). EMC is limited to [0, 30]."""
    clamped = min(EMC_MAX, max(EMC_MIN, emc))
    ratio = clamped / 30.0
    eta = 1.0 - 2.0 * ratio + 1.5 * ratio * ratio - 0.5 * ratio * ratio * ratio
    return clamped, eta


def fosberg_from_moisture(emc: float, wind_mph: float) -> dict[str, float]:
    if wind_mph < 0:
        raise ValueError(f"wind speed {wind_mph} is negative")
    clamped, eta = moisture_damping(emc)
    raw = eta * math.sqrt(1.0 + wind_mph * wind_mph) / 0.3002
    capped = min(FFWI_CAP, max(0.0, raw))
    return {
        "emc_input": emc,
        "emc": clamped,
        "eta": eta,
        "ffwi_raw": raw,
        "ffwi": capped,
    }


def fosberg_ffwi(temp_f: float, rh: float, wind_mph: float) -> dict[str, float]:
    """FFWI plus the intermediate EMC and eta values."""
    emc = equilibrium_moisture(temp_f, rh)
    result = fosberg_from_moisture(emc, wind_mph)
    result["temp_f"] = temp_f
    result["rh"] = rh
    result["wind_mph"] = wind_mph
    return result


def dryness_normalized(days_since_rain: float) -> float:
    if days_since_rain < 0:
        raise ValueError("days since rain cannot be negative")
    if days_since_rain >= DRYNESS_FULL_DAYS:
        return 100.0
    return 100.0 * (days_since_rain / DRYNESS_FULL_DAYS)


def fire_proximity_normalized(distance_km: float | None) -> float | None:
    """None means the feed is missing. A number means a real distance or 'none nearby' as a large distance is not used.

    Callers pass None when FIRMS is unavailable. They pass a distance when a
    filtered detection exists. No detection in the search box is a normalized
    0, represented by passing a distance beyond NEARBY_FIRE_ZERO_KM or by
    calling with a distance and letting the decay hit zero. Use
    `no_detection_factor` for the explicit empty case.
    """
    if distance_km is None:
        return None
    if distance_km <= NEARBY_FIRE_FULL_KM:
        return 100.0
    if distance_km >= NEARBY_FIRE_ZERO_KM:
        return 0.0
    span = NEARBY_FIRE_ZERO_KM - NEARBY_FIRE_FULL_KM
    return 100.0 * (NEARBY_FIRE_ZERO_KM - distance_km) / span


def no_detection_factor() -> float:
    return 0.0


def band_for(score: int) -> str:
    for threshold, name in RISK_BANDS:
        if score >= threshold:
            return name
    return "Low"


def round_score(value: float) -> int:
    rounded = int(math.floor(value + 0.5))
    return max(0, min(100, rounded))


def weekday_name(day: date) -> str:
    return _WEEKDAYS[day.weekday()]


def alert_text(band: str, day: date, today: date, red_flag: bool) -> str:
    """One line from the highest-risk day.

    The high-risk example the product asks for is
    "High risk Saturday. Clear brush within 30 ft before Friday."
    """
    offset = (day - today).days
    weekday = weekday_name(day)
    if offset <= 0:
        when = "today"
        before = "tonight"
    elif offset == 1:
        when = weekday
        before = "today"
    else:
        when = weekday
        before = weekday_name(day - timedelta(days=1))

    if band == "Low":
        line = f"Low risk through {weekday}. Keep the 5-ft zone clear of mulch and debris."
    elif band == "Moderate":
        line = f"Moderate risk {when}. Walk the 5-ft ember zone and the vents before {before}."
    elif band == "High":
        line = f"High risk {when}. Clear brush within 30 ft before {before}."
    else:
        line = (
            f"Extreme risk {when}. Finish the hardening checklist and be ready to leave before {before}."
        )
    if red_flag:
        line += " A Red Flag Warning is active."
    return line


def _component(
    *,
    key: str,
    label: str,
    available: bool,
    normalized: float | None,
    raw_input: dict[str, Any],
    note: str = "",
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "available": available,
        "raw_input": raw_input,
        "normalized": None if normalized is None else round(normalized, 2),
        "weight": SCORE_WEIGHTS[key],
        "effective_weight": None,
        "contribution": None,
        "note": note,
    }


def score_day(
    *,
    weather: dict[str, float] | None,
    days_since_rain: float | None,
    dryness_note: str,
    closest_fire_km: float | None,
    fire_available: bool,
    fire_note: str,
    red_flag: bool | None,
) -> dict[str, Any]:
    """Blend the available components into one 0–100 score.

    `weather` is {"temp_f", "rh", "wind_mph"} plus optional gust and sustained.
    `closest_fire_km` is ignored when `fire_available` is False.
    `red_flag` None means the alerts feed is missing.
    """
    components: list[dict[str, Any]] = []

    if weather is None:
        components.append(
            _component(
                key="ffwi",
                label="Fosberg Fire Weather Index",
                available=False,
                normalized=None,
                raw_input={},
                note="No afternoon temperature, humidity, and wind for this day.",
            )
        )
    else:
        ffwi = fosberg_ffwi(weather["temp_f"], weather["rh"], weather["wind_mph"])
        components.append(
            _component(
                key="ffwi",
                label="Fosberg Fire Weather Index",
                available=True,
                normalized=ffwi["ffwi"],
                raw_input={
                    "temp_f": round(weather["temp_f"], 1),
                    "rh_pct": round(weather["rh"], 1),
                    "wind_mph": round(weather["wind_mph"], 1),
                    "sustained_wind_mph": weather.get("sustained_mph"),
                    "gust_mph": weather.get("gust_mph"),
                    "emc": round(ffwi["emc"], 2),
                    "eta": round(ffwi["eta"], 4),
                    "ffwi_raw": round(ffwi["ffwi_raw"], 2),
                },
                note="Worst-case afternoon wind is the greater of sustained wind and gust when both exist.",
            )
        )

    if days_since_rain is None:
        components.append(
            _component(
                key="dryness",
                label="Days since meaningful rain",
                available=False,
                normalized=None,
                raw_input={},
                note=dryness_note or "NASA POWER rain history is unavailable.",
            )
        )
    else:
        components.append(
            _component(
                key="dryness",
                label="Days since meaningful rain",
                available=True,
                normalized=dryness_normalized(days_since_rain),
                raw_input={"days_since_meaningful_rain": days_since_rain},
                note=dryness_note,
            )
        )

    if not fire_available:
        components.append(
            _component(
                key="nearby_fire",
                label="Nearby active fire",
                available=False,
                normalized=None,
                raw_input={},
                note=fire_note or "NASA FIRMS is unavailable.",
            )
        )
    else:
        if closest_fire_km is None:
            normalized = no_detection_factor()
            raw: dict[str, Any] = {"closest_km": None}
        else:
            normalized = fire_proximity_normalized(closest_fire_km)
            raw = {"closest_km": round(closest_fire_km, 2)}
        components.append(
            _component(
                key="nearby_fire",
                label="Nearby active fire",
                available=True,
                normalized=normalized,
                raw_input=raw,
                note=fire_note,
            )
        )

    if red_flag is None:
        components.append(
            _component(
                key="red_flag",
                label="Red Flag Warning",
                available=False,
                normalized=None,
                raw_input={},
                note="NWS active alerts are unavailable.",
            )
        )
    else:
        components.append(
            _component(
                key="red_flag",
                label="Red Flag Warning",
                available=True,
                normalized=100.0 if red_flag else 0.0,
                raw_input={"active": red_flag},
                note="Applied only on local days the warning overlaps.",
            )
        )

    available = [item for item in components if item["available"]]
    partial = len(available) < len(components)
    if not available:
        return {
            "score": None,
            "band": None,
            "partial": True,
            "breakdown": components,
        }

    weight_sum = sum(item["weight"] for item in available)
    total = 0.0
    for item in components:
        if not item["available"] or item["normalized"] is None:
            continue
        effective = item["weight"] / weight_sum
        contribution = item["normalized"] * effective
        item["effective_weight"] = round(effective, 4)
        item["contribution"] = round(contribution, 2)
        total += contribution

    score = round_score(total)
    return {
        "score": score,
        "band": band_for(score),
        "partial": partial,
        "breakdown": components,
        "score_unrounded": round(total, 2),
    }
