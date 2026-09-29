"""The adapter contract every price source implements.

Adapters are split into ``fetch`` (network I/O, returns the raw payload) and ``parse``
(pure function from payload to observations). Tests exercise ``parse`` against
recorded fixtures, so CI never touches the network and upstream format changes show
up as a failing fixture test rather than silently empty data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from gpu_index.models import Observation, Pricing, Segment


@dataclass(frozen=True, slots=True)
class Stamp:
    """When a collection run happened; shared by every observation in the run."""

    date: str
    collected_at: str

    @classmethod
    def now(cls) -> Stamp:
        ts = datetime.now(UTC).replace(microsecond=0)
        return cls(date=ts.date().isoformat(), collected_at=ts.isoformat())


@dataclass(frozen=True, slots=True)
class SourceAdapter:
    id: str
    name: str
    homepage: str
    terms: str  # why we are allowed to use this data
    min_rows: int  # below this, validation treats the run as broken
    fetch: Callable[[httpx.Client], Any]
    parse: Callable[[Any, Stamp], list[Observation]]


def observation(
    stamp: Stamp,
    *,
    source: str,
    provider: str,
    segment: Segment,
    pricing: Pricing,
    gpu_model: str,
    sku: str,
    region: str,
    geo: str,
    gpu_count: int,
    usd_per_hour: float,
    sample_size: int = 1,
) -> Observation:
    """Build an Observation, deriving the normalized per-GPU price."""
    return Observation(
        date=stamp.date,
        collected_at=stamp.collected_at,
        source=source,
        provider=provider,
        segment=segment,
        pricing=pricing,
        gpu_model=gpu_model,
        sku=sku,
        region=region,
        geo=geo,
        gpu_count=gpu_count,
        usd_per_hour=round(usd_per_hour, 4),
        usd_per_gpu_hour=round(usd_per_hour / gpu_count, 4),
        sample_size=sample_size,
    )
