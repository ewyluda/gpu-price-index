"""Crusoe Cloud on-demand GPU prices from its public pricing page.

Each GPU is a ``.prixing-item`` card (sic, the site's class name) with a model
heading, form-factor tags ("80GB", "SXM", "PCIe", "HGX") and an on-demand price
written as "$3.90/GPU-hr". Cards priced without "/GPU-hr" belong to other products
(dedicated inference endpoints) and are skipped, as are "Contact sales" rows.
"""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from gpu_index.catalog import normalize_gpu_name
from gpu_index.http import get
from gpu_index.models import Observation
from gpu_index.sources.base import SourceAdapter, Stamp, observation

URL = "https://crusoe.ai/cloud/pricing"
PROVIDER = "Crusoe"
_PER_GPU_HOUR = re.compile(r"\$(\d+(?:\.\d+)?)\s*/\s*GPU-hr")


def fetch(client: httpx.Client) -> str:
    return get(client, URL).text


def parse(html: str, stamp: Stamp) -> list[Observation]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Observation] = []
    for card in soup.select(".prixing-item"):
        heading = card.select_one(".pricing-item-heading")
        prices = card.select(".pricing-rich")
        if heading is None or not prices:
            continue
        tags = [t.get_text(strip=True) for t in card.select(".pricing-tag")]
        label = " ".join([heading.get_text(strip=True), *tags])
        gpu_model = normalize_gpu_name(label)
        on_demand = _PER_GPU_HOUR.search(prices[0].get_text(" ", strip=True))
        if gpu_model is None or on_demand is None:
            continue
        rows.append(
            observation(
                stamp,
                source="crusoe",
                provider=PROVIDER,
                segment="neocloud",
                pricing="on_demand",
                gpu_model=gpu_model,
                sku=label,
                region="global",
                geo="Global",
                gpu_count=1,
                usd_per_hour=float(on_demand.group(1)),
            )
        )
    return rows


ADAPTER = SourceAdapter(
    id="crusoe",
    name=PROVIDER,
    homepage=URL,
    terms="Public pricing page; robots.txt allows it and the legal terms have no crawling "
    "restriction. One request per day.",
    min_rows=3,
    fetch=fetch,
    parse=parse,
)
