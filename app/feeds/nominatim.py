"""OpenStreetMap Nominatim geocoding, with a US Census geocoder fallback.

If Nominatim errors or takes longer than 3 seconds, the free US Census
one-line geocoder (no key) is tried instead.

US results only (`countrycodes=us`). At most one request per second.
Zero matches and genuinely different matches are returned to the caller;
they are not turned into a guessed coordinate.
"""

from __future__ import annotations

import logging
import threading
import time

import httpx

from app.constants import GEOCODE_AMBIGUOUS_KM, USER_AGENT
from app.geo import haversine_km
from app.http_client import FeedHTTPError

_LOCK = threading.Lock()
_NEXT_AT = 0.0
SEARCH_URL = "https://nominatim.openstreetmap.org/search"
CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
NOMINATIM_TIMEOUT_S = 3.0
CENSUS_TIMEOUT_S = 8.0
logger = logging.getLogger(__name__)


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
    try:
        payload = _nominatim(text)
    except Exception as exc:  # noqa: BLE001 - any Nominatim failure falls back
        logger.warning("Nominatim failed (%s); trying the US Census geocoder", exc.__class__.__name__)
        return census_search(text)
    return _clean_nominatim(payload, text)


def _nominatim(text: str) -> list:
    _wait_turn()
    try:
        with httpx.Client(timeout=NOMINATIM_TIMEOUT_S, follow_redirects=True) as client:
            response = client.get(
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
    except httpx.HTTPError as exc:
        raise FeedHTTPError(f"Nominatim request failed ({exc.__class__.__name__})") from exc
    if response.status_code != 200:
        raise FeedHTTPError(f"Nominatim returned HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise FeedHTTPError("Nominatim response was not JSON") from exc
    if not isinstance(payload, list):
        raise FeedHTTPError("Nominatim response was not a list")
    return payload


def census_search(text: str) -> list[dict]:
    """US Census one-line geocoder. Raises FeedHTTPError if it also fails."""
    try:
        with httpx.Client(timeout=CENSUS_TIMEOUT_S, follow_redirects=True) as client:
            response = client.get(
                CENSUS_URL,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                params={"address": text, "benchmark": "Public_AR_Current", "format": "json"},
            )
    except httpx.HTTPError as exc:
        raise FeedHTTPError(f"Census geocoder request failed ({exc.__class__.__name__})") from exc
    if response.status_code != 200:
        raise FeedHTTPError(f"Census geocoder returned HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError as exc:
        raise FeedHTTPError("Census geocoder response was not JSON") from exc
    matches = ((body or {}).get("result") or {}).get("addressMatches") or []
    out = []
    for match in matches[:5]:
        coords = (match or {}).get("coordinates") or {}
        try:
            lon = float(coords["x"])
            lat = float(coords["y"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        parts = (match.get("addressComponents") or {})
        city = " ".join(str(parts.get("city") or "").split()).title()
        out.append(
            {
                "label": match.get("matchedAddress") or text,
                "lat": lat,
                "lon": lon,
                "locality": city,
            }
        )
    return out


def _clean_nominatim(payload: list, text: str) -> list[dict]:
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
