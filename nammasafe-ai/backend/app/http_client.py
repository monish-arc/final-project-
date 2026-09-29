"""Shared HTTP helpers used by live-data provider services.

All external calls are made server-side so credentials never reach the browser.
A single helper keeps timeouts, retries and user-agent policy consistent.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from app.config import OSM_USER_AGENT

DEFAULT_TIMEOUT_SEC = 15.0
DEFAULT_UA = OSM_USER_AGENT


class HttpFetchError(RuntimeError):
    """Raised when an upstream endpoint cannot be reached or rejects the request."""


def http_get(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    headers: Optional[Dict[str, str]] = None,
    max_retries: int = 2,
) -> httpx.Response:
    """GET with small timeout and idempotent retry on transport errors."""
    merged_headers = {"User-Agent": DEFAULT_UA, "Accept": "application/json"}
    if headers:
        merged_headers.update(headers)

    last_error: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            response = httpx.get(
                url,
                params=params,
                headers=merged_headers,
                timeout=timeout,
                follow_redirects=True,
            )
            if response.status_code >= 500:
                last_error = HttpFetchError(f"Upstream {response.status_code} for {url}")
                continue
            return response
        except (httpx.HTTPError, httpx.TimeoutException) as exc:  # pragma: no cover
            last_error = exc
    raise HttpFetchError(f"Request failed for {url}: {last_error}") from last_error


def json_get(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    headers: Optional[Dict[str, str]] = None,
) -> Any:
    response = http_get(url, params=params, timeout=timeout, headers=headers)
    if response.status_code >= 400:
        raise HttpFetchError(f"Rejected ({response.status_code}) by {url}")
    try:
        return response.json()
    except Exception as exc:  # pragma: no cover - non-JSON upstream
        raise HttpFetchError(f"Non-JSON response from {url}") from exc


def _get_follow_redirects(url: str, headers: Dict[str, str], timeout: float) -> httpx.Response:
    """GET following redirects while stripping Authorization on host change.

    Data-provider endpoints (e.g. NASA LP DAAC cloud) redirect to a signed
    object store; the Earthdata bearer token must not be forwarded to a
    different origin.
    """
    current_url = url
    current_headers = dict(headers)
    for _ in range(5):
        response = httpx.get(current_url, headers=current_headers, timeout=timeout, follow_redirects=False)
        if response.status_code not in (301, 302, 303, 307, 308):
            return response
        location = response.headers.get("location")
        if not location:
            raise HttpFetchError(f"Redirect without Location from {current_url}")
        next_url = str(httpx.URL(current_url).join(location))
        if httpx.URL(next_url).host != httpx.URL(current_url).host:
            current_headers = {k: v for k, v in current_headers.items() if k.lower() != "authorization"}
        current_url = next_url
    raise HttpFetchError(f"Too many redirects for {url}")


def http_get_bytes(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    headers: Optional[Dict[str, str]] = None,
    max_retries: int = 2,
) -> httpx.Response:
    """GET raw bytes (binary download) with 5xx retry and safe redirects.

    The caller inspects the returned status code (200 / 401 / 403 / 404 / 5xx);
    providers translate them into their own error vocabulary.
    """
    merged_headers = {"User-Agent": DEFAULT_UA, "Accept": "*/*"}
    if headers:
        merged_headers.update(headers)

    last_error: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            response = _get_follow_redirects(url, headers=merged_headers, timeout=timeout)
            if response.status_code >= 500 and attempt < max_retries:
                last_error = HttpFetchError(f"Upstream {response.status_code} for {url}")
                continue
            return response
        except (httpx.HTTPError, httpx.TimeoutException) as exc:  # pragma: no cover
            last_error = exc
    raise HttpFetchError(f"Request failed for {url}: {last_error}") from last_error