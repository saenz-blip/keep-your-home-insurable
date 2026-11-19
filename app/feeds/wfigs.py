"""NIFC WFIGS current incidents.

Public ArcGIS query, no key. Used to put a name, a WF/RX label, acres, and
percent contained on the nearest FIRMS cluster. A prescribed burn stays in
the satellite list; it is labeled, not deleted and not silently treated as a
wildfire.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.constants import WFIGS_ATTACH_KM, WFIGS_QUERY, WFIGS_SEARCH_RADIUS_KM
from app.geo import compass_point, haversine_km, km_to_miles
from app.http_client import FeedHTTPError, get_json

_TYPE_LABELS = {
    "WF": "Wildfire",
    "RX": "Prescribed burn",
}


def fetch_incidents(lat: float, lon: float) -> dict:
    status, payload = get_json(
        WFIGS_QUERY,
        params={
            "f": "json",
            "where": "1=1",
            "outFields": (
                "IncidentName,IncidentTypeCategory,IncidentSize,PercentContained,"
                "FireDiscoveryDateTime,POOState,POOCounty,InitialLatitude,InitialLongitude"
            ),
            "returnGeometry": "true",
            "outSR": "4326",
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "distance": str(int(WFIGS_SEARCH_RADIUS_KM)),
            "units": "esriSRUnit_Kilometer",
            "geometry": f"{lon:.5f},{lat:.5f}",
        },
    )
    if status != 200 or not isinstance(payload, dict):
        raise FeedHTTPError(f"NIFC WFIGS returned HTTP {status}")
    if payload.get("error"):
        message = payload["error"].get("message") if isinstance(payload["error"], dict) else str(payload["error"])
        raise FeedHTTPError(f"NIFC WFIGS query failed ({message})")
    return payload


def _discovered(value: object) -> str | None:
    if value is None or value == "":
        return None
    try:
        millis = float(value)
    except (TypeError, ValueError):
        return str(value)
    # ArcGIS usually returns epoch milliseconds.
    if millis > 10_000_000_000:
        millis = millis / 1000.0
    try:
        return datetime.fromtimestamp(millis, tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _number(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_incidents(payload: dict, lat: float, lon: float) -> list[dict]:
    incidents = []
    for feature in (payload or {}).get("features") or []:
        if not isinstance(feature, dict):
            continue
        attrs = feature.get("attributes") or {}
        geom = feature.get("geometry") or {}
        point_lon = _number(geom.get("x"))
        point_lat = _number(geom.get("y"))
        if point_lat is None or point_lon is None:
            point_lat = _number(attrs.get("InitialLatitude"))
            point_lon = _number(attrs.get("InitialLongitude"))
        if point_lat is None or point_lon is None:
            continue
        if not (-90 <= point_lat <= 90 and -180 <= point_lon <= 180):
            continue
        category = str(attrs.get("IncidentTypeCategory") or "").strip().upper()
        distance = haversine_km(lat, lon, point_lat, point_lon)
        incidents.append(
            {
                "name": attrs.get("IncidentName") or "Unnamed incident",
                "type": category or None,
                "type_label": _TYPE_LABELS.get(category, category or "Incident"),
                "acres": _number(attrs.get("IncidentSize")),
                "percent_contained": _number(attrs.get("PercentContained")),
                "discovered": _discovered(attrs.get("FireDiscoveryDateTime")),
                "state": attrs.get("POOState"),
                "county": attrs.get("POOCounty"),
                "lat": point_lat,
                "lon": point_lon,
                "distance_km": round(distance, 2),
                "distance_mi": round(km_to_miles(distance), 2),
                "bearing": compass_point(lat, lon, point_lat, point_lon),
            }
        )
    incidents.sort(key=lambda item: item["distance_km"])
    return incidents


def attach(detections: list[dict], incidents: list[dict]) -> None:
    """Copy the nearest incident within WFIGS_ATTACH_KM onto each detection."""
    for detection in detections:
        nearest = None
        nearest_distance = None
        for incident in incidents:
            distance = haversine_km(detection["lat"], detection["lon"], incident["lat"], incident["lon"])
            if distance <= WFIGS_ATTACH_KM and (nearest_distance is None or distance < nearest_distance):
                nearest = incident
                nearest_distance = distance
        detection["incident"] = None if nearest is None else _public_incident(nearest)


def _public_incident(incident: dict) -> dict:
    return {
        "name": incident["name"],
        "type": incident["type"],
        "type_label": incident["type_label"],
        "acres": incident["acres"],
        "percent_contained": incident["percent_contained"],
        "discovered": incident["discovered"],
        "distance_km": incident["distance_km"],
        "bearing": incident["bearing"],
    }
