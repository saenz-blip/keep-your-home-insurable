"""Outbound HTTP with a timeout and retries.

Every feed goes through here. Simulated outages are raised by the cache
loader before this module is called, so a demo outage does not hit the network.
"""

from __future__ import annotations

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.constants import USER_AGENT

TIMEOUT = httpx.Timeout(15.0, connect=5.0)
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class FeedHTTPError(Exception):
    """A feed answered with a failure we should not retry, or retries ran out."""


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in RETRYABLE_STATUS:
        return True
    return False


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.4, min=0.4, max=4),
    retry=retry_if_exception(_retryable),
)
def request(url: str, *, headers: dict[str, str] | None = None, params: dict | None = None) -> httpx.Response:
    merged = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        merged.update(headers)
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        response = client.get(url, headers=merged, params=params)
        if response.status_code in RETRYABLE_STATUS:
            response.raise_for_status()
        return response


def get_json(url: str, *, headers: dict[str, str] | None = None, params: dict | None = None) -> tuple[int, object]:
    try:
        response = request(url, headers=headers, params=params)
    except httpx.HTTPStatusError as exc:
        raise FeedHTTPError(f"request failed ({exc.response.status_code})") from exc
    except httpx.HTTPError as exc:
        raise FeedHTTPError(f"request failed ({exc.__class__.__name__})") from exc
    try:
        return response.status_code, response.json()
    except ValueError as exc:
        raise FeedHTTPError("response was not JSON") from exc


def get_text(url: str, *, headers: dict[str, str] | None = None, params: dict | None = None) -> tuple[int, str]:
    try:
        response = request(url, headers=headers, params=params)
    except httpx.HTTPStatusError as exc:
        raise FeedHTTPError(f"request failed ({exc.response.status_code})") from exc
    except httpx.HTTPError as exc:
        raise FeedHTTPError(f"request failed ({exc.__class__.__name__})") from exc
    return response.status_code, response.text
