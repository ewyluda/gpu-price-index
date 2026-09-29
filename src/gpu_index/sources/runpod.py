"""RunPod via its public GraphQL API.

RunPod sells the same GPU two ways, which map cleanly onto two market segments:
Secure Cloud (RunPod-operated data centers, a neocloud) and Community Cloud
(third-party hosts, a marketplace).
"""

from __future__ import annotations

from typing import Any

import httpx

from gpu_index.catalog import normalize_gpu_name
from gpu_index.http import post_json
from gpu_index.models import Observation, Segment
from gpu_index.sources.base import SourceAdapter, Stamp, observation

API = "https://api.runpod.io/graphql"
QUERY = "query { gpuTypes { id displayName memoryInGb securePrice communityPrice } }"

OFFERINGS: list[tuple[str, str, Segment]] = [
    ("securePrice", "RunPod Secure Cloud", "neocloud"),
    ("communityPrice", "RunPod Community Cloud", "marketplace"),
]


def fetch(client: httpx.Client) -> dict[str, Any]:
    payload: dict[str, Any] = post_json(client, API, {"query": QUERY})
    if payload.get("errors"):
        raise RuntimeError(f"RunPod GraphQL error: {payload['errors']}")
    return payload


def parse(payload: dict[str, Any], stamp: Stamp) -> list[Observation]:
    rows: list[Observation] = []
    for gpu in payload["data"]["gpuTypes"]:
        gpu_model = normalize_gpu_name(f"{gpu['id']} {gpu['displayName']}")
        if gpu_model is None:
            continue
        for field, provider, segment in OFFERINGS:
            price = float(gpu.get(field) or 0)
            if price <= 0:  # zero means "not currently offered in this cloud"
                continue
            rows.append(
                observation(
                    stamp,
                    source="runpod",
                    provider=provider,
                    segment=segment,
                    pricing="on_demand",
                    gpu_model=gpu_model,
                    sku=gpu["id"],
                    region="global",
                    geo="Global",
                    gpu_count=1,
                    usd_per_hour=price,
                )
            )
    return rows


ADAPTER = SourceAdapter(
    id="runpod",
    name="RunPod",
    homepage="https://www.runpod.io/pricing",
    terms="Public GraphQL API; the gpuTypes query requires no API key.",
    min_rows=5,
    fetch=fetch,
    parse=parse,
)
