"""Oracle Cloud Infrastructure via its public price-list API.

Oracle publishes its full list price catalog as JSON for its cost estimator, with no
authentication. GPU compute is priced per GPU-hour and is the same in every
commercial region. Parts are matched by part number, since display names are
inconsistent ("OCI - Compute - GPU - H100" vs "Compute - GPU - A100 - v2") and
include look-alikes (Cloud@Customer, NVIDIA AI Enterprise licences) that aren't
cloud GPU rentals.
"""

from __future__ import annotations

from typing import Any

import httpx

from gpu_index.http import get
from gpu_index.models import Observation
from gpu_index.sources.base import SourceAdapter, Stamp, observation

API = "https://apexapps.oracle.com/pls/apex/cetools/api/v1/products/"
PROVIDER = "Oracle Cloud"

# part number -> (catalog key, bare-metal shape the part prices)
PARTS: dict[str, tuple[str, str]] = {
    "B112237": ("B300", "BM.GPU.B300.8"),
    "B110978": ("B200", "BM.GPU.B200.8"),
    "B110519": ("H200", "BM.GPU.H200.8"),
    "B98415": ("H100", "BM.GPU.H100.8"),
    "B109485": ("MI300X", "BM.GPU.MI300X.8"),
    "B95907": ("A100-80GB", "BM.GPU.A100-v2.8"),
    "B109479": ("L40S", "BM.GPU.L40S.4"),
}


def fetch(client: httpx.Client) -> dict[str, Any]:
    payload: dict[str, Any] = get(client, API, params={"currencyCode": "USD"}).json()
    return payload


def _pay_as_you_go(item: dict[str, Any]) -> float | None:
    for localization in item.get("currencyCodeLocalizations", []):
        if localization.get("currencyCode") != "USD":
            continue
        for price in localization.get("prices", []):
            if price.get("model") == "PAY_AS_YOU_GO" and price.get("value"):
                return float(price["value"])
    return None


def parse(payload: dict[str, Any], stamp: Stamp) -> list[Observation]:
    rows: list[Observation] = []
    for item in payload.get("items", []):
        part = PARTS.get(str(item.get("partNumber")))
        price = _pay_as_you_go(item)
        if part is None or price is None or item.get("metricName") != "GPU Per Hour":
            continue
        gpu_model, shape = part
        rows.append(
            observation(
                stamp,
                source="oracle",
                provider=PROVIDER,
                segment="hyperscaler",
                pricing="on_demand",
                gpu_model=gpu_model,
                sku=shape,
                region="global",
                geo="Global",
                gpu_count=1,
                usd_per_hour=price,
            )
        )
    return rows


ADAPTER = SourceAdapter(
    id="oracle",
    name=PROVIDER,
    homepage="https://www.oracle.com/cloud/compute/gpu/pricing/",
    terms="Public price-list API that Oracle documents for cost estimation; no key required.",
    min_rows=4,
    fetch=fetch,
    parse=parse,
)
