"""Hyperstack on-demand and spot GPU prices from its public pricing page.

Price blocks are located by their headings ("On-Demand GPU Pricing", "Spot VM
Pricing"). Hyperstack's model names need an explicit map: "NVIDIA H100" and
"NVIDIA H100 NVLink" are PCIe cards (NVLink here means a bridge between PCIe cards),
which a generic name matcher would mistake for SXM parts.
"""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from gpu_index.http import get
from gpu_index.models import Observation, Pricing
from gpu_index.sources.base import SourceAdapter, Stamp, observation

URL = "https://www.hyperstack.cloud/gpu-pricing"
PROVIDER = "Hyperstack"
BLOCKS: dict[str, Pricing] = {"On-Demand GPU Pricing": "on_demand", "Spot VM Pricing": "spot"}

MODELS = {
    "NVIDIA B300": "B300",
    "NVIDIA B200": "B200",
    "NVIDIA H200 SXM": "H200",
    "NVIDIA H100 SXM": "H100",
    "NVIDIA H100 NVLink": "H100-PCIe",
    "NVIDIA H100 PCIe": "H100-PCIe",
    "NVIDIA H100": "H100-PCIe",
    "NVIDIA A100 SXM": "A100-80GB",
    "NVIDIA A100 NVLink": "A100-80GB-PCIe",
    "NVIDIA A100": "A100-80GB-PCIe",
}


def fetch(client: httpx.Client) -> str:
    return get(client, URL).text


def parse(html: str, stamp: Stamp) -> list[Observation]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Observation] = []
    for block in soup.select(".page-price_card_main"):
        heading = block.find_previous(["h2", "h3", "h4"])
        pricing = BLOCKS.get(heading.get_text(" ", strip=True)) if heading else None
        if pricing is None:
            continue
        for item in block.select(".page-price_card_row_item"):
            cols = [
                c.get_text(" ", strip=True) for c in item.select(".page-price_card_row_item_col")
            ]
            gpu_model = MODELS.get(cols[0]) if cols else None
            price = re.fullmatch(r"\$(\d+(?:\.\d+)?)", cols[-1]) if cols else None
            if gpu_model is None or price is None:
                continue
            rows.append(
                observation(
                    stamp,
                    source="hyperstack",
                    provider=PROVIDER,
                    segment="neocloud",
                    pricing=pricing,
                    gpu_model=gpu_model,
                    sku=cols[0],
                    region="global",
                    geo="Global",
                    gpu_count=1,
                    usd_per_hour=float(price.group(1)),
                )
            )
    return rows


ADAPTER = SourceAdapter(
    id="hyperstack",
    name=PROVIDER,
    homepage=URL,
    terms="Public pricing page; robots.txt allows it and the terms and conditions have no "
    "crawling restriction. One request per day.",
    min_rows=4,
    fetch=fetch,
    parse=parse,
)
