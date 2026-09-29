"""Data-quality gates run after every collection.

Errors mean the data is wrong or a source is broken, and fail the pipeline, which
opens a GitHub issue. Warnings (big day-over-day moves) are published on the status
page but don't block, because real prices do sometimes move sharply.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from gpu_index.catalog import GPUS
from gpu_index.models import PRICING, SEGMENTS, Observation

MIN_USD_PER_GPU_HOUR = 0.05
MAX_USD_PER_GPU_HOUR = 100.0
DRIFT_THRESHOLD = 0.40


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, list[str]]:
        return {"errors": self.errors, "warnings": self.warnings}


def check_rows(rows: list[Observation], report: Report) -> None:
    for o in rows:
        where = f"{o.source}/{o.sku}/{o.region}"
        if o.gpu_model not in GPUS:
            report.errors.append(f"{where}: unknown gpu_model {o.gpu_model!r}")
        if o.segment not in SEGMENTS or o.pricing not in PRICING:
            report.errors.append(f"{where}: invalid segment/pricing {o.segment}/{o.pricing}")
        if o.gpu_count < 1:
            report.errors.append(f"{where}: gpu_count {o.gpu_count} < 1")
        if not MIN_USD_PER_GPU_HOUR <= o.usd_per_gpu_hour <= MAX_USD_PER_GPU_HOUR:
            report.errors.append(
                f"{where}: ${o.usd_per_gpu_hour}/GPU-hr outside "
                f"[{MIN_USD_PER_GPU_HOUR}, {MAX_USD_PER_GPU_HOUR}]"
            )


def check_volume(rows: list[Observation], min_rows: dict[str, int], report: Report) -> None:
    counts: dict[str, int] = defaultdict(int)
    for o in rows:
        counts[o.source] += 1
    for source, minimum in min_rows.items():
        if counts[source] < minimum:
            report.errors.append(
                f"{source}: {counts[source]} rows, expected at least {minimum} "
                "(upstream format change or outage?)"
            )


def _medians(rows: list[Observation]) -> dict[tuple[str, str, str], float]:
    groups: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for o in rows:
        groups[(o.provider, o.gpu_model, o.pricing)].append(o.usd_per_gpu_hour)
    return {k: statistics.median(v) for k, v in groups.items()}


def check_drift(previous: list[Observation], current: list[Observation], report: Report) -> None:
    before, after = _medians(previous), _medians(current)
    for key in sorted(before.keys() & after.keys()):
        old, new = before[key], after[key]
        change = (new - old) / old
        if abs(change) > DRIFT_THRESHOLD:
            provider, gpu, pricing = key
            report.warnings.append(
                f"{provider} {gpu} {pricing}: median moved {change:+.0%} "
                f"(${old:.2f} -> ${new:.2f}/GPU-hr)"
            )


def validate(
    current: list[Observation],
    previous: list[Observation],
    min_rows: dict[str, int],
) -> Report:
    report = Report()
    check_rows(current, report)
    check_volume(current, min_rows, report)
    check_drift(previous, current, report)
    return report
