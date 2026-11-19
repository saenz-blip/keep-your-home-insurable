"""National Weather Service forecast grid and active alerts.

`/points/{lat},{lon}` is allowed to 404. That is "no grid here", not a crash:
Alaska, Hawaii, Puerto Rico, and the continental US all have grids, and the
ocean and some border points do not. Afternoon worst-case values come from
the gridpoint time zone.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.constants import AFTERNOON_END_HOUR, AFTERNOON_START_HOUR, FORECAST_DAYS
from app.http_client import FeedHTTPError, get_json

_ISO_DURATION = __import__("re").compile(
    r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$"
)


def fetch_bundle(lat: float, lon: float) -> dict:
    headers = {"Accept": "application/geo+json, application/json", "User-Agent": _user_agent()}
    status, points = get_json(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}", headers=headers)
    if status == 404:
        detail = ""
        if isinstance(points, dict):
            detail = str(points.get("detail") or points.get("title") or "")
        return {"coverage": "none", "detail": detail or "No NWS forecast grid for this point."}
    if status != 200 or not isinstance(points, dict):
        raise FeedHTTPError(f"NWS points returned HTTP {status}")
    properties = points.get("properties") or {}
    grid_url = properties.get("forecastGridData")
    timezone_name = properties.get("timeZone")
    if not grid_url:
        raise FeedHTTPError("NWS points response had no forecast grid URL")
    grid_status, grid = get_json(grid_url, headers=headers)
    if grid_status != 200 or not isinstance(grid, dict):
        raise FeedHTTPError(f"NWS grid returned HTTP {grid_status}")
    alert_status, alerts = get_json(
        "https://api.weather.gov/alerts/active",
        headers=headers,
        params={"point": f"{lat:.4f},{lon:.4f}"},
    )
    if alert_status != 200 or not isinstance(alerts, dict):
        raise FeedHTTPError(f"NWS alerts returned HTTP {alert_status}")
    return {
        "coverage": "ok",
        "timezone": timezone_name,
        "grid": grid,
        "alerts": alerts,
    }


def _user_agent() -> str:
    from app.constants import USER_AGENT

    return USER_AGENT


def parse_duration(text: str) -> timedelta:
    match = _ISO_DURATION.fullmatch(text.strip())
    if not match:
        raise ValueError(f"unsupported duration {text}")
    days, hours, minutes, seconds = (int(part) if part else 0 for part in match.groups())
    return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)


def parse_interval(valid_time: str) -> tuple[datetime, datetime]:
    start_text, _, duration_text = valid_time.partition("/")
    start = datetime.fromisoformat(start_text)
    if start.tzinfo is None:
        raise ValueError("grid time has no offset")
    if not duration_text:
        return start, start + timedelta(hours=1)
    return start, start + parse_duration(duration_text)


def to_fahrenheit(value: float, uom: str | None) -> float:
    unit = (uom or "").lower()
    if "degf" in unit or "[degf]" in unit:
        return value
    return value * 9.0 / 5.0 + 32.0


def to_mph(value: float, uom: str | None) -> float:
    unit = (uom or "").lower()
    if "m_s-1" in unit or "m/s" in unit:
        return value * 2.236936
    if "mph" in unit or "mile_h" in unit:
        return value
    return value * 0.621371


def _in_range(kind: str, value: float) -> bool:
    if kind == "temp":
        return -80.0 <= value <= 140.0
    if kind == "rh":
        return 0.0 <= value <= 100.0
    if kind == "wind":
        return 0.0 <= value <= 200.0
    return False


def aggregate_forecast(bundle: dict, today: date) -> dict:
    """Afternoon max temperature, min RH, and max wind for today and 3 days.

    `today` is the local calendar day at the address. Intervals that only
    cover morning or evening hours are ignored for that day.
    """
    if bundle.get("coverage") != "ok":
        return {
            "timezone": None,
            "dropped": 0,
            "days": [],
            "red_flag_dates": [],
            "alert_names": [],
            "notes": [bundle.get("detail") or "No NWS forecast grid for this point."],
            "covered": False,
        }

    timezone_name = bundle.get("timezone") or "UTC"
    try:
        zone = ZoneInfo(timezone_name)
    except Exception:
        timezone_name = "UTC"
        zone = ZoneInfo("UTC")

    grid_props = (bundle.get("grid") or {}).get("properties") or {}
    dropped = 0
    notes: list[str] = []
    buckets: dict[date, dict[str, list[float]]] = {
        today + timedelta(days=offset): {"temp": [], "rh": [], "wind": [], "gust": []}
        for offset in range(FORECAST_DAYS)
    }

    series = (
        ("temperature", "temp", to_fahrenheit),
        ("relativeHumidity", "rh", lambda value, uom: value),
        ("windSpeed", "wind", to_mph),
        ("windGust", "gust", to_mph),
    )
    for prop_name, kind, convert in series:
        block = grid_props.get(prop_name) or {}
        if prop_name == "windGust" and not block:
            notes.append("Wind gust was not in the NWS grid. The index uses sustained wind.")
        uom = block.get("uom")
        if prop_name != "windGust" and not uom:
            notes.append(f"NWS {prop_name} had no unit. Assumed degrees Celsius or km/h, and percent for humidity.")
        for sample in block.get("values") or []:
            if not isinstance(sample, dict):
                dropped += 1
                continue
            raw = sample.get("value")
            if raw is None:
                dropped += 1
                continue
            try:
                numeric = float(raw)
                start, end = parse_interval(str(sample.get("validTime") or ""))
                converted = convert(numeric, uom)
            except (TypeError, ValueError):
                dropped += 1
                continue
            if not _in_range("wind" if kind == "gust" else kind, converted):
                dropped += 1
                continue
            for day, bucket in buckets.items():
                window_start = datetime(day.year, day.month, day.day, AFTERNOON_START_HOUR, tzinfo=zone)
                window_end = datetime(day.year, day.month, day.day, AFTERNOON_END_HOUR, tzinfo=zone)
                if start < window_end and end > window_start:
                    bucket[kind].append(converted)

    days = []
    for day, bucket in buckets.items():
        weather = None
        missing = [name for name in ("temp", "rh", "wind") if not bucket[name]]
        if not missing:
            sustained = max(bucket["wind"])
            gust = max(bucket["gust"]) if bucket["gust"] else None
            wind = sustained if gust is None else max(sustained, gust)
            weather = {
                "temp_f": max(bucket["temp"]),
                "rh": min(bucket["rh"]),
                "wind_mph": wind,
                "sustained_mph": sustained,
                "gust_mph": gust,
            }
        days.append({"date": day.isoformat(), "weather": weather, "missing": missing})

    red_flag_dates, alert_names, alert_notes = _red_flag_days(bundle.get("alerts") or {}, zone, today)
    notes.extend(alert_notes)
    return {
        "timezone": timezone_name,
        "dropped": dropped,
        "days": days,
        "red_flag_dates": sorted(day.isoformat() for day in red_flag_dates),
        "alert_names": alert_names,
        "notes": notes,
        "covered": True,
    }


def _red_flag_days(alerts: dict, zone: ZoneInfo, today: date) -> tuple[set[date], list[str], list[str]]:
    dates: set[date] = set()
    names: list[str] = []
    notes: list[str] = []
    window = [today + timedelta(days=offset) for offset in range(FORECAST_DAYS)]
    for feature in alerts.get("features") or []:
        props = (feature or {}).get("properties") or {}
        event = str(props.get("event") or "").strip()
        if not event:
            continue
        if event not in names:
            names.append(event)
        if "red flag" not in event.lower():
            continue
        onset = _parse_alert_time(props.get("onset"))
        ends = _parse_alert_time(props.get("ends") or props.get("expires"))
        if onset is None or ends is None:
            dates.update(window)
            notes.append("A Red Flag Warning had no start or end time, so it was applied to every forecast day.")
            continue
        for day in window:
            day_start = datetime(day.year, day.month, day.day, tzinfo=zone)
            day_end = day_start + timedelta(days=1)
            if onset < day_end and ends > day_start:
                dates.add(day)
    return dates, names, notes


def _parse_alert_time(value: object) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed
