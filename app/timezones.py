"""Fallback US time zone when NWS has no grid for the point.

The National Weather Service time zone is preferred. This guess is only used
to label "today" and the next three days when that grid is missing, so Alaska
and Hawaii do not inherit a California clock.
"""

from __future__ import annotations


def fallback_timezone(lat: float, lon: float) -> str:
    if 18.0 <= lat <= 23.5 and -161.0 <= lon <= -154.0:
        return "Pacific/Honolulu"
    if lat >= 51.0 or lon <= -130.0:
        return "America/Anchorage"
    if 17.5 <= lat <= 18.6 and -68.0 <= lon <= -64.0:
        return "America/Puerto_Rico"
    if lon <= -114.0:
        return "America/Los_Angeles"
    if lon <= -101.0:
        return "America/Denver"
    if lon <= -87.0:
        return "America/Chicago"
    return "America/New_York"
