"""MCP server: lets an AI agent query the GPU price index and price out clusters.

Reads the published artifacts (``site/data/*.json``) from disk, or from a deployed
dashboard when ``GPU_INDEX_DATA_URL`` is set, e.g.
``GPU_INDEX_DATA_URL=https://ewyluda.github.io/gpu-rental-rate/data``.

Run with ``gpu-index-mcp`` (stdio). Example Claude Code registration:
``claude mcp add gpu-index -- uv run --directory /path/to/repo gpu-index-mcp``
or, without a checkout (reads the public dashboard's data):
``claude mcp add gpu-index -- uvx --from "gpu-index[mcp] @ git+<repo url>" gpu-index-mcp``
"""

from __future__ import annotations

import json
import os
from typing import Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer

from gpu_index import index, tco
from gpu_index.http import USER_AGENT
from gpu_index.publish import SITE_DATA

server = MCPServer(
    name="gpu-index",
    instructions=(
        "Daily GPU rental prices (USD per GPU-hour, on-demand list prices) from "
        "hyperscalers, neoclouds and marketplaces. Use list_gpus first to see valid GPU "
        "keys. Use estimate_cluster_cost for 'what would N GPUs for T cost' questions. "
        "Always cite the as_of date returned with the data."
    ),
)


PUBLIC_DATA_URL = "https://ewyluda.github.io/gpu-rental-rate/data"


def load(name: str) -> Any:
    """Load a published artifact by file name (latest.json, history.json, ...).

    Prefers ``GPU_INDEX_DATA_URL``, then a local checkout's ``site/data``, then the
    public dashboard (the case when installed with ``uvx`` outside the repo).
    """
    base = os.environ.get("GPU_INDEX_DATA_URL")
    if base is None and not (SITE_DATA / name).exists():
        base = PUBLIC_DATA_URL
    if base:
        response = httpx.get(
            f"{base.rstrip('/')}/{name}", headers={"User-Agent": USER_AGENT}, timeout=20
        )
        response.raise_for_status()
        return response.json()
    return json.loads((SITE_DATA / name).read_text(encoding="utf-8"))


def _gpu(snap: dict[str, Any], gpu: str) -> dict[str, Any]:
    for entry in snap["gpus"]:
        if entry["key"].lower() == gpu.lower() or entry["name"].lower() == gpu.lower():
            return dict(entry)
    raise ValueError(f"unknown GPU {gpu!r}; valid keys: {[g['key'] for g in snap['gpus']]}")


@server.tool()
def list_gpus() -> dict[str, Any]:
    """List tracked GPUs with specs and today's market index ($/GPU-hr)."""
    snap = load("latest.json")
    return {
        "as_of": snap["as_of"],
        "gpus": [
            {
                "key": g["key"],
                "name": g["name"],
                "memory_gb": g["memory_gb"],
                "bf16_dense_tflops": g["bf16_dense_tflops"],
                "market_index_usd_per_gpu_hour": g["series"]["index"]["value"],
                "providers": g["series"]["index"]["n_providers"],
            }
            for g in snap["gpus"]
        ],
    }


@server.tool()
def get_prices(gpu: str) -> dict[str, Any]:
    """Current prices for one GPU: market and segment indices, per-provider table,
    regional medians, hyperscaler premium and price-performance."""
    snap = load("latest.json")
    return {"as_of": snap["as_of"], **_gpu(snap, gpu)}


@server.tool()
def get_history(
    gpu: str,
    series: Literal["index", "hyperscaler", "neocloud", "marketplace", "spot"] = "index",
) -> dict[str, Any]:
    """Daily history of one index series for a GPU (null where no data that day)."""
    hist = load("history.json")
    key = _gpu(load("latest.json"), gpu)["key"]
    return {
        "gpu": key,
        "series": series,
        "dates": hist["dates"],
        "values": hist["series"][key][series],
    }


@server.tool()
def estimate_cluster_cost(
    gpu: str,
    gpu_count: int,
    hours: float,
    segment: Literal["hyperscaler", "neocloud", "marketplace"] | None = None,
) -> dict[str, Any]:
    """Estimate the on-demand cost of renting gpu_count GPUs for a number of hours,
    quoted per provider at its cheapest listed SKU/region, cheapest first.
    Example: 512 H100s for 90 days -> gpu="H100", gpu_count=512, hours=2160."""
    if gpu_count < 1 or hours <= 0:
        raise ValueError("gpu_count must be >= 1 and hours > 0")
    snap = load("latest.json")
    return index.estimate_cost(snap, _gpu(snap, gpu)["key"], gpu_count, hours, segment)


@server.tool()
def build_vs_rent(
    gpu: str,
    gpu_count: int = 64,
    utilization: float = 0.7,
    rent_segment: Literal["neocloud", "hyperscaler", "marketplace", "index"] = "neocloud",
    capex_per_server_usd: float | None = None,
    power_usd_per_kwh: float | None = None,
    pue: float | None = None,
    depreciation_years: float | None = None,
    cost_of_capital: float | None = None,
    colo_usd_per_kw_month: float | None = None,
) -> dict[str, Any]:
    """Compare owning 8-GPU servers with renting on demand at today's index.

    Returns own vs rent cost per useful GPU-hour, the breakeven utilization above which
    owning is cheaper, payback month and savings over the depreciation horizon.
    utilization is a fraction (0.7 = 70%). Server price and power defaults are
    illustrative placeholders: pass capex_per_server_usd (an 8-GPU server quote) and
    power_usd_per_kwh for a real decision."""
    snap = load("latest.json")
    entry = _gpu(snap, gpu)
    series = entry["series"].get(rent_segment)
    if series is None:
        raise ValueError(f"no {rent_segment} price for {entry['name']} today")
    a = tco.default_assumptions(entry["key"]).with_overrides(
        capex_per_server_usd=capex_per_server_usd,
        power_usd_per_kwh=power_usd_per_kwh,
        pue=pue,
        depreciation_years=depreciation_years,
        cost_of_capital=cost_of_capital,
        colo_usd_per_kw_month=colo_usd_per_kw_month,
    )
    result = tco.build_vs_rent(a, gpu_count, utilization, series["value"])
    for key in ("own_cumulative_usd", "rent_cumulative_usd"):
        result[key] = result[key][:: max(1, result["horizon_months"] // 12)]  # yearly points
    return {"gpu": entry["key"], "rent_segment": rent_segment, "as_of": snap["as_of"], **result}


@server.tool()
def compare_price_performance(
    metric: Literal["pflop", "memory"] = "pflop",
) -> dict[str, Any]:
    """Rank GPUs by market-index cost per dense BF16 PFLOP-hour or per GB of HBM-hour.
    Peak FLOPS are vendor specs; delivered throughput depends on the workload."""
    snap = load("latest.json")
    field = "usd_per_pflop_hour" if metric == "pflop" else "usd_per_gb_hour"
    ranking = sorted(
        (
            {"gpu": g["key"], field: g[field], "market_index": g["series"]["index"]["value"]}
            for g in snap["gpus"]
        ),
        key=lambda r: r[field],
    )
    return {"as_of": snap["as_of"], "metric": field, "ranking": ranking}


@server.tool()
def pipeline_status() -> dict[str, Any]:
    """Health of the most recent collection run: per-source status and validation."""
    status: dict[str, Any] = load("status.json")
    return status


@server.resource("gpu-index://methodology", mime_type="text/markdown")
def methodology() -> str:
    """How the index is computed."""
    return index.__doc__ or ""


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
