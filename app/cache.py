"""Disk cache for feed responses.

Keys are the feed name plus a rounded location or a normalized query.
A successful fetch overwrites the file. A failed fetch, including a
simulated outage, reads it back and reports the age.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent


class SimulatedOutage(Exception):
    def __init__(self, feed: str):
        super().__init__(f"simulated outage for {feed}")
        self.feed = feed


def cache_dir() -> Path:
    path = Path(os.environ.get("CACHE_DIR", ROOT / "cache"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def location_key(lat: float, lon: float) -> str:
    return f"{lat:.2f}_{lon:.2f}"


def _path(feed: str, key: str) -> Path:
    safe_feed = re.sub(r"[^a-z0-9_-]", "", feed.lower()) or "feed"
    safe_key = re.sub(r"[^A-Za-z0-9._-]", "_", key)[:140] or "key"
    return cache_dir() / f"{safe_feed}__{safe_key}.json"


def write_cache(feed: str, key: str, payload: Any) -> None:
    path = _path(feed, key)
    body = {
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "feed": feed,
        "key": key,
        "payload": payload,
    }
    blob = json.dumps(body).encode("utf-8")
    directory = path.parent
    fd, tmp_name = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(blob)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def read_cache(feed: str, key: str) -> dict[str, Any] | None:
    path = _path(feed, key)
    if not path.exists():
        return None
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        cached_at = datetime.fromisoformat(body["cached_at"])
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - cached_at).total_seconds() / 3600.0
        return {"payload": body["payload"], "age_hours": max(0.0, age_hours), "cached_at": body["cached_at"]}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def age_label(status: str, age_hours: float | None) -> str:
    if status == "live":
        return "live"
    if status != "cached":
        return "unavailable"
    if age_hours is None:
        return "cached"
    if age_hours < 1:
        return "data <1 hour old"
    hours = int(round(age_hours))
    hours = max(1, hours)
    unit = "hour" if hours == 1 else "hours"
    return f"data {hours} {unit} old"


def load_feed(feed: str, key: str, fetcher: Callable[[], Any], *, outages: set[str]) -> dict[str, Any]:
    """Fetch, or fall back to the last cached payload.

    The return value always has status live, cached, or unavailable.
    It does not raise for feed failures.
    """
    error: str | None = None
    if feed in outages:
        error = str(SimulatedOutage(feed))
    else:
        try:
            payload = fetcher()
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__
        else:
            try:
                write_cache(feed, key, payload)
            except OSError:
                # The live payload is still usable if the disk cache cannot be written.
                pass
            return {
                "feed": feed,
                "status": "live",
                "payload": payload,
                "age_hours": 0.0,
                "age_label": "live",
                "error": None,
            }

    cached = read_cache(feed, key)
    if cached is not None:
        return {
            "feed": feed,
            "status": "cached",
            "payload": cached["payload"],
            "age_hours": cached["age_hours"],
            "age_label": age_label("cached", cached["age_hours"]),
            "error": error,
        }
    return {
        "feed": feed,
        "status": "unavailable",
        "payload": None,
        "age_hours": None,
        "age_label": "unavailable",
        "error": error,
    }
