import json
from pathlib import Path
from typing import Any

import pytest

from gpu_index.tco import OwnAssumptions, build_vs_rent, default_assumptions

CASES = json.loads((Path(__file__).parent / "fixtures" / "tco_cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_reference_cases_shared_with_the_javascript_twin(case: dict[str, Any]) -> None:
    # tests/tco.test.mjs checks site/tco.js against the same fixture.
    result = build_vs_rent(
        OwnAssumptions(**case["assumptions"]), case["gpu_count"], case["utilization"], case["rent"]
    )
    result.pop("assumptions")
    assert result == case["expected"]


def test_own_and_rent_cost_meet_at_breakeven_utilization() -> None:
    a = default_assumptions("H100")
    u = build_vs_rent(a, 64, 0.7, 3.82)["breakeven_utilization"]
    at_breakeven = build_vs_rent(a, 64, u, 3.82)
    assert at_breakeven["own_usd_per_gpu_hour"] == pytest.approx(3.82, abs=0.001)
    assert build_vs_rent(a, 64, u + 0.05, 3.82)["own_usd_per_gpu_hour"] < 3.82
    assert build_vs_rent(a, 64, u - 0.05, 3.82)["own_usd_per_gpu_hour"] > 3.82


def test_no_breakeven_when_renting_wins_even_at_full_utilization() -> None:
    result = build_vs_rent(default_assumptions("H100"), 8, 1.0, 0.50)
    assert result["breakeven_utilization"] is None
    assert result["payback_month"] is None
    assert result["horizon_savings_usd"] < 0


def test_partial_servers_round_up_and_costs_add_up() -> None:
    result = build_vs_rent(default_assumptions("B200"), 9, 0.6, 6.81)
    assert result["servers"] == 2
    breakdown = sum(result["own_monthly_breakdown_usd"].values())
    assert breakdown == pytest.approx(result["own_monthly_usd"], abs=0.05)
    assert result["horizon_months"] == 60 and len(result["own_cumulative_usd"]) == 61


def test_overrides_apply_and_unknown_gpus_are_rejected() -> None:
    a = default_assumptions("H100").with_overrides(power_usd_per_kwh=0.2, pue=None)
    assert a.power_usd_per_kwh == 0.2 and a.pue == 1.3
    with pytest.raises(KeyError):
        default_assumptions("H100-PCIe")
    with pytest.raises(ValueError):
        build_vs_rent(a, 8, 0.0, 3.0)
