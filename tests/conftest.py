from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from gpu_index.models import Observation
from gpu_index.sources import ADAPTERS, Stamp

FIXTURES = Path(__file__).parent / "fixtures"
STAMP = Stamp(date="2026-09-28", collected_at="2026-09-28T06:17:00+00:00")


def load_fixture(source_id: str) -> Any:
    if source_id == "lambda":
        return (FIXTURES / "lambda.html").read_text(encoding="utf-8")
    return json.loads((FIXTURES / f"{source_id}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def fixture_rows() -> list[Observation]:
    rows: list[Observation] = []
    for source_id, adapter in ADAPTERS.items():
        rows.extend(adapter.parse(load_fixture(source_id), STAMP))
    return rows


def make_obs(**overrides: Any) -> Observation:
    base: dict[str, Any] = {
        "date": "2026-09-28",
        "collected_at": "2026-09-28T06:17:00+00:00",
        "source": "test",
        "provider": "Test Cloud",
        "segment": "neocloud",
        "pricing": "on_demand",
        "gpu_model": "H100",
        "sku": "h100x1",
        "region": "global",
        "geo": "Global",
        "gpu_count": 1,
        "usd_per_hour": 2.0,
        "usd_per_gpu_hour": 2.0,
        "sample_size": 1,
    }
    base.update(overrides)
    if "usd_per_gpu_hour" in overrides and "usd_per_hour" not in overrides:
        base["usd_per_hour"] = base["usd_per_gpu_hour"] * base["gpu_count"]
    return Observation(**base)
