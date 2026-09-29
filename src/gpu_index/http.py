"""Shared HTTP client: identifies itself honestly, retries politely, fails loudly."""

from __future__ import annotations

import time
from typing import Any

import httpx

USER_AGENT = "gpu-index/1.0 (+https://github.com/ewyluda/gpu-rental-rate)"
RETRY_STATUSES = {429, 500, 502, 503, 504}


def make_client(timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"},
        timeout=timeout,
        follow_redirects=True,
    )


def get(
    client: httpx.Client,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    attempts: int = 4,
    backoff: float = 2.0,
) -> httpx.Response:
    """GET with exponential backoff on throttling and transient server errors."""
    for attempt in range(1, attempts + 1):
        try:
            response = client.get(url, params=params)
        except httpx.TransportError:
            if attempt == attempts:
                raise
        else:
            if response.status_code not in RETRY_STATUSES or attempt == attempts:
                response.raise_for_status()
                return response
        time.sleep(backoff * 2 ** (attempt - 1))
    raise AssertionError("unreachable")


def post_json(client: httpx.Client, url: str, payload: dict[str, Any]) -> Any:
    response = client.post(url, json=payload)
    response.raise_for_status()
    return response.json()
