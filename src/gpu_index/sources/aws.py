"""Amazon Web Services on-demand list prices.

Uses the per-region pricing documents that back aws.amazon.com/ec2/pricing/on-demand.
The official Price List Bulk API serves the same numbers but as a multi-hundred-MB
file per region; these documents are ~60 KB compressed.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from gpu_index.catalog import geo_for_region
from gpu_index.http import get
from gpu_index.models import Observation
from gpu_index.sources.base import SourceAdapter, Stamp, observation

URL = (
    "https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/ec2/USD/current/"
    "ec2-ondemand-without-sec-sel/{location}/Linux/index.json"
)
PROVIDER = "AWS"

LOCATIONS: dict[str, str] = {
    "US East (N. Virginia)": "us-east-1",
    "US East (Ohio)": "us-east-2",
    "US West (Oregon)": "us-west-2",
    "Europe (Frankfurt)": "eu-central-1",
    "Europe (Stockholm)": "eu-north-1",
    "Europe (London)": "eu-west-2",
    "Asia Pacific (Tokyo)": "ap-northeast-1",
    "Asia Pacific (Mumbai)": "ap-south-1",
    "Asia Pacific (Sydney)": "ap-southeast-2",
    "South America (Sao Paulo)": "sa-east-1",
}

INSTANCES: dict[str, tuple[str, int]] = {
    "p6-b300.48xlarge": ("B300", 8),
    "p6-b200.48xlarge": ("B200", 8),
    "p5en.48xlarge": ("H200", 8),
    "p5e.48xlarge": ("H200", 8),
    "p5.48xlarge": ("H100", 8),
    "p5.4xlarge": ("H100", 1),
    "p4de.24xlarge": ("A100-80GB", 8),
    "p4d.24xlarge": ("A100-40GB", 8),
    "g6e.xlarge": ("L40S", 1),
    "g6e.12xlarge": ("L40S", 4),
    "g6e.48xlarge": ("L40S", 8),
}


def fetch(client: httpx.Client) -> dict[str, Any]:
    documents: dict[str, Any] = {}
    for location in LOCATIONS:
        url = URL.format(location=quote(location))
        try:
            documents[location] = get(client, url).json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:  # region without GPU capacity listed
                raise
    return documents


def parse(documents: dict[str, Any], stamp: Stamp) -> list[Observation]:
    rows: list[Observation] = []
    for location, doc in documents.items():
        region = LOCATIONS.get(location, location)
        for offers in doc.get("regions", {}).values():
            for offer in offers.values():
                instance = offer.get("Instance Type", "")
                if instance not in INSTANCES:
                    continue
                price = float(offer.get("price") or 0)
                if price <= 0:
                    continue
                gpu_model, count = INSTANCES[instance]
                rows.append(
                    observation(
                        stamp,
                        source="aws",
                        provider=PROVIDER,
                        segment="hyperscaler",
                        pricing="on_demand",
                        gpu_model=gpu_model,
                        sku=instance,
                        region=region,
                        geo=geo_for_region(location),
                        gpu_count=count,
                        usd_per_hour=price,
                    )
                )
    return rows


ADAPTER = SourceAdapter(
    id="aws",
    name=PROVIDER,
    homepage="https://aws.amazon.com/ec2/pricing/on-demand/",
    terms="Public list prices published on aws.amazon.com; fetched once per day.",
    min_rows=10,
    fetch=fetch,
    parse=parse,
)
