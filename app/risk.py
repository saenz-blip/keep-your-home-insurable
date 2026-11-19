"""Turn an address into a scored report.

Feed failures stay inside the report. The only exceptions are lookup problems
the page can explain: an empty query, no US match, or more than one place.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.cache import load_feed, location_key
from app.constants import (
    CHECKLIST,
    DISCLAIMER,
    FORECAST_DAYS,
    SCORE_WEIGHTS,
    STATIC_HEAT_MAX_FRP_MW,
)
from app.feeds.firms import analyze, fetch_area
from app.feeds.nominatim import classify, search
from app.feeds.nws import aggregate_forecast, fetch_bundle
from app.feeds.power import fetch_point, summarize
from app.feeds.wfigs import attach, fetch_incidents, parse_incidents
from app.scoring import alert_text, proximity_floor, score_day, weekday_name
from app.timezones import fallback_timezone

_FEED_LABELS = {
    "nominatim": "OpenStreetMap Nominatim",
    "nws": "National Weather Service",
    "power": "NASA POWER",
    "firms": "NASA FIRMS",
    "wfigs": "NIFC WFIGS",
}


class LookupProblem(Exception):
    def __init__(self, message: str, error: str = "lookup", candidates: list | None = None):
        super().__init__(message)
        self.message = message
        self.error = error
        self.candidates = candidates or []


def outage_names(query: str | None) -> set[str]:
    names: set[str] = set()
    for raw in (os.environ.get("SIMULATE_OUTAGE", ""), query or ""):
        for part in raw.split(","):
            part = part.strip().lower()
            if part:
                names.add(part)
    return names


def gibs_urls(lat: float, lon: float, today: date) -> list[dict]:
    """VIIRS true-color snapshots. The newest day is often not posted yet."""
    half = 0.42
    south = max(-90.0, lat - half)
    north = min(90.0, lat + half)
    west = max(-180.0, lon - half)
    east = min(180.0, lon + half)
    urls = []
    for lag in (1, 2, 3):
        day = today - timedelta(days=lag)
        urls.append(
            {
                "date": day.isoformat(),
                "url": (
                    "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
                    "?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap"
                    "&LAYERS=VIIRS_SNPP_CorrectedReflectance_TrueColor"
                    "&STYLES=&FORMAT=image/jpeg&CRS=EPSG:4326"
                    f"&BBOX={south:.4f},{west:.4f},{north:.4f},{east:.4f}"
                    "&WIDTH=1024&HEIGHT=1024"
                    f"&TIME={day.isoformat()}"
                ),
            }
        )
    return urls


def _view(load: dict, dropped: int, notes: list[str]) -> dict:
    return {
        "id": load["feed"],
        "label": _FEED_LABELS.get(load["feed"], load["feed"]),
        "status": load["status"],
        "age_hours": None if load["age_hours"] is None else round(load["age_hours"], 2),
        "age_label": load["age_label"],
        "dropped": dropped,
        "notes": notes,
        "error": load["error"],
    }


def evaluate(
    address: str | None,
    lat: float | None,
    lon: float | None,
    simulate: str | None,
) -> dict:
    outages = outage_names(simulate)
    query = " ".join((address or "").split())
    if lat is None and lon is None and not query:
        raise LookupProblem("Enter a US address.", "bad_request")
    if (lat is None) ^ (lon is None):
        raise LookupProblem("Pass both latitude and longitude, or an address.", "bad_request")
    if lat is not None and lon is not None:
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise LookupProblem("That coordinate is off the map.", "bad_request")

    geocode_view = None
    if lat is None or lon is None:
        assert query
        loaded = load_feed(
            "nominatim",
            query.lower(),
            lambda: search(query),
            outages=outages,
        )
        if loaded["payload"] is None:
            raise LookupProblem(
                "OpenStreetMap did not answer, and there is no saved lookup for that address. Nothing was guessed.",
                "geocoder_down",
            )
        choice = classify(loaded["payload"])
        geocode_view = _view(loaded, 0, [])
        if choice["status"] == "none":
            raise LookupProblem(choice["message"], "not_found")
        if choice["status"] == "ambiguous":
            raise LookupProblem(choice["message"], "ambiguous", choice["candidates"])
        hit = choice["candidates"][0]
        lat = hit["lat"]
        lon = hit["lon"]
        label = hit["label"]
    else:
        label = query or f"{lat:.4f}, {lon:.4f}"

    tz_name = fallback_timezone(lat, lon)
    try:
        today = datetime.now(ZoneInfo(tz_name)).date()
    except Exception:
        tz_name = "UTC"
        today = datetime.now(ZoneInfo("UTC")).date()

    key = location_key(lat, lon)

    def _nws():
        return fetch_bundle(lat, lon)

    def _power():
        return fetch_point(lat, lon, today)

    def _firms():
        return fetch_area(lat, lon)

    def _wfigs():
        return fetch_incidents(lat, lon)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            "nws": pool.submit(load_feed, "nws", key, _nws, outages=outages),
            "power": pool.submit(load_feed, "power", key, _power, outages=outages),
            "firms": pool.submit(load_feed, "firms", key, _firms, outages=outages),
            "wfigs": pool.submit(load_feed, "wfigs", key, _wfigs, outages=outages),
        }
        loaded = {name: future.result() for name, future in futures.items()}

    nws_bundle = loaded["nws"]["payload"] if isinstance(loaded["nws"]["payload"], dict) else None
    if nws_bundle and nws_bundle.get("coverage") == "ok" and nws_bundle.get("timezone"):
        try:
            zone_today = datetime.now(ZoneInfo(nws_bundle["timezone"])).date()
        except Exception:
            zone_today = today
        else:
            today = zone_today
            tz_name = nws_bundle["timezone"]

    try:
        forecast = aggregate_forecast(nws_bundle or {"coverage": "none", "detail": "No NWS response."}, today)
    except Exception as exc:
        forecast = {
            "timezone": tz_name,
            "dropped": 0,
            "days": [],
            "red_flag_dates": [],
            "alert_names": [],
            "notes": [f"The NWS grid could not be read ({exc})."],
            "covered": False,
        }
    if not forecast["days"]:
        forecast["days"] = [
            {"date": (today + timedelta(days=offset)).isoformat(), "weather": None, "missing": ["temp", "rh", "wind"]}
            for offset in range(FORECAST_DAYS)
        ]

    power_summary = {
        "available": False,
        "days_since_rain": None,
        "dropped": 0,
        "notes": ["NASA POWER did not return rain history."],
    }
    if isinstance(loaded["power"]["payload"], dict):
        try:
            power_summary = summarize(loaded["power"]["payload"], today)
        except Exception as exc:
            power_summary = {
                "available": False,
                "days_since_rain": None,
                "dropped": 0,
                "notes": [f"NASA POWER could not be read ({exc})."],
            }

    firms_summary = None
    firms_notes = []
    if loaded["firms"]["status"] == "unavailable":
        firms_notes = [loaded["firms"]["error"] or "NASA FIRMS is unavailable."]
    elif isinstance(loaded["firms"]["payload"], dict):
        try:
            firms_summary = analyze(loaded["firms"]["payload"], lat, lon)
            firms_notes = firms_summary["notes"]
        except Exception as exc:
            firms_notes = [f"FIRMS detections could not be read ({exc})."]
            firms_summary = None

    incidents: list[dict] = []
    wfigs_notes: list[str] = []
    if loaded["wfigs"]["status"] == "unavailable":
        wfigs_notes = [loaded["wfigs"]["error"] or "NIFC incident names are unavailable."]
    elif isinstance(loaded["wfigs"]["payload"], dict):
        try:
            incidents = parse_incidents(loaded["wfigs"]["payload"], lat, lon)
            if not incidents:
                wfigs_notes.append("No current NIFC incident inside 70 km.")
            else:
                wfigs_notes.append(f"{len(incidents)} current NIFC incident{'s' if len(incidents) != 1 else ''} inside 70 km.")
        except Exception as exc:
            wfigs_notes = [f"NIFC incidents could not be read ({exc})."]

    if firms_summary is not None and incidents:
        attach(firms_summary["kept"], incidents)
        if firms_summary["closest"] is not None:
            # analyze() built closest before attachment; copy the matched name across.
            nearest = firms_summary["kept"][0]
            firms_summary["closest"] = nearest

    days_since = power_summary.get("days_since_rain") if power_summary.get("available") else None
    dryness_note = " ".join(power_summary.get("notes") or [])
    fire_available = firms_summary is not None
    closest_km = None
    floor_distance_km = None
    nearby_alert = None
    fire_note = " ".join(firms_notes)
    if fire_available:
        closest = firms_summary["closest"]
        if closest is None:
            closest_km = None
        else:
            closest_km = closest["distance_km"]
            incident = closest.get("incident")
            if incident:
                acres = incident.get("acres")
                contained = incident.get("percent_contained")
                extra = incident["type_label"]
                if acres is not None:
                    extra += f", {acres:g} acres"
                if contained is not None:
                    extra += f", {contained:g}% contained"
                fire_note = (
                    f"Closest detection is {closest['distance_km']} km {closest['bearing']}, "
                    f"matched to {incident['name']} ({extra}). "
                ) + fire_note
        qualifying = [
            row
            for row in firms_summary["kept"]
            if row.get("frp") is not None and row["frp"] >= STATIC_HEAT_MAX_FRP_MW
        ]
        if qualifying:
            floor_distance_km = qualifying[0]["distance_km"]
            if proximity_floor(floor_distance_km) > 0:
                incident = qualifying[0].get("incident") or {}
                category = str(incident.get("type") or "").upper()
                if category == "WF":
                    kind = "wildfire"
                elif category == "RX":
                    kind = "prescribed"
                else:
                    kind = "fire"
                nearby_alert = {
                    "distance_km": floor_distance_km,
                    "bearing": qualifying[0].get("bearing") or "",
                    "name": incident.get("name"),
                    "kind": kind,
                }

    red_flag_known = bool(forecast.get("covered")) and loaded["nws"]["status"] != "unavailable"
    red_flag_dates = set(forecast.get("red_flag_dates") or [])

    day_rows = []
    for offset, day_forecast in enumerate(forecast["days"][:FORECAST_DAYS]):
        day = date.fromisoformat(day_forecast["date"])
        scored = score_day(
            weather=day_forecast.get("weather"),
            days_since_rain=days_since,
            dryness_note=dryness_note,
            closest_fire_km=closest_km,
            fire_available=fire_available,
            fire_note=fire_note,
            red_flag=(day.isoformat() in red_flag_dates) if red_flag_known else None,
            floor_distance_km=floor_distance_km if fire_available else None,
        )
        if offset == 0:
            day_label = "Today"
        elif offset == 1:
            day_label = "Tomorrow"
        else:
            day_label = weekday_name(day)
        day_rows.append(
            {
                "date": day.isoformat(),
                "label": day_label,
                "weekday": weekday_name(day),
                "offset": offset,
                **scored,
            }
        )

    ranked = [row for row in day_rows if row.get("score") is not None]
    best = ranked[0] if ranked else None
    for row in ranked[1:]:
        if row["score"] > best["score"]:
            best = row

    partial_reasons = []
    if not forecast.get("covered"):
        partial_reasons.append(forecast["notes"][0] if forecast.get("notes") else "No NWS forecast grid for this point.")
    elif loaded["nws"]["status"] == "unavailable":
        partial_reasons.append("National Weather Service data is unavailable and nothing was cached.")
    if not power_summary.get("available"):
        partial_reasons.append(power_summary["notes"][-1] if power_summary.get("notes") else "Rain history is unavailable.")
    if not fire_available:
        partial_reasons.append(firms_notes[0] if firms_notes else "Satellite fire detections are unavailable.")
    if loaded["wfigs"]["status"] == "unavailable":
        partial_reasons.append(wfigs_notes[0])

    ffwi_ready = False
    if best is not None:
        ffwi = next((item for item in best["breakdown"] if item["key"] == "ffwi"), None)
        ffwi_ready = bool(ffwi and ffwi.get("available"))

    if best is None:
        alert = "Not enough public data to estimate a score. Nothing was filled in."
        score = None
        band = None
        partial = True
    elif not ffwi_ready:
        alert = "Partial estimate. Afternoon fire weather is missing, so this is not a full score."
        score = best["score"]
        band = best["band"]
        partial = True
    else:
        window_end = date.fromisoformat(day_rows[-1]["date"]) if day_rows else today
        alert = alert_text(
            best["band"],
            date.fromisoformat(best["date"]),
            today,
            red_flag=best["date"] in red_flag_dates,
            window_end=window_end,
            nearby=nearby_alert,
        )
        score = best["score"]
        band = best["band"]
        partial = bool(best["partial"] or partial_reasons or any(row["partial"] for row in day_rows))

    feeds = []
    if geocode_view:
        feeds.append(geocode_view)
    feeds.append(_view(loaded["nws"], forecast.get("dropped") or 0, forecast.get("notes") or []))
    feeds.append(_view(loaded["power"], power_summary.get("dropped") or 0, power_summary.get("notes") or []))
    feeds.append(
        _view(
            loaded["firms"],
            (firms_summary or {}).get("dropped_invalid") or 0,
            firms_notes,
        )
    )
    feeds.append(_view(loaded["wfigs"], 0, wfigs_notes))

    cached_bits = [f"{feed['label']}: {feed['age_label']}" for feed in feeds if feed["status"] == "cached"]
    banner = ""
    if cached_bits:
        banner = "Live feed unavailable. Showing saved data. " + " · ".join(cached_bits)

    kept = (firms_summary or {}).get("kept") or []
    return {
        "ok": True,
        "disclaimer": DISCLAIMER,
        "address": {"query": query, "label": label, "lat": lat, "lon": lon},
        "timezone": tz_name,
        "today": today.isoformat(),
        "score": score,
        "band": band,
        "alert": alert,
        "partial": partial,
        "partial_reasons": partial_reasons,
        "highest_risk_day": None if best is None else best["date"],
        "banner": banner,
        "days": day_rows,
        "weights": SCORE_WEIGHTS,
        "fires": kept[:12],
        "fire_summary": {
            "raw_count": (firms_summary or {}).get("raw_count", 0),
            "dropped_invalid": (firms_summary or {}).get("dropped_invalid", 0),
            "low_confidence_count": (firms_summary or {}).get("low_confidence_count", 0),
            "industrial_count": (firms_summary or {}).get("industrial_count", 0),
            "industrial_by_site": (firms_summary or {}).get("industrial_by_site", []),
            "possible_static_count": (firms_summary or {}).get("possible_static_count", 0),
            "possible_static": (firms_summary or {}).get("possible_static", []),
            "industrial_points": (firms_summary or {}).get("industrial_points", []),
            "low_confidence_points": (firms_summary or {}).get("low_confidence_points", []),
            "kept": kept,
            "kept_count": (firms_summary or {}).get("kept_count", 0),
            "closest": (firms_summary or {}).get("closest"),
            "available": fire_available,
        },
        "low_confidence": (firms_summary or {}).get("low_confidence") or [],
        "incidents": incidents[:8],
        "feeds": feeds,
        "checklist": list(CHECKLIST),
        "scene": gibs_urls(lat, lon, today),
        "alert_names": forecast.get("alert_names") or [],
    }
