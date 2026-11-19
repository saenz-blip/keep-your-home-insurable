"""Distance and compass bearing on a sphere."""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0
_COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
KM_PER_MILE = 1.609344


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def bearing_degrees(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial compass bearing in degrees, 0 = north, clockwise."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlmb = math.radians(lon2 - lon1)
    y = math.sin(dlmb) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlmb)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def compass_point(lat1: float, lon1: float, lat2: float, lon2: float) -> str:
    degrees = bearing_degrees(lat1, lon1, lat2, lon2)
    index = int((degrees + 22.5) // 45) % 8
    return _COMPASS[index]


def km_to_miles(km: float) -> float:
    return km / KM_PER_MILE
