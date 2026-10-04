"""Vast.ai marketplace via its public offer-search API.

A marketplace has no list price: every host sets its own. We pull every rentable
on-demand offer for each tracked GPU and summarize to the median per-GPU price,
recording how many offers it came from. A median of a handful of offers is one host's
asking price, not a market, so models with fewer than MIN_OFFERS listings are skipped.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from typing import Any

import httpx

from gpu_index.catalog import normalize_gpu_name
from gpu_index.http import get
from gpu_index.models import Observation
from gpu_index.sources.base import SourceAdapter, Stamp, observation

API = "https://console.vast.ai/api/v0/bundles/"
PROVIDER = "Vast.ai"
MIN_OFFERS = 5

# Vast's own gpu_name values for the models we track.
GPU_NAMES = [
    "B200",
    "H200",
    "H100 SXM",
    "H100 NVL",
    "H100 PCIE",
    "A100 SXM4",
    "A100 PCIE",
    "L40S",
    "MI300X",
]


def fetch(client: httpx.Client) -> list[dict[str, Any]]:
    offers: list[dict[str, Any]] = []
    for name in GPU_NAMES:
        query = {
            "rentable": {"eq": True},
            "type": "on-demand",
            "gpu_name": {"eq": name},
            "limit": 500,
        }
        page = get(client, API, params={"q": json.dumps(query)}).json()
        offers.extend(page.get("offers", []))
    return offers


def _model_for(offer: dict[str, Any]) -> str | None:
    name = str(offer.get("gpu_name", ""))
    if "A100" in name:  # Vast reports "A100 SXM4" for both memory sizes
        ram_gb = float(offer.get("gpu_ram") or 0) / 1024
        if ram_gb < 60:
            return "A100-40GB"
        name = f"{name} 80GB"
    return normalize_gpu_name(name)


def parse(offers: list[dict[str, Any]], stamp: Stamp) -> list[Observation]:
    by_model: dict[str, list[float]] = defaultdict(list)
    for offer in offers:
        gpu_model = _model_for(offer)
        gpus = int(offer.get("num_gpus") or 0)
        price = float(offer.get("dph_total") or 0)
        if gpu_model is None or gpus <= 0 or price <= 0:
            continue
        by_model[gpu_model].append(price / gpus)

    return [
        observation(
            stamp,
            source="vast",
            provider=PROVIDER,
            segment="marketplace",
            pricing="on_demand",
            gpu_model=gpu_model,
            sku="median-offer",
            region="global",
            geo="Global",
            gpu_count=1,
            usd_per_hour=statistics.median(prices),
            sample_size=len(prices),
        )
        for gpu_model, prices in sorted(by_model.items())
        if len(prices) >= MIN_OFFERS
    ]


ADAPTER = SourceAdapter(
    id="vast",
    name=PROVIDER,
    homepage="https://vast.ai/pricing",
    terms="Public offer-search API used by the Vast.ai console; no key required.",
    min_rows=3,
    fetch=fetch,
    parse=parse,
)
