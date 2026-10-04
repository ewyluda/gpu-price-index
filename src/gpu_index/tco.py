"""Build vs rent: the total cost of owning GPU servers against renting at the index.

Owning has a large fixed cost (the server depreciating, and the capital tied up in it)
and a small variable one (power draw rises with load). Renting on demand is purely
variable: you pay only for hours used. So the answer turns on utilization, and the
key output is the **breakeven utilization** above which owning is cheaper per useful
GPU-hour.

Monthly cost of ownership, per server:
  depreciation   capex / (years * 12)                  straight line, no residual value
  capital        capex * cost_of_capital / 2 / 12      interest on the average balance
  colocation     server_kw * colo_usd_per_kw_month     space, cooling, power delivery
  operations     capex * ops_pct_per_year / 12         support, spares, network, staff
  energy         server_kw * load * pue * 730 * $/kWh  load = idle + (1 - idle) * util

The JavaScript twin (site/tco.js) implements the same formulas; both are checked
against tests/fixtures/tco_cases.json so the dashboard and MCP server always agree.
Default hardware prices are illustrative placeholders, not market data.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from typing import Any

HOURS_PER_MONTH = 730
GPUS_PER_SERVER = 8


@dataclass(frozen=True)
class OwnAssumptions:
    capex_per_server_usd: float
    server_kw: float
    depreciation_years: float = 5.0
    cost_of_capital: float = 0.08
    pue: float = 1.3
    power_usd_per_kwh: float = 0.08
    colo_usd_per_kw_month: float = 150.0
    ops_pct_per_year: float = 0.08
    idle_power_fraction: float = 0.35

    def with_overrides(self, **overrides: float | None) -> OwnAssumptions:
        return replace(self, **{k: v for k, v in overrides.items() if v is not None})


def _round(value: float, digits: int = 2) -> float:
    return round(value + 0.0, digits)


def build_vs_rent(
    a: OwnAssumptions, gpu_count: int, utilization: float, rent_usd_per_gpu_hour: float
) -> dict[str, Any]:
    """Compare owning ``gpu_count`` GPUs at ``utilization`` (0-1] with renting them on demand."""
    if gpu_count < 1 or not 0 < utilization <= 1 or rent_usd_per_gpu_hour <= 0:
        raise ValueError("need gpu_count >= 1, 0 < utilization <= 1 and a positive rent rate")
    servers = math.ceil(gpu_count / GPUS_PER_SERVER)
    capex = a.capex_per_server_usd * servers
    kw = a.server_kw * servers

    depreciation = capex / (a.depreciation_years * 12)
    capital = capex * a.cost_of_capital / 2 / 12
    colocation = kw * a.colo_usd_per_kw_month
    operations = capex * a.ops_pct_per_year / 12
    energy_per_load = kw * a.pue * HOURS_PER_MONTH * a.power_usd_per_kwh
    load = a.idle_power_fraction + (1 - a.idle_power_fraction) * utilization
    energy = energy_per_load * load

    own_monthly = depreciation + capital + colocation + operations + energy
    useful_gpu_hours = gpu_count * HOURS_PER_MONTH * utilization
    rent_monthly = rent_usd_per_gpu_hour * useful_gpu_hours

    # own(u) = fixed + energy_per_load * (idle + (1 - idle) * u); rent(u) = rate * gpus * 730 * u
    fixed = depreciation + capital + colocation + operations
    intercept = fixed + energy_per_load * a.idle_power_fraction
    slope_gap = rent_usd_per_gpu_hour * gpu_count * HOURS_PER_MONTH - energy_per_load * (
        1 - a.idle_power_fraction
    )
    breakeven = intercept / slope_gap if slope_gap > 0 else None
    if breakeven is not None and breakeven > 1:
        breakeven = None  # renting is cheaper even at 100% utilization

    # Cash view over the depreciation horizon: capex paid up front, then monthly
    # cash costs (everything except depreciation, which is the capex itself).
    horizon = round(a.depreciation_years * 12)
    cash_monthly = own_monthly - depreciation
    own_cumulative = [capex + cash_monthly * m for m in range(horizon + 1)]
    rent_cumulative = [rent_monthly * m for m in range(horizon + 1)]
    payback_month = next(
        (m for m in range(1, horizon + 1) if own_cumulative[m] <= rent_cumulative[m]), None
    )

    return {
        "gpu_count": gpu_count,
        "servers": servers,
        "utilization": utilization,
        "rent_usd_per_gpu_hour": rent_usd_per_gpu_hour,
        "own_usd_per_gpu_hour": _round(own_monthly / useful_gpu_hours, 4),
        "own_monthly_usd": _round(own_monthly),
        "rent_monthly_usd": _round(rent_monthly),
        "own_monthly_breakdown_usd": {
            "depreciation": _round(depreciation),
            "capital": _round(capital),
            "colocation": _round(colocation),
            "operations": _round(operations),
            "energy": _round(energy),
        },
        "breakeven_utilization": None if breakeven is None else _round(breakeven, 4),
        "horizon_months": horizon,
        "payback_month": payback_month,
        "horizon_savings_usd": _round(rent_cumulative[-1] - own_cumulative[-1]),
        "own_cumulative_usd": [_round(v) for v in own_cumulative],
        "rent_cumulative_usd": [_round(v) for v in rent_cumulative],
        "assumptions": asdict(a),
    }


# Illustrative 8-GPU server assumptions. Power is the vendor reference system's
# maximum (e.g. DGX H100 10.2 kW, DGX B200 14.3 kW, DGX A100 6.5 kW); capex values are
# round-number placeholders for a quote you'd replace with your own.
SERVER_DEFAULTS: dict[str, tuple[float, float]] = {
    "B300": (500_000, 14.5),
    "B200": (450_000, 14.3),
    "H200": (300_000, 10.2),
    "H100": (250_000, 10.2),
    "MI300X": (250_000, 11.0),
    "A100-80GB": (120_000, 6.5),
    "L40S": (90_000, 4.5),
}


def default_assumptions(gpu: str) -> OwnAssumptions:
    if gpu not in SERVER_DEFAULTS:
        raise KeyError(f"no ownership defaults for {gpu!r}; have {sorted(SERVER_DEFAULTS)}")
    capex, kw = SERVER_DEFAULTS[gpu]
    return OwnAssumptions(capex_per_server_usd=capex, server_kw=kw)
