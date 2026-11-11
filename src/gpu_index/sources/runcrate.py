"""Runcrate via its public per-GPU price feed.

The feed lists one entry per GPU type with the lowest on-demand per-GPU-hour price across
its live offers (``min_price_hr``) and how many offers are live (``available_options``).
That is a "from" price, so each GPU type becomes one observation in one global region.

Only GPU types that map to one catalog key without guessing are collected. Runcrate
sells H100 and A100 80GB on both SXM and PCIe machines and the feed does not say which
form factor a price belongs to, so those two are skipped rather than filed under the
SXM keys. H200 NVL and the GPUs outside the catalog are skipped too.
"""

from __future__ import annotations

from typing import Any

import httpx

from gpu_index.http import get
from gpu_index.models import Observation
from gpu_index.sources.base import SourceAdapter, Stamp, observation

API = "https://www.runcrate.ai/api/gpu-pricing"
PROVIDER = "Runcrate"

# Feed ``gpu_type`` -> catalog key, for types whose form factor is unambiguous.
GPU_TYPES = {
    "B300": "B300",
    "B200": "B200",
    "H200": "H200",  # SXM5; the NVL card is a separate ``H200_nvl`` type
    "A100": "A100-40GB",
    "L40S": "L40S",
}


def fetch(client: httpx.Client) -> dict[str, Any]:
    payload: dict[str, Any] = get(client, API).json()
    return payload


def parse(payload: dict[str, Any], stamp: Stamp) -> list[Observation]:
    rows: list[Observation] = []
    for gpu in payload["gpus"]:
        gpu_model = GPU_TYPES.get(gpu["gpu_type"])
        if gpu_model is None or not gpu.get("available_options"):
            continue
        price = float(gpu.get("min_price_hr") or 0)
        if price <= 0:
            continue
        rows.append(
            observation(
                stamp,
                source="runcrate",
                provider=PROVIDER,
                segment="neocloud",
                pricing="on_demand",
                gpu_model=gpu_model,
                sku=gpu["gpu_type"],
                region="global",
                geo="Global",
                gpu_count=1,
                usd_per_hour=price,
            )
        )
    return rows


ADAPTER = SourceAdapter(
    id="runcrate",
    name=PROVIDER,
    homepage="https://www.runcrate.ai/pricing",
    terms="Public JSON price feed, the same data as the pricing page; no key required.",
    min_rows=3,
    fetch=fetch,
    parse=parse,
)
