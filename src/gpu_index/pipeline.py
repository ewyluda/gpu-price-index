"""Collection run: fetch every source, isolate failures, persist, validate."""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from gpu_index import store
from gpu_index.http import make_client
from gpu_index.models import Observation
from gpu_index.sources import ADAPTERS, SourceAdapter, Stamp
from gpu_index.validate import Report, validate

log = logging.getLogger(__name__)


@dataclass
class SourceResult:
    id: str
    name: str
    ok: bool
    rows: int
    seconds: float
    error: str | None = None


@dataclass
class RunResult:
    stamp: Stamp
    sources: list[SourceResult]
    observations: list[Observation]
    report: Report = field(default_factory=Report)

    @property
    def ok(self) -> bool:
        return self.report.ok and all(s.ok for s in self.sources)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.stamp.date,
            "collected_at": self.stamp.collected_at,
            "ok": self.ok,
            "observations": len(self.observations),
            "sources": [asdict(s) for s in self.sources],
            "validation": self.report.to_dict(),
        }


def _run_source(
    adapter: SourceAdapter, client: httpx.Client, stamp: Stamp
) -> tuple[SourceResult, list[Observation]]:
    started = time.perf_counter()
    try:
        rows = adapter.parse(adapter.fetch(client), stamp)
    except Exception as exc:  # one broken source must not sink the others
        log.exception("source %s failed", adapter.id)
        seconds = round(time.perf_counter() - started, 2)
        error = f"{type(exc).__name__}: {exc}"
        return SourceResult(adapter.id, adapter.name, False, 0, seconds, error), []
    seconds = round(time.perf_counter() - started, 2)
    log.info("source %s: %d rows in %.1fs", adapter.id, len(rows), seconds)
    return SourceResult(adapter.id, adapter.name, True, len(rows), seconds), rows


def collect(source_ids: list[str] | None = None, stamp: Stamp | None = None) -> RunResult:
    stamp = stamp or Stamp.now()
    adapters = [ADAPTERS[s] for s in (source_ids or list(ADAPTERS))]

    results: list[SourceResult] = []
    observations: list[Observation] = []
    with make_client() as client:
        for adapter in adapters:
            result, rows = _run_source(adapter, client, stamp)
            results.append(result)
            observations.extend(rows)

    # Only replace sources that succeeded, so a failed fetch keeps any earlier
    # same-day data instead of erasing it.
    succeeded = {r.id for r in results if r.ok}
    store.write_day(stamp.date, observations, replace_sources=succeeded)

    earlier = [d for d in store.dates() if d < stamp.date]
    previous = store.read_day(earlier[-1]) if earlier else []
    report = validate(
        observations,
        previous,
        min_rows={a.id: a.min_rows for a in adapters if a.id in succeeded},
    )
    return RunResult(stamp, results, observations, report)
