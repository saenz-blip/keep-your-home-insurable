"""NASA FIRMS active-fire detections.

Three VIIRS near-real-time sources are merged. Known refinery circles are
removed first. Low confidence is reported separately and is not used in the
score. Clusters of repeated sub-1 MW nominal detections are treated as
possible static heat and listed, not scored. An empty CSV is a real "no
detections" result.
"""

from __future__ import annotations

import csv
import io
import os
from collections import defaultdict

from app.constants import (
    FIRMS_DAYS,
    FIRMS_SEARCH_RADIUS_KM,
    FIRMS_SOURCES,
    INDUSTRIAL_HEAT_SOURCES,
    LOW_CONFIDENCE_NUMERIC_BELOW,
    STATIC_HEAT_CLUSTER_KM,
    STATIC_HEAT_MAX_FRP_MW,
    STATIC_HEAT_MIN_DETECTIONS,
)
from app.geo import compass_point, haversine_km, km_to_miles
from app.http_client import FeedHTTPError, get_text


def bounding_box(lat: float, lon: float, radius_km: float = FIRMS_SEARCH_RADIUS_KM) -> tuple[float, float, float, float]:
    import math

    dlat = radius_km / 111.0
    cos = math.cos(math.radians(min(89.0, max(-89.0, lat))))
    dlon = radius_km / (111.0 * max(0.2, abs(cos)))
    west = max(-180.0, lon - dlon)
    east = min(180.0, lon + dlon)
    south = max(-90.0, lat - dlat)
    north = min(90.0, lat + dlat)
    return west, south, east, north


def fetch_area(lat: float, lon: float) -> dict:
    key = (os.environ.get("FIRMS_MAP_KEY") or "").strip()
    if not key:
        raise FeedHTTPError("FIRMS_MAP_KEY is not set. Nearby satellite detections were left out of the score.")
    west, south, east, north = bounding_box(lat, lon)
    bbox = f"{west:.4f},{south:.4f},{east:.4f},{north:.4f}"
    tables = []
    errors = []
    for source in FIRMS_SOURCES:
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{bbox}/{FIRMS_DAYS}"
        try:
            status, text = get_text(url, headers={"Accept": "text/csv"})
        except FeedHTTPError as exc:
            errors.append(f"{source}: {exc}")
            continue
        if status != 200:
            errors.append(f"{source}: HTTP {status}")
            continue
        tables.append({"source": source, "csv": text})
    if not tables:
        detail = "; ".join(errors) or "no FIRMS response"
        raise FeedHTTPError(f"FIRMS area request failed ({detail})")
    return {"tables": tables, "source_errors": errors, "bbox": [west, south, east, north]}


def classify_confidence(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in {"l", "low"}:
        return "low"
    if text in {"n", "nominal"}:
        return "nominal"
    if text in {"h", "high"}:
        return "high"
    try:
        number = float(text)
    except ValueError:
        return "unknown"
    if number < LOW_CONFIDENCE_NUMERIC_BELOW:
        return "low"
    if number >= 80:
        return "high"
    return "nominal"


def _float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_csv(text: str) -> tuple[list[dict], int]:
    """Return detections and a count of rows that were dropped as unusable.

    A header-only body, or a completely empty body, is zero detections.
    Anything that is not a FIRMS table is an error, not an empty fire map.
    """
    stripped = (text or "").strip()
    if not stripped:
        return [], 0
    if not stripped.lower().startswith("latitude"):
        raise ValueError("FIRMS did not return a CSV table")
    reader = csv.DictReader(io.StringIO(stripped))
    if not reader.fieldnames or "latitude" not in [name.strip().lower() for name in reader.fieldnames if name]:
        raise ValueError("FIRMS CSV has no latitude column")
    detections = []
    dropped = 0
    for row in reader:
        if not row or all(not (value or "").strip() for value in row.values()):
            continue
        lowered = {(key or "").strip().lower(): value for key, value in row.items()}
        lat = _float(lowered.get("latitude"))
        lon = _float(lowered.get("longitude"))
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            dropped += 1
            continue
        frp = _float(lowered.get("frp"))
        if frp is not None and (frp < 0 or frp > 10000):
            dropped += 1
            continue
        detections.append(
            {
                "lat": lat,
                "lon": lon,
                "frp": frp,
                "confidence": str(lowered.get("confidence") or "").strip(),
                "confidence_class": classify_confidence(lowered.get("confidence")),
                "satellite": str(lowered.get("satellite") or "").strip(),
                "acq_date": str(lowered.get("acq_date") or "").strip(),
                "acq_time": str(lowered.get("acq_time") or "").strip(),
            }
        )
    return detections, dropped


def industrial_match(lat: float, lon: float) -> dict | None:
    for source in INDUSTRIAL_HEAT_SOURCES:
        distance = haversine_km(lat, lon, source["lat"], source["lon"])
        if distance <= source["radius_km"]:
            return source
    return None


def _cluster(points: list[dict], radius_km: float) -> list[list[dict]]:
    parent = list(range(len(points)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[b] = a

    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            if haversine_km(points[i]["lat"], points[i]["lon"], points[j]["lat"], points[j]["lon"]) <= radius_km:
                union(i, j)
    groups: dict[int, list[dict]] = defaultdict(list)
    for index, point in enumerate(points):
        groups[find(index)].append(point)
    return list(groups.values())


def _is_static_cluster(members: list[dict]) -> bool:
    if len(members) < STATIC_HEAT_MIN_DETECTIONS:
        return False
    satellites = set()
    dates = set()
    for member in members:
        if member["confidence_class"] != "nominal":
            return False
        if member["frp"] is None or member["frp"] >= STATIC_HEAT_MAX_FRP_MW:
            return False
        if member["satellite"]:
            satellites.add(member["satellite"])
        if member["acq_date"]:
            dates.add(member["acq_date"])
    return len(satellites) >= 2 or len(dates) >= 2


def analyze(payload: dict, lat: float, lon: float) -> dict:
    """Filter one cached or live FIRMS payload for a home coordinate."""
    detections: list[dict] = []
    invalid = 0
    parse_errors = []
    for table in (payload or {}).get("tables") or []:
        try:
            rows, dropped = parse_csv(table.get("csv") or "")
        except ValueError as exc:
            parse_errors.append(f"{table.get('source')}: {exc}")
            continue
        invalid += dropped
        detections.extend(rows)

    low_confidence = []
    industrial = []
    candidates = []
    for row in detections:
        if row["confidence_class"] == "low":
            low_confidence.append(row)
            continue
        site = industrial_match(row["lat"], row["lon"])
        if site is not None:
            tagged = dict(row)
            tagged["site"] = site["name"]
            industrial.append(tagged)
            continue
        candidates.append(row)

    possible_static = []
    kept = []
    for group in _cluster(candidates, STATIC_HEAT_CLUSTER_KM):
        if _is_static_cluster(group):
            possible_static.extend(group)
        else:
            kept.extend(group)

    def located(row: dict) -> dict:
        distance = haversine_km(lat, lon, row["lat"], row["lon"])
        item = dict(row)
        item["distance_km"] = round(distance, 2)
        item["distance_mi"] = round(km_to_miles(distance), 2)
        item["bearing"] = compass_point(lat, lon, row["lat"], row["lon"])
        return item

    kept_located = sorted((located(row) for row in kept), key=lambda row: row["distance_km"])
    static_located = sorted((located(row) for row in possible_static), key=lambda row: row["distance_km"])
    low_located = sorted((located(row) for row in low_confidence), key=lambda row: row["distance_km"])
    industrial_located = sorted((located(row) for row in industrial), key=lambda row: row["distance_km"])

    by_site: dict[str, int] = defaultdict(int)
    for row in industrial:
        by_site[row["site"]] += 1

    static_clusters = []
    for group in _cluster(static_located, STATIC_HEAT_CLUSTER_KM):
        nearest = min(group, key=lambda row: row["distance_km"])
        frps = [row["frp"] for row in group if row["frp"] is not None]
        static_clusters.append(
            {
                "count": len(group),
                "lat": nearest["lat"],
                "lon": nearest["lon"],
                "distance_km": nearest["distance_km"],
                "distance_mi": nearest["distance_mi"],
                "bearing": nearest["bearing"],
                "max_frp": None if not frps else round(max(frps), 2),
                "satellites": sorted({row["satellite"] for row in group if row["satellite"]}),
                "reason": (
                    f"{len(group)} nominal-confidence detections under {STATIC_HEAT_MAX_FRP_MW} MW, "
                    "seen on more than one satellite or day. Treated as possible static heat and left out of the score."
                ),
            }
        )
    static_clusters.sort(key=lambda row: row["distance_km"])

    notes = []
    if by_site:
        detail = ", ".join(f"{name}: {count}" for name, count in sorted(by_site.items()))
        notes.append(f"Filtered {len(industrial)} detections inside known industrial sites ({detail}).")
    if low_confidence:
        notes.append(f"{len(low_confidence)} low-confidence detections were listed separately and left out of the score.")
    if static_clusters:
        notes.append(
            f"{len(possible_static)} detections in {len(static_clusters)} clusters look like persistent "
            f"low-FRP nominal heat and were left out of the score."
        )
    if invalid:
        notes.append(f"Dropped {invalid} FIRMS rows with missing coordinates or impossible FRP.")
    source_errors = (payload or {}).get("source_errors") or []
    notes.extend(source_errors)
    notes.extend(parse_errors)
    if not kept_located and not notes:
        notes.append("No active FIRMS detections in the search area.")
    elif not kept_located:
        notes.append("No FIRMS detections left to score after filtering.")

    closest = kept_located[0] if kept_located else None
    return {
        "raw_count": len(detections),
        "dropped_invalid": invalid,
        "low_confidence_count": len(low_confidence),
        "industrial_count": len(industrial),
        "industrial_by_site": [{"name": name, "count": count} for name, count in sorted(by_site.items())],
        "industrial_points": industrial_located,
        "possible_static_count": len(possible_static),
        "possible_static": static_clusters,
        "kept_count": len(kept_located),
        "kept": kept_located,
        "low_confidence": low_located[:8],
        "low_confidence_points": low_located,
        "closest": closest,
        "notes": notes,
        "source_errors": source_errors,
    }
