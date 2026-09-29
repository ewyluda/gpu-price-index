"""Index methodology: turn raw observations into comparable daily price indices.

Two-stage median, equal weight per provider:
  1. For each provider, take the median on-demand $/GPU-hr across its SKUs/regions.
  2. Take the median of those provider medians.

Stage 1 stops Azure (hundreds of region rows) from outvoting Lambda (a handful of
rows); stage 2 is robust to any one provider's outlier pricing. The *market index*
blends all segments; *segment indices* (hyperscaler / neocloud / marketplace) use
only providers in that segment. See docs/methodology.md.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict
from datetime import date as Date
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from gpu_index.catalog import GPUS
from gpu_index.models import SEGMENTS, Observation, Pricing

METHODOLOGY_VERSION = "1.0"
SERIES = ("index", *SEGMENTS, "spot")


def _r(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def _usd(value: float | None) -> float | None:
    """Round a price to the cent, half-up, so Python and the browser display it identically."""
    if value is None:
        return None
    return float(Decimal(repr(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def provider_medians(
    rows: Iterable[Observation], pricing: Pricing = "on_demand"
) -> dict[tuple[str, str], tuple[str, float]]:
    """(gpu_model, provider) -> (segment, median $/GPU-hr)."""
    groups: dict[tuple[str, str], list[float]] = defaultdict(list)
    segments: dict[tuple[str, str], str] = {}
    for o in rows:
        if o.pricing != pricing:
            continue
        groups[(o.gpu_model, o.provider)].append(o.usd_per_gpu_hour)
        segments[(o.gpu_model, o.provider)] = o.segment
    return {k: (segments[k], statistics.median(v)) for k, v in groups.items()}


def daily_values(rows: list[Observation]) -> dict[str, dict[str, tuple[float, int]]]:
    """gpu_model -> series name -> (value, n_providers) for a single day's rows."""
    out: dict[str, dict[str, tuple[float, int]]] = defaultdict(dict)
    by_gpu: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (gpu, _provider), (segment, median) in provider_medians(rows).items():
        by_gpu[gpu].append((segment, median))
    for gpu, entries in by_gpu.items():
        out[gpu]["index"] = (statistics.median(m for _, m in entries), len(entries))
        for segment in SEGMENTS:
            values = [m for s, m in entries if s == segment]
            if values:
                out[gpu][segment] = (statistics.median(values), len(values))
    spot: dict[str, list[float]] = defaultdict(list)
    for (gpu, _provider), (_segment, median) in provider_medians(rows, "spot").items():
        spot[gpu].append(median)
    for gpu, values in spot.items():
        out[gpu]["spot"] = (statistics.median(values), len(values))
    return out


def history(rows: list[Observation]) -> dict[str, Any]:
    """Aligned daily series for every GPU: {"dates": [...], "series": {gpu: {name: [...]}}}."""
    by_date: dict[str, list[Observation]] = defaultdict(list)
    for o in rows:
        by_date[o.date].append(o)
    dates = sorted(by_date)
    per_day = {d: daily_values(by_date[d]) for d in dates}
    series: dict[str, dict[str, list[float | None]]] = {}
    for gpu in GPUS:
        series[gpu] = {
            name: [_usd(per_day[d].get(gpu, {}).get(name, (None, 0))[0]) for d in dates]
            for name in SERIES
        }
    return {"dates": dates, "series": series}


def pct_change(dates: list[str], values: list[float | None], days: int) -> float | None:
    """Change from the last value on or before (latest - days) to the latest value."""
    if not dates or values[-1] is None:
        return None
    target = (Date.fromisoformat(dates[-1]) - timedelta(days=days)).isoformat()
    for d, v in zip(reversed(dates), reversed(values), strict=True):
        if d <= target and v is not None:
            return _r((values[-1] - v) / v)
    return None


def _provider_table(rows: list[Observation], gpu: str) -> list[dict[str, Any]]:
    groups: dict[str, list[Observation]] = defaultdict(list)
    for o in rows:
        if o.gpu_model == gpu and o.pricing == "on_demand":
            groups[o.provider].append(o)
    table = []
    for provider, obs in groups.items():
        best = min(obs, key=lambda o: o.usd_per_gpu_hour)
        table.append(
            {
                "provider": provider,
                "source": best.source,
                "segment": best.segment,
                "median": _usd(statistics.median(o.usd_per_gpu_hour for o in obs)),
                "min": _usd(best.usd_per_gpu_hour),
                "max": _usd(max(o.usd_per_gpu_hour for o in obs)),
                "best_sku": best.sku,
                "best_region": best.region,
                "n_skus": len({o.sku for o in obs}),
                "n_regions": len({o.region for o in obs}),
                "sample_size": sum(o.sample_size for o in obs),
            }
        )
    return sorted(table, key=lambda r: r["median"])


def _regional(rows: list[Observation], gpu: str) -> dict[str, dict[str, float]]:
    """Median $/GPU-hr per geography per segment (region-specific list prices only)."""
    groups: dict[tuple[str, str], list[float]] = defaultdict(list)
    for o in rows:
        if o.gpu_model == gpu and o.pricing == "on_demand" and o.geo != "Global":
            groups[(o.geo, o.segment)].append(o.usd_per_gpu_hour)
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for (geo, segment), values in sorted(groups.items()):
        out[geo][segment] = _usd(statistics.median(values)) or 0.0
    return dict(out)


def snapshot(rows: list[Observation]) -> dict[str, Any]:
    """Everything the dashboard, the brief and the MCP server need, as one document."""
    if not rows:
        raise ValueError("no observations to build a snapshot from")
    hist = history(rows)
    dates: list[str] = hist["dates"]
    latest_date = dates[-1]
    latest = [o for o in rows if o.date == latest_date]
    today = daily_values(latest)

    gpus = []
    for key, spec in GPUS.items():
        if key not in today:
            continue
        series = hist["series"][key]
        entry: dict[str, Any] = asdict(spec)
        for name in SERIES:
            if name in today[key]:
                value, n = today[key][name]
                entry.setdefault("series", {})[name] = {
                    "value": _usd(value),
                    "n_providers": n,
                    "change_7d": pct_change(dates, series[name], 7),
                    "change_30d": pct_change(dates, series[name], 30),
                }
        s = entry["series"]
        hyper, neo = s.get("hyperscaler"), s.get("neocloud")
        entry["hyperscaler_premium"] = (
            _r(hyper["value"] / neo["value"] - 1) if hyper and neo else None
        )
        index_value = s["index"]["value"]
        entry["usd_per_pflop_hour"] = _usd(index_value / (spec.bf16_dense_tflops / 1000))
        entry["usd_per_gb_hour"] = _r(index_value / spec.memory_gb, 5)
        entry["providers"] = _provider_table(latest, key)
        entry["regional"] = _regional(latest, key)
        gpus.append(entry)

    return {
        "as_of": latest_date,
        "first_date": dates[0],
        "days_of_history": len(dates),
        "methodology_version": METHODOLOGY_VERSION,
        "observations": len(latest),
        "providers": sorted({o.provider for o in latest}),
        "gpus": gpus,
    }


def estimate_cost(
    snap: dict[str, Any],
    gpu: str,
    gpu_count: int,
    hours: float,
    segment: str | None = None,
) -> dict[str, Any]:
    """Price a reservation of ``gpu_count`` GPUs for ``hours`` at each provider's list price."""
    entry = next((g for g in snap["gpus"] if g["key"] == gpu), None)
    if entry is None:
        raise KeyError(f"no current prices for {gpu!r}; known: {[g['key'] for g in snap['gpus']]}")
    gpu_hours = gpu_count * hours
    quotes = [
        {
            "provider": p["provider"],
            "segment": p["segment"],
            "usd_per_gpu_hour": p["min"],
            "total_usd": round(p["min"] * gpu_hours, 2),
            "sku": p["best_sku"],
            "region": p["best_region"],
        }
        for p in entry["providers"]
        if segment is None or p["segment"] == segment
    ]
    quotes.sort(key=lambda q: q["total_usd"])
    index_value = entry["series"]["index"]["value"]
    return {
        "gpu": gpu,
        "gpu_count": gpu_count,
        "hours": hours,
        "gpu_hours": gpu_hours,
        "as_of": snap["as_of"],
        "at_market_index_usd": round(index_value * gpu_hours, 2),
        "quotes": quotes,
        "note": "On-demand list prices. Reserved and committed-use pricing is not included.",
    }
