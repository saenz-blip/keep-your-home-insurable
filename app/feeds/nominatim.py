"""OpenStreetMap Nominatim geocoding.

US results only (`countrycodes=us`). At most one request per second.
Zero matches and genuinely different matches are returned to the caller;
they are not turned into a guessed coordinate.
"""

from __future__ import annotations

import threading
import time

from app.constants import GEOCODE_AMBIGUOUS_KM, USER_AGENT
from app.geo import haversine_km
from app.http_client import FeedHTTPError, get_json

_LOCK = threading.Lock()
_NEXT_AT = 0.0
SEARCH_URL = "https://nominatim.openstreetmap.org/search"


def _wait_turn() -> None:
    global _NEXT_AT
    with _LOCK:
        now = time.monotonic()
        if now < _NEXT_AT:
            time.sleep(_NEXT_AT - now)
        _NEXT_AT = time.monotonic() + 1.05


def search(query: str) -> list[dict]:
    text = " ".join(query.split())
    if not text:
        return []
    _wait_turn()
    status, payload = get_json(
        SEARCH_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        params={
            "q": text,
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": 5,
            "countrycodes": "us",
        },
    )
    if status != 200 or not isinstance(payload, list):
        raise FeedHTTPError(f"Nominatim returned HTTP {status}")
    cleaned = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        country = ((row.get("address") or {}).get("country_code") or "").lower()
        # jsonv2 includes addressdetails; if the country is present and not US, drop it.
        if country and country != "us":
            continue
        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        cleaned.append(
            {
                "label": row.get("display_name") or text,
                "lat": lat,
                "lon": lon,
                "locality": _locality(row.get("address")),
            }
        )
    return cleaned


def _locality(address: object) -> str:
    if not isinstance(address, dict):
        return ""
    for key in ("city", "town", "village", "hamlet", "municipality"):
        value = address.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


def did_you_mean(query: str, locality: str, match_count: int) -> bool:
    """True when the typed text is a loose match for the place we kept.

    Multiple Nominatim hits, or a city/town that the user never typed.
    """
    if match_count > 1:
        return True
    place = " ".join((locality or "").split())
    if not place:
        return False
    typed = " ".join((query or "").split()).casefold()
    return place.casefold() not in typed


def classify(results: list[dict]) -> dict:
    """Turn a Nominatim list into one hit, no hit, or an ambiguous set.

    Places within GEOCODE_AMBIGUOUS_KM of the first hit are the same place
    (a street and a building on it). Anything farther is a different candidate.
    """
    if not results:
        return {
            "status": "none",
            "message": "No US match for that address in OpenStreetMap. Try a street, city, and state.",
            "candidates": [],
        }
    first = results[0]
    distinct = [first]
    for other in results[1:]:
        distance = haversine_km(first["lat"], first["lon"], other["lat"], other["lon"])
        if distance > GEOCODE_AMBIGUOUS_KM:
            distinct.append(other)
    if len(distinct) > 1:
        return {
            "status": "ambiguous",
            "message": "That matches more than one place in the US. Pick one.",
            "candidates": distinct,
        }
    return {"status": "one", "message": "", "candidates": [first]}
