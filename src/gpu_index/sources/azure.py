"""Microsoft Azure via the public, unauthenticated Retail Prices API.

https://learn.microsoft.com/rest/api/cost-management/retail-prices/azure-retail-prices
"""

from __future__ import annotations

from typing import Any

import httpx

from gpu_index.catalog import geo_for_region
from gpu_index.http import get
from gpu_index.models import Observation
from gpu_index.sources.base import SourceAdapter, Stamp, observation

API = "https://prices.azure.com/api/retail/prices"
PROVIDER = "Microsoft Azure"

# armSkuName -> (catalog key, GPUs per VM). One representative SKU per shape; the
# flex / no-InfiniBand variants carry the same GPU and would double-count.
SKUS: dict[str, tuple[str, int]] = {
    "Standard_ND96isr_H100_v5": ("H100", 8),
    "Standard_NC40ads_H100_v5": ("H100-NVL", 1),
    "Standard_NC80adis_H100_v5": ("H100-NVL", 2),
    "Standard_ND96isr_H200_v5": ("H200", 8),
    "Standard_ND96amsr_A100_v4": ("A100-80GB", 8),
    "Standard_ND96asr_v4": ("A100-40GB", 8),
    "Standard_NC24ads_A100_v4": ("A100-80GB-PCIe", 1),
    "Standard_NC48ads_A100_v4": ("A100-80GB-PCIe", 2),
    "Standard_NC96ads_A100_v4": ("A100-80GB-PCIe", 4),
    "Standard_ND96isr_MI300X_v5": ("MI300X", 8),
}


def fetch(client: httpx.Client) -> list[dict[str, Any]]:
    sku_filter = " or ".join(f"armSkuName eq '{sku}'" for sku in SKUS)
    params: dict[str, Any] | None = {
        "$filter": (
            f"serviceName eq 'Virtual Machines' and priceType eq 'Consumption' and ({sku_filter})"
        )
    }
    url: str | None = API
    items: list[dict[str, Any]] = []
    while url:
        page = get(client, url, params=params).json()
        items.extend(page["Items"])
        url = page.get("NextPageLink")
        params = None  # NextPageLink already encodes the filter
    return items


def _is_general_availability(item: dict[str, Any]) -> bool:
    """Linux, pay-as-you-go, publicly purchasable meters only."""
    region = str(item.get("armRegionName", ""))
    return (
        item.get("armSkuName") in SKUS
        and item.get("unitOfMeasure") == "1 Hour"
        and item.get("type", "Consumption") == "Consumption"
        and "Windows" not in item.get("productName", "")
        and "Low Priority" not in item.get("meterName", "")
        and not region.startswith(("usgov", "usdod"))  # sovereign clouds
        and float(item.get("retailPrice") or 0) > 0
    )


def parse(items: list[dict[str, Any]], stamp: Stamp) -> list[Observation]:
    items = [i for i in items if _is_general_availability(i)]
    on_demand = {
        (i["armSkuName"], i["armRegionName"]): float(i["retailPrice"])
        for i in items
        if "Spot" not in i["meterName"]
    }
    rows: list[Observation] = []
    for item in items:
        sku, region = item["armSkuName"], item["armRegionName"]
        price = float(item["retailPrice"])
        is_spot = "Spot" in item["meterName"]
        # Azure lists a spot meter at the full on-demand rate where spot capacity
        # isn't actually discounted; those rows would distort the spot series.
        if is_spot and price >= on_demand.get((sku, region), float("inf")):
            continue
        gpu_model, count = SKUS[sku]
        rows.append(
            observation(
                stamp,
                source="azure",
                provider=PROVIDER,
                segment="hyperscaler",
                pricing="spot" if is_spot else "on_demand",
                gpu_model=gpu_model,
                sku=sku,
                region=region,
                geo=geo_for_region(region),
                gpu_count=count,
                usd_per_hour=price,
            )
        )
    return rows


ADAPTER = SourceAdapter(
    id="azure",
    name=PROVIDER,
    homepage="https://azure.microsoft.com/pricing/details/virtual-machines/linux/",
    terms="Public Retail Prices API, documented for unauthenticated programmatic use.",
    min_rows=10,
    fetch=fetch,
    parse=parse,
)
