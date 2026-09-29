"""Data-quality gates, applied before anything is stored or published.

- Rows failing schema or price-bounds checks are dropped and reported as errors.
- A source returning fewer valid rows than its minimum is treated as failed: its rows
  are not written, so a half-broken parser can't replace yesterday's good data.
- Day-over-day moves above the drift threshold, and providers that disappear, are
  published as warnings: real prices do move, but a silent outage must be visible.

Errors fail the pipeline, which opens a GitHub issue.
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


def row_problem(o: Observation) -> str | None:
    """Why a row is invalid, or None if it passes schema and bounds checks."""
    where = f"{o.source}/{o.sku}/{o.region}"
    if o.gpu_model not in GPUS:
        return f"{where}: unknown gpu_model {o.gpu_model!r}"
    if o.segment not in SEGMENTS or o.pricing not in PRICING:
        return f"{where}: invalid segment/pricing {o.segment}/{o.pricing}"
    if o.gpu_count < 1:
        return f"{where}: gpu_count {o.gpu_count} < 1"
    if not MIN_USD_PER_GPU_HOUR <= o.usd_per_gpu_hour <= MAX_USD_PER_GPU_HOUR:
        return (
            f"{where}: ${o.usd_per_gpu_hour}/GPU-hr outside "
            f"[{MIN_USD_PER_GPU_HOUR}, {MAX_USD_PER_GPU_HOUR}]"
        )
    return None


def screen_source(
    source: str, rows: list[Observation], min_rows: int, report: Report
) -> list[Observation] | None:
    """Drop invalid rows; return the valid rows, or None if too few remain to trust."""
    valid = []
    for o in rows:
        problem = row_problem(o)
        if problem:
            report.errors.append(problem)
        else:
            valid.append(o)
    if len(valid) < min_rows:
        report.errors.append(
            f"{source}: {len(valid)} valid rows, expected at least {min_rows} "
            "(upstream format change or outage?); keeping previous data"
        )
        return None
    return valid


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
    missing = {o.provider for o in previous} - {o.provider for o in current}
    for provider in sorted(missing):
        report.warnings.append(
            f"{provider}: listed yesterday but absent today; its last prices are carried "
            "forward for up to 3 days"
        )
